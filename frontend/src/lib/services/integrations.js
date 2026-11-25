import { apiFetch } from '$lib/api/client.js';
import { toAppError } from '$lib/errors.js';

/**
 * @typedef {import('$lib/types.js').Integration} Integration
 * @typedef {import('$lib/types.js').IntegrationRecovery} IntegrationRecovery
 * @typedef {import('$lib/errors.js').AppError} AppError
 */

/**
 * Fetch all integrations for the current user, newest first. The API never
 * sends token columns.
 * @returns {Promise<{data: Integration[], count: number | null, error: AppError | null}>}
 */
export async function fetchIntegrations() {
	const { data, error } = await apiFetch('/integrations');
	if (error) return { data: [], count: null, error: toAppError(error) };
	const rows = data ?? [];
	return { data: rows, count: rows.length, error: null };
}

/**
 * Disconnect (delete) several integrations in one request.
 * Gmail and Google Calendar share one Google token, so the Google card
 * removes both rows together rather than leaving half a connection behind.
 * @param {string[]} integrationIds - The integration UUIDs
 * @returns {Promise<{data: boolean | null, error: AppError | null}>}
 */
export async function disconnectIntegrations(integrationIds) {
	const { error } = await apiFetch('/integrations/disconnect', {
		method: 'POST',
		body: { integration_ids: integrationIds }
	});
	if (error) return { data: null, error: toAppError(error) };
	return { data: true, error: null };
}

/**
 * Fetch the latest Google Calendar reconnect recovery generation (or null).
 * Only google_calendar creates recoveries (email resumes from provider cursors
 * with no recovery record). The catch-up UI polls this while the latest
 * generation is in flight.
 * @returns {Promise<{data: IntegrationRecovery | null, error: AppError | null}>}
 */
export async function fetchCalendarRecovery() {
	const { data, error } = await apiFetch('/integrations/recovery', {
		query: { provider: 'google_calendar' }
	});
	if (error) return { data: null, error: toAppError(error) };
	return { data: data?.recovery ?? null, error: null };
}
