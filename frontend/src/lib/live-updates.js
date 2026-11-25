/**
 * Live updates: one server-sent-event stream per signed-in tab
 * (docs/specs/sqlite-single-process/03-api-auth-web.md §C).
 *
 * `GET /live` is read with a streaming `fetch` carrying the normal Bearer
 * token (no token in a URL). Frames:
 *   event: ready       — the stream is open; catch up from the API
 *   event: invalidate  — data: {resource, operation, occurred_at}
 *   event: reauth      — the token behind the stream is expiring; reconnect
 *   event: revoked     — the session was signed out; stop
 *   : ping             — heartbeat (every 25 s)
 * A message is only a hint: consumers debounce by resource and refetch
 * through the API, so a lost message costs latency, never correctness.
 */

import { getAccessToken, refresh } from '$lib/auth.js';
import { getApiBaseUrl } from '$lib/api/http.js';

/**
 * @typedef {{resource: string, operation: string, entity_id?: string, occurred_at?: string}} LiveInvalidation
 */

const DEBOUNCE_MS = 350;
const MAX_BACKOFF_MS = 60_000;
/** No byte for this long (heartbeats come every 25 s) means a dead stream. */
const SILENCE_TIMEOUT_MS = 60_000;
const ALLOWED_RESOURCES = new Set([
	'events',
	'event_sources',
	'event_change_proposals',
	'calendar_work_items',
	'emails',
	'integrations'
]);

/** @type {string | null} */
let userId = null;
/** @type {AbortController | null} */
let controller = null;
/** Bumped whenever a connection is abandoned, so its late callbacks are ignored. */
let connectionGen = 0;
/** @type {ReturnType<typeof setTimeout> | null} */
let reconnectTimer = null;
/** @type {ReturnType<typeof setTimeout> | null} */
let watchdogTimer = null;
let debounceTimers = new Map();
let trailingRefresh = new Map();
let inFlight = new Map();
/** @type {Map<string, Set<(inv: LiveInvalidation) => void>>} */
let listeners = new Map();
let connectionStatus = 'disconnected';
// Must live at module scope, not inside start(): a reconnect calls connect()
// again, and a locally-declared counter would re-zero on every attempt, so the
// backoff would never advance past its first step.
let rejoinAttempts = 0;
let intentionalStop = true;

/**
 * Subscribe to invalidation for a resource.
 * @param {string} resource
 * @param {(inv: LiveInvalidation) => void} callback
 * @returns {() => void} unsubscribe
 */
export function subscribe(resource, callback) {
	if (!listeners.has(resource)) listeners.set(resource, new Set());
	/** @type {Set<(inv: LiveInvalidation) => void>} */ (listeners.get(resource)).add(callback);
	return () => {
		const set = listeners.get(resource);
		if (set) {
			set.delete(callback);
			if (set.size === 0) listeners.delete(resource);
		}
	};
}

/** @param {string} resource @param {LiveInvalidation} inv */
function emit(resource, inv) {
	const set = listeners.get(resource);
	if (!set) return;
	for (const cb of [...set]) {
		try {
			cb(inv);
		} catch (e) {
			console.error('[live-updates] listener error', e);
		}
	}
}

/** @param {string} resource @param {LiveInvalidation} inv */
function scheduleRefresh(resource, inv) {
	// Debounce per resource + coalesce burst
	if (inFlight.get(resource)) {
		trailingRefresh.set(resource, inv);
		return;
	}
	if (debounceTimers.has(resource)) {
		clearTimeout(debounceTimers.get(resource));
		trailingRefresh.set(resource, inv);
	}
	debounceTimers.set(resource, setTimeout(() => {
		debounceTimers.delete(resource);
		const latest = trailingRefresh.get(resource) || inv;
		trailingRefresh.delete(resource);
		inFlight.set(resource, true);
		emit(resource, latest);
		// Release in-flight on the next tick so trailing invalidations queue.
		setTimeout(() => {
			inFlight.delete(resource);
			if (trailingRefresh.has(resource)) {
				const pending = trailingRefresh.get(resource);
				trailingRefresh.delete(resource);
				scheduleRefresh(resource, pending);
			}
		}, 0);
	}, DEBOUNCE_MS));
}

/**
 * Force a catch-up refetch for every subscribed resource.
 * Used on (re)connect, tab-visible, window-focus and network-online.
 */
export function catchUp() {
	for (const resource of [...listeners.keys()]) {
		scheduleRefresh(resource, {
			resource,
			operation: 'CATCHUP',
			occurred_at: new Date().toISOString()
		});
	}
}

/** @param {unknown} payload */
function handleInvalidate(payload) {
	/** @type {LiveInvalidation & {payload?: LiveInvalidation}} */
	const message = /** @type {LiveInvalidation & {payload?: LiveInvalidation}} */ (payload);
	const inv = message?.payload || message;
	if (!inv || !inv.resource) return;
	if (!ALLOWED_RESOURCES.has(inv.resource)) return;
	console.debug('[live-updates] invalidate', inv);
	scheduleRefresh(inv.resource, inv);
}

function clearWatchdog() {
	if (watchdogTimer) clearTimeout(watchdogTimer);
	watchdogTimer = null;
}

function clearReconnect() {
	if (reconnectTimer) clearTimeout(reconnectTimer);
	reconnectTimer = null;
}

/** Abandon the current connection without scheduling anything. */
function dropConnection() {
	connectionGen += 1;
	clearWatchdog();
	if (controller) {
		try {
			controller.abort();
		} catch {
			// already aborted
		}
	}
	controller = null;
}

/** Reconnect after the backoff (1 s doubling to 60 s, plus 0–20 % jitter). */
function scheduleReconnect() {
	dropConnection();
	if (intentionalStop || !userId) return;
	clearReconnect();
	const base = Math.min(1000 * 2 ** rejoinAttempts, MAX_BACKOFF_MS);
	const delay = Math.round(base * (1 + Math.random() * 0.2));
	rejoinAttempts += 1;
	connectionStatus = 'reconnecting';
	reconnectTimer = setTimeout(() => {
		reconnectTimer = null;
		if (!intentionalStop && userId) connect();
	}, delay);
}

/** @param {number} gen */
function resetWatchdog(gen) {
	clearWatchdog();
	watchdogTimer = setTimeout(() => {
		watchdogTimer = null;
		if (gen !== connectionGen) return;
		console.warn('[live-updates] stream silent, reconnecting');
		scheduleReconnect();
	}, SILENCE_TIMEOUT_MS);
}

/**
 * Handle one SSE frame. Returns false when the stream must end.
 * @param {string} frame
 * @returns {boolean}
 */
function handleFrame(frame) {
	let event = 'message';
	/** @type {string[]} */
	const data = [];
	for (const line of frame.split(/\r?\n/)) {
		if (!line || line.startsWith(':')) continue;
		const colon = line.indexOf(':');
		const field = colon === -1 ? line : line.slice(0, colon);
		let value = colon === -1 ? '' : line.slice(colon + 1);
		if (value.startsWith(' ')) value = value.slice(1);
		if (field === 'event') event = value;
		else if (field === 'data') data.push(value);
	}
	if (event === 'ready') {
		rejoinAttempts = 0;
		connectionStatus = 'connected';
		catchUp();
	} else if (event === 'invalidate') {
		try {
			handleInvalidate(JSON.parse(data.join('\n')));
		} catch (e) {
			console.warn('[live-updates] bad invalidate frame', e);
		}
	} else if (event === 'reauth') {
		scheduleReconnect();
		return false;
	} else if (event === 'revoked') {
		stop();
		return false;
	}
	return true;
}

async function connect() {
	clearReconnect();
	dropConnection();
	const gen = connectionGen;
	const abort = new AbortController();
	controller = abort;
	connectionStatus = 'connecting';

	let token = getAccessToken();
	if (!token) token = await refresh();
	if (gen !== connectionGen) return;
	if (!token) {
		// The auth module signs out when the session is gone.
		stop();
		return;
	}

	let response;
	try {
		response = await fetch(`${getApiBaseUrl()}/live`, {
			headers: { Authorization: `Bearer ${token}`, Accept: 'text/event-stream' },
			cache: 'no-store',
			signal: abort.signal
		});
	} catch (error) {
		if (gen !== connectionGen) return;
		console.warn('[live-updates] connect failed', error);
		scheduleReconnect();
		return;
	}
	if (gen !== connectionGen) return;

	if (response.status === 401) {
		const renewed = await refresh();
		if (gen !== connectionGen) return;
		if (!renewed) {
			stop();
			return;
		}
		scheduleReconnect();
		return;
	}
	if (!response.ok || !response.body) {
		// 429 (too many streams), 503 (busy) and anything else: back off.
		scheduleReconnect();
		return;
	}

	const reader = response.body.getReader();
	const decoder = new TextDecoder();
	let buffer = '';
	resetWatchdog(gen);
	try {
		while (true) {
			const { value, done } = await reader.read();
			if (gen !== connectionGen) return;
			if (done) break;
			resetWatchdog(gen);
			buffer += decoder.decode(value, { stream: true });
			let boundary;
			while ((boundary = buffer.search(/\r?\n\r?\n/)) !== -1) {
				const frame = buffer.slice(0, boundary);
				const separator = /** @type {RegExpMatchArray} */ (buffer.slice(boundary).match(/^\r?\n\r?\n/));
				buffer = buffer.slice(boundary + separator[0].length);
				if (!handleFrame(frame)) {
					try {
						reader.cancel();
					} catch {
						// nothing to cancel
					}
					return;
				}
				if (gen !== connectionGen) return;
			}
		}
	} catch (error) {
		if (gen !== connectionGen) return;
		console.warn('[live-updates] stream error', error);
	}
	if (gen !== connectionGen) return;
	// The server ended the stream (restart, deploy, idle proxy): reconnect.
	scheduleReconnect();
}

/**
 * Open the live stream for a user. Idempotent for the same user; a different
 * user replaces the stream.
 * @param {string} uid
 */
export async function start(uid) {
	if (!uid) return;
	if (userId === uid && !intentionalStop) return;
	await stop();
	intentionalStop = false;
	userId = uid;
	connect();
}

/**
 * Reconnect with the current token after a token rotation, so the server's
 * stream lifetime follows the new token. A no-op while stopped.
 */
export async function refreshAuth() {
	if (intentionalStop || !userId) return;
	connect();
}

/**
 * Close the stream and cancel any reconnect. Idempotent.
 */
export async function stop() {
	intentionalStop = true;
	rejoinAttempts = 0;
	clearReconnect();
	dropConnection();
	userId = null;
	connectionStatus = 'disconnected';
	// Clear timers but keep listeners for re-subscribe
	for (const t of debounceTimers.values()) clearTimeout(t);
	debounceTimers.clear();
	trailingRefresh.clear();
	inFlight.clear();
}

export function getStatus() {
	return connectionStatus;
}

/** For tests: the reconnect attempt counter. */
export function getRejoinAttempts() {
	return rejoinAttempts;
}

// For tests
export function __resetForTests() {
	clearReconnect();
	dropConnection();
	userId = null;
	for (const t of debounceTimers.values()) clearTimeout(t);
	debounceTimers.clear();
	trailingRefresh.clear();
	inFlight.clear();
	listeners.clear();
	connectionStatus = 'disconnected';
	rejoinAttempts = 0;
	intentionalStop = true;
	connectionGen = 0;
}
