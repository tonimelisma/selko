/**
 * Sign-in state for the web app (03-api-auth-web.md §B.7, §B.10).
 *
 * The access token lives only in this module's memory; the refresh token lives
 * only in the HttpOnly `selko_refresh` cookie that `POST /auth/token` sets
 * (Path=/auth), so no script can read it and data requests never carry it.
 * A page load restores the session with one refresh request; a timer renews
 * the access token a minute before it expires; a 401 from the API triggers one
 * shared refresh (see `refresh`). Other tabs hear sign-in and sign-out over a
 * BroadcastChannel and follow at once.
 */

import { API_REQUEST_TIMEOUT_MS, getApiBaseUrl, parseApiError } from '$lib/api/http.js';

/**
 * @typedef {{ id: string, email: string }} AuthUser
 * @typedef {'SIGNED_IN' | 'TOKEN_REFRESHED' | 'SIGNED_OUT'} AuthEvent
 * @typedef {{ message: string, status: number, code?: string }} AuthError
 */

const CHANNEL_NAME = 'selko-auth';
/** Renew this long before the access token expires. */
const REFRESH_MARGIN_MS = 60_000;

/** @type {string | null} */
let accessToken = null;
/** @type {number} unix seconds */
let expiresAt = 0;
/** @type {AuthUser | null} */
let currentUser = null;
/** @type {ReturnType<typeof setTimeout> | null} */
let refreshTimer = null;
/** @type {Promise<string | null> | null} */
let refreshInFlight = null;
/** @type {Set<(event: AuthEvent, user: AuthUser | null) => void>} */
const listeners = new Set();
/** @type {BroadcastChannel | null} */
let channel = null;

/** @returns {string | null} the in-memory access token */
export function getAccessToken() {
	return accessToken;
}

/** @returns {AuthUser | null} */
export function getUser() {
	return currentUser;
}

/**
 * Listen for SIGNED_IN, TOKEN_REFRESHED and SIGNED_OUT.
 * @param {(event: AuthEvent, user: AuthUser | null) => void} callback
 * @returns {() => void} unsubscribe
 */
export function onAuthChange(callback) {
	listeners.add(callback);
	ensureChannel();
	return () => listeners.delete(callback);
}

/** @param {AuthEvent} event */
function emit(event) {
	for (const callback of [...listeners]) {
		try {
			callback(event, currentUser);
		} catch (error) {
			console.error('[auth] listener error', error);
		}
	}
}

function ensureChannel() {
	if (channel || typeof BroadcastChannel === 'undefined') return;
	try {
		channel = new BroadcastChannel(CHANNEL_NAME);
		channel.onmessage = (message) => {
			const type = message?.data?.type;
			if (type === 'SIGNED_OUT') {
				if (accessToken || currentUser) {
					clearSession();
					emit('SIGNED_OUT');
				}
			} else if (type === 'SIGNED_IN') {
				// The cookie jar is shared: this tab can take the new session too.
				refresh();
			}
		};
	} catch {
		channel = null;
	}
}

/** @param {'SIGNED_IN' | 'SIGNED_OUT'} type */
function broadcast(type) {
	ensureChannel();
	try {
		channel?.postMessage({ type });
	} catch {
		// A closed channel only costs the other tabs their instant update.
	}
}

function clearTimer() {
	if (refreshTimer) clearTimeout(refreshTimer);
	refreshTimer = null;
}

function clearSession() {
	clearTimer();
	accessToken = null;
	expiresAt = 0;
	currentUser = null;
}

/** @param {any} body */
function acceptTokens(body) {
	accessToken = body.access_token;
	expiresAt = Number(body.expires_at) || Math.floor(Date.now() / 1000) + Number(body.expires_in || 3600);
	currentUser = body.user ? { id: body.user.id, email: body.user.email } : currentUser;
	clearTimer();
	const delay = Math.max(expiresAt * 1000 - REFRESH_MARGIN_MS - Date.now(), 0);
	refreshTimer = setTimeout(() => {
		refreshTimer = null;
		refresh();
	}, delay);
}

/**
 * POST a JSON body to an /auth endpoint with the cookie jar.
 * @param {string} path
 * @param {Record<string, unknown>} body
 * @param {Record<string, string>} [headers]
 * @returns {Promise<Response>}
 */
async function authPost(path, body, headers = {}) {
	const controller = new AbortController();
	const timer = setTimeout(() => controller.abort(), API_REQUEST_TIMEOUT_MS);
	try {
		return await fetch(`${getApiBaseUrl()}${path}`, {
			method: 'POST',
			credentials: 'include',
			headers: { 'Content-Type': 'application/json', Accept: 'application/json', ...headers },
			body: JSON.stringify(body),
			signal: controller.signal
		});
	} finally {
		clearTimeout(timer);
	}
}

/** @param {unknown} error @returns {AuthError} */
function networkError(error) {
	const timedOut = error instanceof Error && error.name === 'AbortError';
	return {
		message: timedOut
			? 'The request timed out. Please try again.'
			: "Can't reach Selko. Check your connection and try again.",
		status: 0,
		code: timedOut ? 'TIMEOUT' : 'NETWORK_ERROR'
	};
}

/**
 * One refresh-grant request. `invalid` means the cookie is gone or dead;
 * `unavailable` means the server could not be reached or failed.
 * @returns {Promise<{ outcome: 'ok' | 'invalid' | 'unavailable' }>}
 */
async function requestRefresh() {
	let response;
	try {
		response = await authPost('/auth/token', { grant_type: 'refresh_token' });
	} catch {
		return { outcome: 'unavailable' };
	}
	if (response.ok) {
		acceptTokens(await response.json());
		return { outcome: 'ok' };
	}
	if (response.status === 400 || response.status === 401 || response.status === 403) {
		return { outcome: 'invalid' };
	}
	return { outcome: 'unavailable' };
}

/**
 * Renew the access token from the refresh cookie. Concurrent callers share one
 * request (single flight). Resolves to the new token, or null. A refused
 * refresh signs this tab out; an unreachable server keeps the current state.
 * @returns {Promise<string | null>}
 */
export function refresh() {
	if (!refreshInFlight) {
		refreshInFlight = (async () => {
			const hadSession = Boolean(accessToken || currentUser);
			const { outcome } = await requestRefresh();
			if (outcome === 'ok') {
				emit(hadSession ? 'TOKEN_REFRESHED' : 'SIGNED_IN');
				return accessToken;
			}
			if (outcome === 'invalid' && hadSession) {
				clearSession();
				emit('SIGNED_OUT');
			}
			return null;
		})().finally(() => {
			refreshInFlight = null;
		});
	}
	return refreshInFlight;
}

/**
 * Restore the session on page load from the refresh cookie.
 * @returns {Promise<{ user: AuthUser | null, unavailable: boolean }>}
 */
export async function restoreSession() {
	ensureChannel();
	if (refreshInFlight) {
		await refreshInFlight;
		return { user: currentUser, unavailable: false };
	}
	let outcome;
	refreshInFlight = requestRefresh()
		.then((result) => {
			outcome = result.outcome;
			return accessToken;
		})
		.finally(() => {
			refreshInFlight = null;
		});
	await refreshInFlight;
	// A sign-in that finished while this request was out wins over its refusal.
	if (outcome === 'ok' || accessToken) return { user: currentUser, unavailable: false };
	clearSession();
	return { user: null, unavailable: outcome === 'unavailable' };
}

/**
 * Sign in with email and password; the API sets the refresh cookie.
 * @param {string} email
 * @param {string} password
 * @returns {Promise<{ user: AuthUser | null, error: AuthError | null }>}
 */
export async function signIn(email, password) {
	let response;
	try {
		response = await authPost('/auth/token', { grant_type: 'password', email, password });
	} catch (error) {
		return { user: null, error: networkError(error) };
	}
	if (!response.ok) {
		const error = await parseApiError(response);
		return { user: null, error: { message: error.message, status: error.status, code: error.code } };
	}
	acceptTokens(await response.json());
	emit('SIGNED_IN');
	broadcast('SIGNED_IN');
	return { user: currentUser, error: null };
}

/**
 * Create an account. It does not sign in: the register page sends the user to
 * the sign-in page, as before.
 * @param {string} email
 * @param {string} password
 * @returns {Promise<{ data: { user: AuthUser, confirmation_required: boolean } | null, error: AuthError | null }>}
 */
export async function signUp(email, password) {
	let response;
	try {
		response = await authPost('/auth/signup', { email, password });
	} catch (error) {
		return { data: null, error: networkError(error) };
	}
	if (!response.ok) {
		const error = await parseApiError(response);
		return { data: null, error: { message: error.message, status: error.status, code: error.code } };
	}
	return { data: await response.json(), error: null };
}

/**
 * Sign out. `global` (the default, as before) ends every session of the user;
 * `local` only this one. The local state is dropped even when the request
 * fails, so the user is never left half signed in.
 * @param {{ scope?: 'local' | 'global' }} [options]
 * @returns {Promise<void>}
 */
export async function signOut(options = {}) {
	const { scope = 'global' } = options;
	const token = accessToken;
	clearSession();
	try {
		await authPost('/auth/logout', { scope }, token ? { Authorization: `Bearer ${token}` } : {});
	} catch (error) {
		console.warn('[auth] sign-out request failed', error);
	}
	emit('SIGNED_OUT');
	broadcast('SIGNED_OUT');
}

// For tests
export function __resetForTests() {
	clearSession();
	refreshInFlight = null;
	listeners.clear();
	if (channel) {
		try {
			channel.close();
		} catch {
			// already closed
		}
	}
	channel = null;
}
