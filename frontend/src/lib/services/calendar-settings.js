import { apiFetch } from '$lib/api/client.js';
import { toAppError } from '$lib/errors.js';

/**
 * @typedef {'all_day' | 'day_9_to_5' | 'morning_8_to_9' | 'custom'} AllDayDisplayMode
 */

/**
 * @typedef {Object} CalendarSettings
 * @property {string} user_id - UUID
 * @property {string | null} target_calendar_id
 * @property {string | null} default_invitees - Comma-separated emails
 * @property {string | null} [timezone]
 * @property {AllDayDisplayMode} [all_day_display_mode]
 * @property {string | null} [all_day_custom_start] - HH:MM or HH:MM:SS
 * @property {string | null} [all_day_custom_end] - HH:MM or HH:MM:SS
 * @property {string} updated_at
 */

/**
 * Get the user's calendar settings (null when none are saved yet).
 * @returns {Promise<{data: CalendarSettings | null, error: import('$lib/errors.js').AppError | null}>}
 */
export async function getCalendarSettings() {
	const { data, error } = await apiFetch('/settings/calendar');
	if (error) return { data: null, error: toAppError(error) };
	return { data: data?.settings ?? null, error: null };
}

/**
 * Update the user's calendar settings; only the given fields change.
 * @param {Object} settings
 * @param {string | null} [settings.target_calendar_id] - Target calendar ID (null for primary)
 * @param {string | null} [settings.default_invitees] - Comma-separated emails
 * @param {AllDayDisplayMode} [settings.all_day_display_mode]
 * @param {string | null} [settings.all_day_custom_start]
 * @param {string | null} [settings.all_day_custom_end]
 * @returns {Promise<{data: CalendarSettings | null, error: import('$lib/errors.js').AppError | null}>}
 */
export async function updateCalendarSettings(settings) {
	/** @type {Record<string, unknown>} */
	const body = {};
	for (const [key, value] of Object.entries(settings)) {
		if (value !== undefined) body[key] = value;
	}
	const { data, error } = await apiFetch('/settings/calendar', { method: 'PATCH', body });
	if (error) return { data: null, error: toAppError(error) };
	return { data: data?.settings ?? null, error: null };
}
