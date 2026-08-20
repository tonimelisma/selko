/**
 * LiveUpdateCoordinator — single private Broadcast channel per signed-in user.
 * Implements spec docs/specs/live-ui-updates.md §2-3.
 *
 * One topic: user:<uid>:selko-changes, event 'invalidate', payload
 * {resource, operation, entity_id, occurred_at} — invalidation hint only.
 * Consumers debounce by resource and refetch via existing RLS queries.
 */

import { supabase } from '$lib/supabase.js';

/** @type {import('@supabase/supabase-js').RealtimeChannel | null} */
let channel = null;
/** @type {string | null} */
let userId = null;
let debounceTimers = new Map();
let trailingRefresh = new Map();
let inFlight = new Map();
let listeners = new Map(); // resource -> Set<callback>
let connectionStatus = 'disconnected';
// F1.1 (D1): must live at module scope, not inside start() — a rejoin calls
// start() again, and a locally-declared counter re-zeroes on every attempt,
// which is why the backoff never advanced past its first step.
let rejoinAttempts = 0;
let intentionalStop = false;

/**
 * @typedef {{resource: string, operation: string, entity_id?: string, occurred_at: string}} LiveInvalidation
 */

const DEBOUNCE_MS = 350;

/**
 * Re-authorize the realtime socket after a token rotation.
 * Private channels authorize per-JWT; without this the channel goes deaf
 * when the access token expires (~1h) and nothing reports it.
 * @param {string | null} accessToken
 */
export async function refreshAuth(accessToken) {
	if (!accessToken) return;
	try {
		await supabase.realtime.setAuth(accessToken);
	} catch (e) {
		console.warn('[live-updates] setAuth refresh failed', e);
	}
}

/**
 * Subscribe to invalidation for a resource.
 * @param {string} resource
 * @param {(inv: LiveInvalidation) => void} callback
 * @returns {() => void} unsubscribe
 */
export function subscribe(resource, callback) {
	if (!listeners.has(resource)) listeners.set(resource, new Set());
	listeners.get(resource).add(callback);
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
		// keep latest inv
		trailingRefresh.set(resource, inv);
	}
	debounceTimers.set(resource, setTimeout(() => {
		debounceTimers.delete(resource);
		const latest = trailingRefresh.get(resource) || inv;
		trailingRefresh.delete(resource);
		inFlight.set(resource, true);
		emit(resource, latest);
		// Release in-flight after handler runs — consumers call fetch which is async;
		// we release on next tick so trailing invalidations queue correctly.
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
 * Used on tab-visible, window-focus and network-online. Unlike start(),
 * this does not short-circuit when the channel already exists.
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
	// payload is {resource, operation, entity_id, occurred_at}
	/** @type {LiveInvalidation & {payload?: LiveInvalidation}} */
	const message = /** @type {LiveInvalidation & {payload?: LiveInvalidation}} */ (payload);
	const inv = message?.payload || message;
	if (!inv || !inv.resource) return;
	const allowed = new Set(['events', 'event_sources', 'event_change_proposals', 'calendar_work_items', 'emails', 'integrations']);
	if (!allowed.has(inv.resource)) return;
	console.debug('[live-updates] invalidate', inv);
	scheduleRefresh(inv.resource, inv);
}

/**
 * Start the private channel for a user.
 * Idempotent — calling with same userId is no-op; different user re-creates.
 * Must call supabase.realtime.setAuth() before join for private channels.
 * @param {string} uid
 */
export async function start(uid) {
	if (!uid) return;
	if (userId === uid && channel) return;
	await stop();
	intentionalStop = false;
	userId = uid;
	connectionStatus = 'connecting';

	// Ensure realtime auth is set for private channel
	try {
		const { data: { session } } = await supabase.auth.getSession();
		if (session?.access_token) {
			await supabase.realtime.setAuth(session.access_token);
		}
	} catch (e) {
		console.warn('[live-updates] setAuth failed', e);
	}

	const topic = `user:${uid}:selko-changes`;
	channel = supabase.channel(topic, { config: { private: true } });

	channel.on('broadcast', { event: 'invalidate' }, (payload) => {
		handleInvalidate(payload);
	});

	channel.subscribe((status) => {
		connectionStatus = status;
		console.debug('[live-updates] channel status', status);
		if (status === 'SUBSCRIBED') {
			rejoinAttempts = 0;
			catchUp();
			return;
		}
		if (status === 'CHANNEL_ERROR' || status === 'TIMED_OUT' || status === 'CLOSED') {
			// A deliberate stop() (sign-out, layout teardown) must not schedule
			// a rejoin — only an unexpected drop should self-heal.
			if (intentionalStop) return;
			// A private channel that fails authorization will not self-heal.
			// Rejoin with backoff and catch up from the database on success —
			// the database is the source of truth, the channel is a hint.
			const delay = Math.min(1000 * 2 ** rejoinAttempts, 60000);
		const nextRejoinAttempts = rejoinAttempts + 1;
		rejoinAttempts = nextRejoinAttempts;
			const uid = userId;
			setTimeout(() => {
				if (!uid) return;
				stop()
					.then(() => start(uid))
					.then(() => {
						rejoinAttempts = nextRejoinAttempts;
					})
					.catch((error) => {
						console.warn('[live-updates] rejoin failed', error);
					});
			}, delay);
		}
	});
}

/**
 * Stop and remove the channel. Idempotent.
 */
export async function stop() {
	intentionalStop = true;
	rejoinAttempts = 0;
	if (channel) {
		try {
			await supabase.removeChannel(channel);
		} catch (e) {
			console.warn('[live-updates] removeChannel failed', e);
		}
		channel = null;
	}
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

export function getChannel() {
	return channel;
}

// For tests
export function __resetForTests() {
	if (channel) {
		try { supabase.removeChannel(channel); } catch {}
		channel = null;
	}
	userId = null;
	for (const t of debounceTimers.values()) clearTimeout(t);
	debounceTimers.clear();
	trailingRefresh.clear();
	inFlight.clear();
	listeners.clear();
	connectionStatus = 'disconnected';
	rejoinAttempts = 0;
	intentionalStop = false;
}
