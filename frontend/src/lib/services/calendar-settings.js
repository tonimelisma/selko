import { supabase } from '$lib/supabase.js';
import { parseSupabaseError } from '$lib/errors.js';

/**
 * @typedef {Object} CalendarSettings
 * @property {string} user_id - UUID
 * @property {string | null} target_calendar_id
 * @property {string | null} default_invitees - Comma-separated emails
 * @property {string} updated_at
 */

/**
 * @typedef {import('$lib/types.js').SupabaseServiceResult} SupabaseServiceResult
 */

/**
 * Get user's calendar settings
 * @returns {Promise<SupabaseServiceResult<CalendarSettings | null>>}
 */
export async function getCalendarSettings() {
	try {
		const { data, error } = await supabase
			.from('user_calendar_settings')
			.select('*')
			.maybeSingle();

		if (error) throw error;

		return { data, error: null };
	} catch (error) {
		return { data: null, error: parseSupabaseError(error) };
	}
}

/**
 * Update user's calendar settings
 * @param {Object} settings
 * @param {string} [settings.target_calendar_id] - Target calendar ID (null for primary)
 * @param {string} [settings.default_invitees] - Comma-separated emails
 * @returns {Promise<SupabaseServiceResult<CalendarSettings | null>>}
 */
export async function updateCalendarSettings(settings) {
	try {
		// Get current user ID
		const {
			data: { user }
		} = await supabase.auth.getUser();
		if (!user) throw new Error('Not authenticated');

		const { data, error } = await supabase
			.from('user_calendar_settings')
			.upsert({
				user_id: user.id,
				...settings,
				updated_at: new Date().toISOString()
			})
			.select()
			.single();

		if (error) throw error;

		return { data, error: null };
	} catch (error) {
		return { data: null, error: parseSupabaseError(error) };
	}
}
