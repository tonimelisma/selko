import { supabase } from '$lib/supabase.js';
import { parseSupabaseError } from '$lib/errors.js';

/**
 * @typedef {import('$lib/types.js').CalendarEvent} CalendarEvent
 * @typedef {import('$lib/types.js').EventStatus} EventStatus
 */

const EVENT_RELATIONS = `*, event_sources(*, emails(id, subject, from_email, from_name, date_sent)), event_change_proposals(id, event_id, user_id, source_id, kind, status, change_set, event_snapshot_before, resolution_reason, created_at, resolved_at, updated_at), calendar_work_items(id, event_id, user_id, action, generation, status, desired_event, provider_event_id, expected_provider_revision, force_overwrite, attempts, max_attempts, next_retry_at, failure_code, failure_detail, created_at, updated_at, completed_at)`;

/** @param {any} event */
export function pendingEventProposal(event) {
	return (event?.event_change_proposals || []).find(
		/** @param {any} proposal */
		(proposal) => proposal?.status === 'pending'
	) || null;
}

/** @param {any} event */
export function isNewReviewEvent(event) {
	return event?.review_status === 'pending_review' || (!event?.review_status && event?.status === 'pending_review');
}

/** @param {any} event */
export function isChangeReviewEvent(event) {
	return Boolean(pendingEventProposal(event));
}

/** @param {any} event */
export function isHistoryEvent(event) {
	return !isNewReviewEvent(event) && !isChangeReviewEvent(event);
}

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
		const nowIso = new Date().toISOString();
		const { data, error, count } = await supabase
			.from('events')
			.select('*', { count: 'exact' })
			.eq('status', 'pending_review')
			.or(`end_datetime.gte.${nowIso},and(end_datetime.is.null,start_datetime.gte.${nowIso}),and(end_datetime.is.null,start_datetime.is.null)`)
			.order('start_datetime', { ascending: true });

		if (error) throw error;

		const now = new Date(nowIso);
		const filtered = (data ?? []).filter((event) => {
			const raw = event.end_datetime || event.start_datetime;
			if (!raw) return true;
			return new Date(raw) >= now;
		});
		return { data: filtered, count: filtered.length, error: null };
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
		const { data, error } = await supabase.from('events').select(EVENT_RELATIONS).eq('id', eventId).single();

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
 * Fetch pending New + Changes events with source email info for Review Queue
 * @returns {Promise<{data: CalendarEvent[], error: import('$lib/errors.js').SupabaseError | null}>}
 */
export async function fetchPendingEventsWithSources() {
	try {
		const nowIso = new Date().toISOString();
		const { data: events, error: eventsError } = await supabase
			.from('events')
			.select(EVENT_RELATIONS)
			.in('review_status', ['pending_review', 'active'])
			.or(`end_datetime.gte.${nowIso},and(end_datetime.is.null,start_datetime.gte.${nowIso}),and(end_datetime.is.null,start_datetime.is.null)`)
			.order('start_datetime', { ascending: true });
		if (eventsError) throw eventsError;
		const now = new Date(nowIso);
		const filtered = (events ?? []).filter((event) => {
			if (!isNewReviewEvent(event) && !isChangeReviewEvent(event)) return false;
			const raw = event.end_datetime || event.start_datetime;
			if (!raw) return true;
			return new Date(raw) >= now;
		});
		return { data: filtered, error: null };
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
			.select(EVENT_RELATIONS, {
				count: 'exact'
			})
			.in('review_status', ['active', 'rejected', 'cancelled'])
			.order('updated_at', { ascending: false })
			.range(offset, offset + limit - 1);
		if (error) throw error;
		return { data: (data ?? []).filter(isHistoryEvent), count, error: null };
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
