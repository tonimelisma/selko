/**
 * LiveUpdateCoordinator — single private Broadcast channel per signed-in user.
 * Implements spec docs/specs/live-ui-updates.md §2-3.
 *
 * One topic: user:<uid>:selko-changes, event 'invalidate', payload
 * {resource, operation, entity_id, occurred_at} — invalidation hint only.
 * Consumers debounce by resource and refetch via existing RLS queries.
 */

import { supabase } from '$lib/supabase.js';

let channel = null;
let userId = null;
let debounceTimers = new Map();
let trailingRefresh = new Map();
let inFlight = new Map();
let listeners = new Map(); // resource -> Set<callback>
let connectionStatus = 'disconnected';

/**
 * @typedef {{resource: string, operation: string, entity_id?: string, occurred_at: string}} LiveInvalidation
 */

const DEBOUNCE_MS = 350;

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

function handleInvalidate(payload) {
	// payload is {resource, operation, entity_id, occurred_at}
	const inv = payload?.payload || payload;
	if (!inv || !inv.resource) return;
	const allowed = new Set(['events', 'event_sources', 'emails', 'integrations']);
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
			// Spec § reliability: fetch canonical snapshot on SUBSCRIBED
			// Consumers will have subscribed via subscribe(); we trigger a
			// synthetic refresh for each resource they care about.
			for (const resource of [...listeners.keys()]) {
				scheduleRefresh(resource, { resource, operation: 'SUBSCRIBED', occurred_at: new Date().toISOString() });
			}
		}
	});
}

/**
 * Stop and remove the channel. Idempotent.
 */
export async function stop() {
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
}
