import { supabase } from '$lib/supabase.js';
import { parseSupabaseError } from '$lib/errors.js';

/**
 * @typedef {import('$lib/types.js').CalendarEvent} CalendarEvent
 * @typedef {import('$lib/types.js').EventStatus} EventStatus
*/

const EVENT_RELATIONS = `*, event_sources(*, emails(id, subject, from_email, from_name, date_sent)), event_change_proposals(id, event_id, user_id, source_id, kind, status, change_set, event_snapshot_before, resolution_reason, created_at, resolved_at, updated_at), calendar_work_items(id, event_id, user_id, action, generation, status, provider_event_id, expected_provider_revision, force_overwrite, attempts, max_attempts, next_retry_at, failure_code, failure_detail, created_at, updated_at, completed_at)`;

/** @param {any} event */
function latestCalendarWorkItem(event) {
	return [...(event?.calendar_work_items || [])]
		.filter((item) => item?.status !== 'superseded')
		.sort((left, right) => (right?.generation || 0) - (left?.generation || 0))[0] || null;
}

/**
 * Derive the user-facing delivery state from the authoritative review state
 * and the latest worker-owned calendar item. This is deliberately client
 * state, not a persisted events column.
 * @param {any} event
 * @returns {EventStatus}
 */
export function deriveEventStatus(event) {
	if (event?.review_status === 'pending_review') return 'pending_review';
	if (event?.review_status === 'rejected') return 'rejected';
	if (event?.review_status === 'cancelled') return 'cancelled';

	const item = latestCalendarWorkItem(event);
	if (!item) return event?.google_calendar_event_id ? 'synced' : 'approved';
	const oauthBlocked = ['oauth_required', 'oauth_scope_required'].includes(item.failure_code);
	if (item.action === 'cancel') {
		if (item.status === 'succeeded') return 'cancelled';
		if (item.status === 'failed' || item.status === 'blocked') return oauthBlocked ? 'cancel_queued' : 'sync_failed';
		return 'cancel_queued';
	}
	if (item.status === 'processing') return 'syncing';
	if (item.status === 'succeeded') return 'synced';
	if (item.status === 'failed' || item.status === 'blocked') return oauthBlocked ? 'approved' : 'sync_failed';
	return 'approved';
}

/** @param {any} event */
function withDeliveryStatus(event) {
	return { ...event, status: deriveEventStatus(event) };
}

/** @param {any} event */
export function pendingEventProposal(event) {
	return (event?.event_change_proposals || []).find(
		/** @param {any} proposal */
		(proposal) => proposal?.status === 'pending'
	) || null;
}

/** @param {any} event */
export function isNewReviewEvent(event) {
	return event?.review_status === 'pending_review';
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
			.eq('review_status', 'pending_review')
			.or(`end_datetime.gte.${nowIso},and(end_datetime.is.null,start_datetime.gte.${nowIso}),and(end_datetime.is.null,start_datetime.is.null)`)
			.order('start_datetime', { ascending: true });

		if (error) throw error;

		const now = new Date(nowIso);
		const filtered = (data ?? []).filter((event) => {
			const raw = event.end_datetime || event.start_datetime;
			if (!raw) return true;
			return new Date(raw) >= now;
		});
		return { data: filtered.map(withDeliveryStatus), count: filtered.length, error: null };
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
			.order('start_datetime', { ascending: true });

		if (statuses && statuses.length > 0 && statuses.every((status) => ['pending_review', 'rejected', 'cancelled'].includes(status))) {
			query = query.in('review_status', statuses);
		}
		if (startAfter) {
			query = query.gte('start_datetime', startAfter);
		}
		if (startBefore) {
			query = query.lte('start_datetime', startBefore);
		}
		query = query.range(offset, offset + limit - 1);

		const { data, error, count } = await query;

		if (error) throw error;

		return { data: (data ?? []).map(withDeliveryStatus), count, error: null };
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

		return { data: withDeliveryStatus(data), error: null };
	} catch (error) {
		return { data: null, error: parseSupabaseError(error) };
	}
}

/**
 * Update the authoritative review state (approve or reject).
 * @param {string} eventId - The event UUID
 * @param {EventStatus} status - New status
 * @returns {Promise<{data: CalendarEvent | null, error: import('$lib/errors.js').SupabaseError | null}>}
 */
export async function updateEventStatus(eventId, status) {
	try {
		if (!['approved', 'rejected'].includes(status)) {
			throw new Error(`Unsupported review transition: ${status}`);
		}
		const { data, error } = await supabase.rpc('set_event_review_status', {
			p_event_id: eventId,
			p_review_status: status === 'approved' ? 'active' : 'rejected'
		});

		if (error) throw error;

		return { data: data ? withDeliveryStatus(data) : data, error: null };
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
		return { data: filtered.map(withDeliveryStatus), error: null };
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
			.not('event_change_proposals.status', 'eq', 'pending')
			.order('updated_at', { ascending: false })
			.range(offset, offset + limit - 1);
		if (error) throw error;
		return { data: (data ?? []).map(withDeliveryStatus), count, error: null };
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
