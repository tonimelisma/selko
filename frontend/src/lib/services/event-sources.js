import { supabase } from '$lib/supabase.js';
import { parseSupabaseError } from '$lib/errors.js';

/**
 * @typedef {'new_invitation' | 'update' | 'cancellation' | 'reminder' | 'unknown'} SourceType
 */

/**
 * @typedef {Object} ExtractedData
 * @property {string} [title]
 * @property {string} [start_datetime]
 * @property {string} [end_datetime]
 * @property {string} [location]
 * @property {string} [description]
 * @property {string} [source_quote]
 */

/**
 * @typedef {'email' | 'google_calendar' | 'google_photos'} SourceOrigin
 */

/**
 * @typedef {Object} EventSource
 * @property {string} id - UUID
 * @property {string} event_id - UUID
 * @property {string} [email_id] - UUID (required for email sources)
 * @property {SourceOrigin} source_origin - Source type: email, google_calendar, or google_photos
 * @property {SourceType} source_type
 * @property {ExtractedData} [extracted_data]
 * @property {string} created_at
 * @property {Object} [emails] - Joined email data
 */

/**
 * Fetch all sources for an event
 * @param {string} eventId - The event UUID
 * @returns {Promise<{data: EventSource[], error: import('$lib/errors.js').SupabaseError | null}>}
 */
export async function fetchEventSources(eventId) {
	try {
		const { data, error } = await supabase
			.from('event_sources')
			.select(
				`
				*,
				emails(id, subject, from_email, from_name, date_sent)
			`
			)
			.eq('event_id', eventId)
			.order('created_at', { ascending: true });

		if (error) throw error;

		return { data: data ?? [], error: null };
	} catch (error) {
		return { data: [], error: parseSupabaseError(error) };
	}
}
