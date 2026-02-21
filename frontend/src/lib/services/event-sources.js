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
 * @property {Object} [event_snapshot_before]
 * @property {boolean} is_undone
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

/**
 * Undo a source's contribution to an event
 * This marks the source as undone but doesn't delete it, allowing for redo
 * @param {string} sourceId - The source UUID
 * @returns {Promise<{data: EventSource | null, error: import('$lib/errors.js').SupabaseError | null}>}
 */
export async function undoSourceContribution(sourceId) {
	try {
		const { data, error } = await supabase
			.from('event_sources')
			.update({ is_undone: true })
			.eq('id', sourceId)
			.select()
			.single();

		if (error) throw error;

		return { data, error: null };
	} catch (error) {
		return { data: null, error: parseSupabaseError(error) };
	}
}

/**
 * Redo a previously undone source contribution
 * @param {string} sourceId - The source UUID
 * @returns {Promise<{data: EventSource | null, error: import('$lib/errors.js').SupabaseError | null}>}
 */
export async function redoSourceContribution(sourceId) {
	try {
		const { data, error } = await supabase
			.from('event_sources')
			.update({ is_undone: false })
			.eq('id', sourceId)
			.select()
			.single();

		if (error) throw error;

		return { data, error: null };
	} catch (error) {
		return { data: null, error: parseSupabaseError(error) };
	}
}

/**
 * Get count of active (non-undone) sources for an event
 * @param {string} eventId - The event UUID
 * @returns {Promise<{count: number, error: import('$lib/errors.js').SupabaseError | null}>}
 */
export async function getActiveSourceCount(eventId) {
	try {
		const { count, error } = await supabase
			.from('event_sources')
			.select('id', { count: 'exact', head: true })
			.eq('event_id', eventId)
			.eq('is_undone', false);

		if (error) throw error;

		return { count: count ?? 0, error: null };
	} catch (error) {
		return { count: 0, error: parseSupabaseError(error) };
	}
}
