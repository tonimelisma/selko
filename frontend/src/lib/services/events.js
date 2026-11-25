import { apiFetch } from '$lib/api/client.js';
import { toAppError } from '$lib/errors.js';

/**
 * @typedef {import('$lib/types.js').CalendarEvent} CalendarEvent
 * @typedef {import('$lib/types.js').EventStatus} EventStatus
 * @typedef {import('$lib/errors.js').AppError} AppError
 */

/** Largest page `GET /events/activity` accepts. */
const MAX_PAGE = 500;

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
 * Get a single event with its sources, proposals and calendar work, plus the
 * server-derived delivery `status`.
 * @param {string} eventId - The event UUID
 * @returns {Promise<{data: CalendarEvent | null, error: AppError | null}>}
 */
export async function getEvent(eventId) {
	const { data, error } = await apiFetch(`/events/${encodeURIComponent(eventId)}`);
	if (error) return { data: null, error: toAppError(error) };
	return { data, error: null };
}

/**
 * Record the user's review decision (approve or reject a New event).
 * @param {string} eventId - The event UUID
 * @param {'approved' | 'rejected'} status - The decision
 * @returns {Promise<{data: {event_id: string, review_status: string, work_item_id: string | null, generation: number | null} | null, error: AppError | null}>}
 */
export async function updateEventStatus(eventId, status) {
	if (status !== 'approved' && status !== 'rejected') {
		return { data: null, error: toAppError(new Error(`Unsupported review transition: ${status}`)) };
	}
	const action = status === 'approved' ? 'accept' : 'reject';
	const { data, error } = await apiFetch(`/events/${encodeURIComponent(eventId)}/${action}`, {
		method: 'POST'
	});
	if (error) return { data: null, error: toAppError(error) };
	return { data, error: null };
}

/**
 * The Review queue: upcoming New events and events with a pending change.
 * @returns {Promise<{data: CalendarEvent[], error: AppError | null}>}
 */
export async function fetchPendingEventsWithSources() {
	const { data, error } = await apiFetch('/events/review');
	if (error) return { data: [], error: toAppError(error) };
	return { data: data ?? [], error: null };
}

/**
 * Fetch decided events for the History screen, newest change first.
 * @param {Object} [options={}]
 * @param {number} [options.limit=20] - Maximum number of events to fetch (≤ 500)
 * @param {number} [options.offset=0] - Offset for pagination
 * @returns {Promise<{data: CalendarEvent[], count: number | null, error: AppError | null}>}
 */
export async function fetchActivityEvents(options = {}) {
	const { limit = 20, offset = 0 } = options;
	const { data, error } = await apiFetch('/events/activity', {
		query: { limit: Math.min(Math.max(1, limit), MAX_PAGE), offset: Math.max(0, offset) }
	});
	if (error) return { data: [], count: null, error: toAppError(error) };
	return { data: data?.items ?? [], count: data?.total ?? null, error: null };
}

/**
 * Update event details. Resolves to the full event (relations and status).
 * @param {string} eventId - The event UUID
 * @param {Partial<Pick<CalendarEvent, 'title' | 'start_datetime' | 'end_datetime' | 'all_day' | 'location' | 'description'>>} updates
 * @returns {Promise<{data: CalendarEvent | null, error: AppError | null}>}
 */
export async function updateEvent(eventId, updates) {
	/** @type {Record<string, unknown>} */
	const body = {};
	for (const [key, value] of Object.entries(updates)) {
		if (value !== undefined) body[key] = value;
	}
	const { data, error } = await apiFetch(`/events/${encodeURIComponent(eventId)}`, {
		method: 'PATCH',
		body
	});
	if (error) return { data: null, error: toAppError(error) };
	return { data, error: null };
}
