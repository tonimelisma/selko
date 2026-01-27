import { writable } from 'svelte/store';
import { supabase } from './supabase.js';

/**
 * @typedef {import('./types.js').Email} Email
 * @typedef {import('./types.js').CalendarEvent} CalendarEvent
 * @typedef {import('./types.js').Integration} Integration
 */

// Auth stores
/** @type {import('svelte/store').Writable<import('@supabase/supabase-js').User | null>} */
export const user = writable(null);
export const loading = writable(true);

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

export async function initAuth() {
	const { data: { session } } = await supabase.auth.getSession();
	user.set(session?.user ?? null);
	loading.set(false);

	supabase.auth.onAuthStateChange((_event, session) => {
		user.set(session?.user ?? null);
	});
}
