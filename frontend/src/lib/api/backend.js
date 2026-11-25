/**
 * Backend API client for server-side operations (sync, LLM processing, OAuth,
 * calendar writes). Every call goes through `apiFetch` in `client.js`, which
 * owns the token, the timeout and the 401 refresh.
 */

import { apiFetch, getAccessToken, getApiBaseUrl, parseApiError } from '$lib/api/client.js';

/**
 * @typedef {import('$lib/api/http.js').ApiError} ApiError
 */

/**
 * Call the API and keep this module's `{data, error}` shape.
 * @param {string} endpoint
 * @param {import('$lib/api/client.js').ApiFetchOptions} [options]
 * @returns {Promise<{data: any, error: ApiError | null}>}
 */
async function request(endpoint, options = {}) {
	const { data, error } = await apiFetch(endpoint, options);
	return error ? { data: null, error } : { data, error: null };
}

// ============================================================================
// Email Operations
// ============================================================================

/**
 * @typedef {Object} EmailSyncResult
 * @property {number} fetched - Number of emails fetched from Gmail
 * @property {number} saved - Number of new emails saved
 * @property {number} [attachments_downloaded] - Number of attachments downloaded
 */

/**
 * Sync emails from Gmail
 * @param {Object} [options={}]
 * @param {number} [options.maxResults=50] - Maximum emails to fetch
 * @param {boolean} [options.fetchAttachments=true] - Whether to download attachments
 * @returns {Promise<{data: EmailSyncResult | null, error: ApiError | null}>}
 */
export async function syncEmails(options = {}) {
	const { maxResults = 50, fetchAttachments = true } = options;
	return request('/emails/sync', {
		method: 'POST',
		body: { max_results: maxResults, fetch_attachments: fetchAttachments }
	});
}

/**
 * @typedef {Object} EmailProcessResult
 * @property {number} num_events - Total events found
 * @property {number} num_new - New events created
 * @property {number} num_updated - Existing events updated
 * @property {string[]} event_ids - IDs of affected events
 */

/**
 * Process a single email to extract calendar events
 * @param {string} emailId - The email UUID to process
 * @returns {Promise<{data: EmailProcessResult | null, error: ApiError | null}>}
 */
export async function processEmail(emailId) {
	return request(`/emails/${emailId}/process`, { method: 'POST' });
}

/**
 * Process multiple recent emails to extract events
 * @param {Object} [options={}]
 * @param {number} [options.maxEmails=10] - Maximum emails to process
 * @returns {Promise<{data: EmailProcessResult | null, error: ApiError | null}>}
 */
export async function batchProcessEmails(options = {}) {
	const { maxEmails = 10 } = options;
	return request('/emails/batch-process', { method: 'POST', body: { max_emails: maxEmails } });
}

/**
 * Queue one historical email for safe reprocessing.
 * @param {string} emailId
 * @returns {Promise<{data: {email_id: string, processing_status: string} | null, error: ApiError | null}>}
 */
export async function reprocessEmail(emailId) {
	return request(`/emails/${emailId}/reprocess`, { method: 'POST' });
}

/**
 * Fetch discovered, user-configurable folders for an email provider.
 * @param {'gmail' | 'outlook'} provider
 * @returns {Promise<{data: any[], error: ApiError | null}>}
 */
export async function fetchEmailFolders(provider) {
	const { data, error } = await apiFetch(`/integrations/${provider}/folders`, { method: 'GET' });
	if (error) return { data: [], error };
	return { data: data ?? [], error: null };
}

/**
 * Save an include/exclude override for a discovered folder.
 * @param {'gmail' | 'outlook'} provider
 * @param {string} folderId
 * @param {boolean} isIncluded
 */
export async function updateEmailFolder(provider, folderId, isIncluded) {
	return request(`/integrations/${provider}/folders/${folderId}`, {
		method: 'PATCH',
		body: { is_included: isIncluded }
	});
}

// ============================================================================
// Calendar Operations
// ============================================================================

/**
 * @typedef {Object} Calendar
 * @property {string} id - Calendar ID
 * @property {string} name - Calendar name
 * @property {boolean} is_primary - Whether this is the primary calendar
 * @property {boolean} is_selected - Whether this is the currently selected target
 * @property {'google_calendar' | 'outlook'} [provider] - Provider that owns the calendar.
 *   Outlook ids are opaque `outlook:`-prefixed strings; store them unchanged.
 */

/**
 * List calendars from every calendar-capable connected provider
 * (Google Calendar and calendar-scoped Outlook).
 * @returns {Promise<{data: Calendar[] | null, error: ApiError | null}>}
 */
export async function listCalendars() {
	return request('/calendars', { method: 'GET' });
}

/**
 * @typedef {Object} CalendarSyncResult
 * @property {string} event_id - Selko event UUID
 * @property {string | null} google_calendar_event_id - Google Calendar event ID when synced
 * @property {string | null} synced_at - ISO timestamp when synced
 * @property {'approved' | 'syncing' | 'synced'} status - Worker-owned queue/sync state
 */

/**
 * Idempotently observe or retry worker-owned calendar sync.
 * @param {string} eventId - The event UUID to sync
 * @returns {Promise<{data: CalendarSyncResult | null, error: ApiError | null}>}
 */
export async function syncEventToCalendar(eventId) {
	return request(`/events/${eventId}/sync`, { method: 'POST' });
}

/**
 * Apply an event change proposal (Changes lane approve).
 * @param {string} eventId
 * @returns {Promise<{data: {event_id: string, status: string} | null, error: ApiError | null}>}
 */
export async function applyEventChange(eventId) {
	return request(`/events/${eventId}/apply-change`, { method: 'POST' });
}

/**
 * Reject an event change proposal (Changes lane reject).
 * @param {string} eventId
 * @returns {Promise<{data: {event_id: string, status: string} | null, error: ApiError | null}>}
 */
export async function rejectEventChange(eventId) {
	return request(`/events/${eventId}/reject-change`, { method: 'POST' });
}

/**
 * Undo a History action back to New or Changes review lane.
 * Reverts Google Calendar to the pre-Selko state when synced.
 * @param {string} eventId
 * @param {{ force?: boolean }} [options]
 * @returns {Promise<{data: {event_id: string, status: string} | null, error: ApiError | null}>}
 */
export async function undoHistoryEvent(eventId, options = {}) {
	const { force = false } = options;
	return request(`/events/${eventId}/undo`, { method: 'POST', body: { force } });
}

// ============================================================================
// OAuth Operations
// ============================================================================

/**
 * Get the Google OAuth authorization URL.
 * One consent covers both Gmail and Google Calendar; the callback stores the
 * shared token in both integrations rows.
 * @param {string} [redirectUri] - Optional custom redirect URI
 * @returns {string} The authorization URL
 */
export function getGoogleAuthUrl(redirectUri) {
	const params = new URLSearchParams();
	if (redirectUri) {
		params.set('redirect_uri', redirectUri);
	}
	const queryString = params.toString();
	return `${getApiBaseUrl()}/integrations/google/auth${queryString ? `?${queryString}` : ''}`;
}

/**
 * Fetch the provider's auth_url with the user's Bearer token, then navigate.
 * Browser navigation alone cannot send Authorization headers.
 * @param {string} path - API path (with query) of the auth endpoint
 * @returns {Promise<void>}
 */
async function startOAuthRedirect(path) {
	if (!getAccessToken()) {
		throw new Error('Not authenticated');
	}
	const { data, error } = await apiFetch(path, { headers: { Accept: 'application/json' } });
	if (error) {
		throw new Error(error.message || 'Failed to start OAuth');
	}
	if (!data?.auth_url) {
		throw new Error('OAuth response missing auth_url');
	}

	try {
		new URL(data.auth_url);
	} catch {
		console.error('Invalid OAuth redirect URL:', data.auth_url);
		throw new Error('Failed to generate OAuth URL');
	}

	window.location.href = data.auth_url;
}

/**
 * @param {string} provider
 * @param {string} [redirectUri]
 */
function authPath(provider, redirectUri) {
	const params = new URLSearchParams();
	if (redirectUri) params.set('redirect_uri', redirectUri);
	const queryString = params.toString();
	return `/integrations/${provider}/auth${queryString ? `?${queryString}` : ''}`;
}

/**
 * Initiate the combined Google (Gmail + Google Calendar) OAuth flow
 * @param {string} [redirectUri] - Optional custom redirect URI
 * @returns {Promise<void>}
 */
export async function initiateGoogleAuth(redirectUri) {
	await startOAuthRedirect(authPath('google', redirectUri));
}

/**
 * Get the Outlook OAuth authorization URL.
 * @param {string} [redirectUri] - Optional custom redirect URI
 * @returns {string} The authorization URL
 */
export function getOutlookAuthUrl(redirectUri) {
	return `${getApiBaseUrl()}${authPath('outlook', redirectUri)}`;
}

/**
 * Initiate Outlook OAuth flow.
 * @param {string} [redirectUri] - Optional custom redirect URI
 * @returns {Promise<void>}
 */
export async function initiateOutlookAuth(redirectUri) {
	await startOAuthRedirect(authPath('outlook', redirectUri));
}

// ============================================================================
// Health Check
// ============================================================================

/**
 * @typedef {Object} HealthStatus
 * @property {string} status - "healthy" or "unhealthy"
 */

/**
 * Check if the backend API is healthy (no authentication).
 * @returns {Promise<{data: HealthStatus | null, error: ApiError | null}>}
 */
export async function checkHealth() {
	try {
		const response = await fetch(`${getApiBaseUrl()}/health`);
		if (!response.ok) {
			return { data: null, error: await parseApiError(response) };
		}
		return { data: await response.json(), error: null };
	} catch (error) {
		return {
			data: null,
			error: {
				message: error instanceof Error ? error.message : 'Health check failed',
				status: 0
			}
		};
	}
}
