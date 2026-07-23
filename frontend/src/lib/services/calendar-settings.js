import { supabase } from '$lib/supabase.js';
import { parseSupabaseError } from '$lib/errors.js';

/**
 * @typedef {'all_day' | 'day_9_to_5' | 'morning_8_to_9' | 'custom'} AllDayDisplayMode
 */

/**
 * @typedef {Object} CalendarSettings
 * @property {string} user_id - UUID
 * @property {string | null} target_calendar_id
 * @property {string | null} default_invitees - Comma-separated emails
 * @property {AllDayDisplayMode} [all_day_display_mode]
 * @property {string | null} [all_day_custom_start] - HH:MM or HH:MM:SS
 * @property {string | null} [all_day_custom_end] - HH:MM or HH:MM:SS
 * @property {string} updated_at
 */

/**
 * Get user's calendar settings
 * @returns {Promise<{data: CalendarSettings | null, error: import('$lib/errors.js').SupabaseError | null}>}
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
 * @param {AllDayDisplayMode} [settings.all_day_display_mode]
 * @param {string | null} [settings.all_day_custom_start]
 * @param {string | null} [settings.all_day_custom_end]
 * @returns {Promise<{data: CalendarSettings | null, error: import('$lib/errors.js').SupabaseError | null}>}
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
