import { supabase } from '$lib/supabase.js';
import { parseSupabaseError } from '$lib/errors.js';

/**
 * @typedef {import('$lib/types.js').CalendarEvent} CalendarEvent
 * @typedef {import('$lib/types.js').EventStatus} EventStatus
 */

/**
 * @typedef {Object} FetchEventsOptions
 * @property {number} [limit=50] - Maximum number of events to fetch
 * @property {number} [offset=0] - Offset for pagination
 * @property {EventStatus[]} [statuses] - Filter by status(es)
 * @property {string} [startAfter] - Only events starting after this ISO date
 * @property {string} [startBefore] - Only events starting before this ISO date
 */

/**
 * Fetch events pending user review
 * @returns {Promise<{data: CalendarEvent[], count: number | null, error: import('$lib/errors.js').SupabaseError | null}>}
 */
export async function fetchPendingEvents() {
	try {
		const { data, error, count } = await supabase
			.from('events')
			.select('*', { count: 'exact' })
			.eq('status', 'pending_review')
			.order('start_datetime', { ascending: true });

		if (error) throw error;

		return { data: data ?? [], count, error: null };
	} catch (error) {
		return { data: [], count: null, error: parseSupabaseError(error) };
	}
}

/**
 * Fetch events with optional filters
 * @param {FetchEventsOptions} [options={}]
 * @returns {Promise<{data: CalendarEvent[], count: number | null, error: import('$lib/errors.js').SupabaseError | null}>}
 */
export async function fetchEvents(options = {}) {
	const { limit = 50, offset = 0, statuses, startAfter, startBefore } = options;

	try {
		let query = supabase
			.from('events')
			.select('*', { count: 'exact' })
			.order('start_datetime', { ascending: true })
			.range(offset, offset + limit - 1);

		if (statuses && statuses.length > 0) {
			query = query.in('status', statuses);
		}
		if (startAfter) {
			query = query.gte('start_datetime', startAfter);
		}
		if (startBefore) {
			query = query.lte('start_datetime', startBefore);
		}

		const { data, error, count } = await query;

		if (error) throw error;

		return { data: data ?? [], count, error: null };
	} catch (error) {
		return { data: [], count: null, error: parseSupabaseError(error) };
	}
}

/**
 * Get a single event by ID
 * @param {string} eventId - The event UUID
 * @returns {Promise<{data: CalendarEvent | null, error: import('$lib/errors.js').SupabaseError | null}>}
 */
export async function getEvent(eventId) {
	try {
		const { data, error } = await supabase.from('events').select('*').eq('id', eventId).single();

		if (error) throw error;

		return { data, error: null };
	} catch (error) {
		return { data: null, error: parseSupabaseError(error) };
	}
}

/**
 * Update event status (approve, reject, etc.)
 * @param {string} eventId - The event UUID
 * @param {EventStatus} status - New status
 * @returns {Promise<{data: CalendarEvent | null, error: import('$lib/errors.js').SupabaseError | null}>}
 */
export async function updateEventStatus(eventId, status) {
	try {
		const { data, error } = await supabase
			.from('events')
			.update({ status })
			.eq('id', eventId)
			.select()
			.single();

		if (error) throw error;

		return { data, error: null };
	} catch (error) {
		return { data: null, error: parseSupabaseError(error) };
	}
}

/**
 * Fetch pending events with source email info for Review Queue grouping
 * @returns {Promise<{data: CalendarEvent[], error: import('$lib/errors.js').SupabaseError | null}>}
 */
export async function fetchPendingEventsWithSources() {
	try {
		const { data: events, error: eventsError } = await supabase
			.from('events')
			.select('*, event_sources(*, emails(id, subject, from_email, from_name, date_sent))')
			.eq('status', 'pending_review')
			.order('start_datetime', { ascending: true });
		if (eventsError) throw eventsError;
		return { data: events ?? [], error: null };
	} catch (error) {
		return { data: [], error: parseSupabaseError(error) };
	}
}

/**
 * Fetch activity events for History screen
 * @param {Object} [options={}]
 * @param {number} [options.limit=20] - Maximum number of events to fetch
 * @param {number} [options.offset=0] - Offset for pagination
 * @returns {Promise<{data: CalendarEvent[], count: number | null, error: import('$lib/errors.js').SupabaseError | null}>}
 */
export async function fetchActivityEvents(options = {}) {
	const { limit = 20, offset = 0 } = options;
	try {
		const { data, error, count } = await supabase
			.from('events')
			.select('*, event_sources(*, emails(id, subject, from_email, from_name, date_sent))', {
				count: 'exact'
			})
			.in('status', ['approved', 'synced', 'sync_failed', 'rejected', 'cancelled'])
			.order('updated_at', { ascending: false })
			.range(offset, offset + limit - 1);
		if (error) throw error;
		return { data: data ?? [], count, error: null };
	} catch (error) {
		return { data: [], count: null, error: parseSupabaseError(error) };
	}
}

/**
 * Update event details
 * @param {string} eventId - The event UUID
 * @param {Partial<Pick<CalendarEvent, 'title' | 'start_datetime' | 'end_datetime' | 'all_day' | 'location' | 'description'>>} updates
 * @returns {Promise<{data: CalendarEvent | null, error: import('$lib/errors.js').SupabaseError | null}>}
 */
export async function updateEvent(eventId, updates) {
	try {
		const { data, error } = await supabase
			.from('events')
			.update(updates)
			.eq('id', eventId)
			.select()
			.single();

		if (error) throw error;

		return { data, error: null };
	} catch (error) {
		return { data: null, error: parseSupabaseError(error) };
	}
}
