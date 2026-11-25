import { apiFetch } from '$lib/api/client.js';
import { toAppError } from '$lib/errors.js';
import { reprocessEmail } from '$lib/api/backend.js';

const MAX_PAGE = 500;

/**
 * Fetch the user-facing processing history, newest first: processed and
 * failed emails, plus skipped calendar invites (kept as the audit trail).
 * Each row carries the event sources and their events' outcomes.
 * @param {{limit?: number, offset?: number}} [options]
 * @returns {Promise<{data: any[], count: number | null, error: import('$lib/errors.js').AppError | null}>}
 */
export async function fetchEmailHistory(options = {}) {
	const { limit = 20, offset = 0 } = options;
	const { data, error } = await apiFetch('/emails/history', {
		query: { limit: Math.min(Math.max(1, limit), MAX_PAGE), offset: Math.max(0, offset) }
	});
	if (error) return { data: [], count: null, error: toAppError(error) };
	return { data: data?.items ?? [], count: data?.total ?? null, error: null };
}

/**
 * Reprocess an email, returning the API error without mutating the visible row
 * until the next refresh confirms the queued state.
 * @param {string} emailId
 */
export async function queueEmailReprocess(emailId) {
	return reprocessEmail(emailId);
}

/**
 * Fetch only the processing fields needed while a user-initiated reprocess is
 * running. Keeping this narrow avoids refreshing the whole History page.
 * @param {string} emailId
 * @returns {Promise<{data: any, error: import('$lib/errors.js').AppError | null}>}
 */
export async function fetchEmailProcessingState(emailId) {
	const { data, error } = await apiFetch(`/emails/${encodeURIComponent(emailId)}/processing-state`);
	if (error) return { data: null, error: toAppError(error) };
	return { data, error: null };
}
