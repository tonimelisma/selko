import { writable } from 'svelte/store';
import { onAuthChange, restoreSession } from './auth.js';

/**
 * @typedef {import('./types.js').Email} Email
 * @typedef {import('./types.js').CalendarEvent} CalendarEvent
 * @typedef {import('./types.js').Integration} Integration
 * @typedef {import('./types.js').AuthUser} AuthUser
 */

// Auth stores
/** @type {import('svelte/store').Writable<AuthUser | null>} */
export const user = writable(null);
export const loading = writable(true);
/**
 * True when the session could not be restored because Selko was unreachable,
 * so the app shows "Can't reach Selko" instead of sending a signed-in user to
 * the login page.
 * @type {import('svelte/store').Writable<boolean>}
 */
export const authUnavailable = writable(false);

// Data stores
/** @type {import('svelte/store').Writable<Email[]>} */
export const emails = writable([]);
/** @type {import('svelte/store').Writable<boolean>} */
export const emailsLoading = writable(false);

/** @type {import('svelte/store').Writable<CalendarEvent[]>} */
export const pendingEvents = writable([]);
/** @type {import('svelte/store').Writable<boolean>} */
export const pendingEventsLoading = writable(false);

/** @type {import('svelte/store').Writable<Integration[]>} */
export const integrations = writable([]);
/** @type {import('svelte/store').Writable<boolean>} */
export const integrationsLoading = writable(false);

/** @type {(() => void) | null} */
let unsubscribeAuth = null;

/** Restore the session (one refresh request) and follow auth changes. */
export async function initAuth() {
	if (!unsubscribeAuth) {
		unsubscribeAuth = onAuthChange((event, authUser) => {
			user.set(authUser);
			if (authUser) authUnavailable.set(false);
			if (event === 'TOKEN_REFRESHED' || event === 'SIGNED_IN') {
				import('$lib/live-updates.js').then((m) => m.refreshAuth());
			}
		});
	}
	await retryAuth();
}

/** Try restoring the session again (the "Can't reach Selko" Retry). */
export async function retryAuth() {
	loading.set(true);
	const { user: restored, unavailable } = await restoreSession();
	user.set(restored);
	authUnavailable.set(unavailable);
	loading.set(false);
}
