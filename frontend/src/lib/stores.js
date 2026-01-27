import { writable } from 'svelte/store';
import { supabase } from './supabase.js';

export const user = writable(null);
export const loading = writable(true);

export async function initAuth() {
	const { data: { session } } = await supabase.auth.getSession();
	user.set(session?.user ?? null);
	loading.set(false);

	supabase.auth.onAuthStateChange((_event, session) => {
		user.set(session?.user ?? null);
	});
}
