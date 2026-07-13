/**
 * Backend API client for server-side operations
 *
 * These operations require server-side secrets (OAuth credentials, API keys)
 * and cannot be performed directly from the frontend.
 */

import { supabase } from '$lib/supabase.js';

/**
 * Get the API base URL from environment
 * @returns {string}
 */
function getApiBaseUrl() {
	// @ts-ignore - Vite env variable
	return import.meta.env.VITE_API_URL || 'http://localhost:8000';
}

/**
 * Get the current access token for API authentication
 * @returns {Promise<string | null>}
 */
async function getAccessToken() {
	const {
		data: { session }
	} = await supabase.auth.getSession();
	return session?.access_token ?? null;
}

/** Default timeout for backend API requests (ms). */
const API_REQUEST_TIMEOUT_MS = 30_000;

/**
 * Make an authenticated request to the backend API
 * @param {string} endpoint - API endpoint (without base URL)
 * @param {RequestInit} [options={}] - Fetch options
 * @returns {Promise<Response>}
 */
async function apiRequest(endpoint, options = {}) {
	const token = await getAccessToken();
	if (!token) {
		throw new Error('Not authenticated');
	}

	const url = `${getApiBaseUrl()}${endpoint}`;
	const timeoutSignal = AbortSignal.timeout(API_REQUEST_TIMEOUT_MS);

	try {
		return await fetch(url, {
			...options,
			signal: timeoutSignal,
			headers: {
				'Content-Type': 'application/json',
				Authorization: `Bearer ${token}`,
				...options.headers
			}
		});
	} catch (error) {
		if (error instanceof DOMException && error.name === 'TimeoutError') {
			throw new Error('Request timed out. Please try again.');
		}
		if (error instanceof Error && error.name === 'AbortError') {
			throw new Error('Request timed out. Please try again.');
		}
		throw error;
	}
}

/**
 * @typedef {Object} ApiError
 * @property {string} message
 * @property {number} status
 * @property {string} [detail]
 * @property {string} [code]
 */

/**
 * Extract a human-readable message from FastAPI-style error payloads.
 * Supports plain strings and nested `{ error, detail }` objects.
 * @param {unknown} detail
 * @returns {string | null}
 */
function extractErrorMessage(detail) {
	if (typeof detail === 'string' && detail.trim()) {
		return detail;
	}
	if (detail && typeof detail === 'object') {
		const nested = /** @type {{ detail?: unknown, message?: unknown, error?: unknown }} */ (
			detail
		);
		if (typeof nested.detail === 'string' && nested.detail.trim()) {
			return nested.detail;
		}
		if (typeof nested.message === 'string' && nested.message.trim()) {
			return nested.message;
		}
		if (typeof nested.error === 'string' && nested.error.trim()) {
			return nested.error;
		}
	}
	return null;
}

/**
 * Extract machine-readable error code from FastAPI-style payloads.
 * @param {any} data
 * @returns {string | null}
 */
function extractErrorCode(data) {
	if (!data || typeof data !== 'object') return null;
	if (typeof data.error === 'string' && data.error.trim()) return data.error;
	if (data.detail && typeof data.detail === 'object' && typeof data.detail.error === 'string') {
		return data.detail.error;
	}
	return null;
}

/**
 * Parse API error response
 * @param {Response} response
 * @returns {Promise<ApiError>}
 */
async function parseApiError(response) {
	try {
		const data = await response.json();
		const message =
			extractErrorMessage(data.detail) ||
			extractErrorMessage(data.message) ||
			extractErrorMessage(data) ||
			'API request failed';
		return {
			message,
			status: response.status,
			detail: typeof data.detail === 'string' ? data.detail : message,
			code: extractErrorCode(data) || undefined
		};
	} catch {
		return {
			message: `API request failed with status ${response.status}`,
			status: response.status
		};
	}
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
 * Requires server-side Gmail API credentials
 * @param {Object} [options={}]
 * @param {number} [options.maxResults=50] - Maximum emails to fetch
 * @param {boolean} [options.fetchAttachments=true] - Whether to download attachments
 * @returns {Promise<{data: EmailSyncResult | null, error: ApiError | null}>}
 */
export async function syncEmails(options = {}) {
	const { maxResults = 50, fetchAttachments = true } = options;

	try {
		const response = await apiRequest('/emails/sync', {
			method: 'POST',
			body: JSON.stringify({
				max_results: maxResults,
				fetch_attachments: fetchAttachments
			})
		});

		if (!response.ok) {
			const error = await parseApiError(response);
			return { data: null, error };
		}

		const data = await response.json();
		return { data, error: null };
	} catch (error) {
		return {
			data: null,
			error: {
				message: error instanceof Error ? error.message : 'Sync failed',
				status: 0
			}
		};
	}
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
 * Requires server-side LLM API key (Gemini)
 * @param {string} emailId - The email UUID to process
 * @returns {Promise<{data: EmailProcessResult | null, error: ApiError | null}>}
 */
export async function processEmail(emailId) {
	try {
		const response = await apiRequest(`/emails/${emailId}/process`, {
			method: 'POST'
		});

		if (!response.ok) {
			const error = await parseApiError(response);
			return { data: null, error };
		}

		const data = await response.json();
		return { data, error: null };
	} catch (error) {
		return {
			data: null,
			error: {
				message: error instanceof Error ? error.message : 'Processing failed',
				status: 0
			}
		};
	}
}

/**
 * Process multiple recent emails to extract events
 * Requires server-side LLM API key (Gemini)
 * @param {Object} [options={}]
 * @param {number} [options.maxEmails=10] - Maximum emails to process
 * @returns {Promise<{data: EmailProcessResult | null, error: ApiError | null}>}
 */
export async function batchProcessEmails(options = {}) {
	const { maxEmails = 10 } = options;

	try {
		const response = await apiRequest('/emails/batch-process', {
			method: 'POST',
			body: JSON.stringify({ max_emails: maxEmails })
		});

		if (!response.ok) {
			const error = await parseApiError(response);
			return { data: null, error };
		}

		const data = await response.json();
		return { data, error: null };
	} catch (error) {
		return {
			data: null,
			error: {
				message: error instanceof Error ? error.message : 'Batch processing failed',
				status: 0
			}
		};
	}
}

/**
 * Queue one historical email for safe reprocessing.
 * @param {string} emailId
 * @returns {Promise<{data: {email_id: string, processing_status: string} | null, error: ApiError | null}>}
 */
export async function reprocessEmail(emailId) {
	try {
		const response = await apiRequest(`/emails/${emailId}/reprocess`, { method: 'POST' });
		if (!response.ok) {
			return { data: null, error: await parseApiError(response) };
		}
		return { data: await response.json(), error: null };
	} catch (error) {
		return {
			data: null,
			error: { message: error instanceof Error ? error.message : 'Reprocess failed', status: 0 }
		};
	}
}

/**
 * Fetch discovered, user-configurable folders for an email provider.
 * @param {'gmail' | 'outlook'} provider
 */
export async function fetchEmailFolders(provider) {
	try {
		const response = await apiRequest(`/integrations/${provider}/folders`, { method: 'GET' });
		if (!response.ok) return { data: [], error: await parseApiError(response) };
		return { data: await response.json(), error: null };
	} catch (error) {
		return {
			data: [],
			error: { message: error instanceof Error ? error.message : 'Failed to load folders', status: 0 }
		};
	}
}

/**
 * Save an include/exclude override for a discovered folder.
 * @param {'gmail' | 'outlook'} provider
 * @param {string} folderId
 * @param {boolean} isIncluded
 */
export async function updateEmailFolder(provider, folderId, isIncluded) {
	try {
		const response = await apiRequest(`/integrations/${provider}/folders/${folderId}`, {
			method: 'PATCH',
			body: JSON.stringify({ is_included: isIncluded })
		});
		if (!response.ok) return { data: null, error: await parseApiError(response) };
		return { data: await response.json(), error: null };
	} catch (error) {
		return {
			data: null,
			error: { message: error instanceof Error ? error.message : 'Failed to update folder', status: 0 }
		};
	}
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
 */

/**
 * List user's Google Calendars
 * Requires server-side Google Calendar API credentials
 * @returns {Promise<{data: Calendar[] | null, error: ApiError | null}>}
 */
export async function listCalendars() {
	try {
		const response = await apiRequest('/calendars', {
			method: 'GET'
		});

		if (!response.ok) {
			const error = await parseApiError(response);
			return { data: null, error };
		}

		const data = await response.json();
		return { data, error: null };
	} catch (error) {
		return {
			data: null,
			error: {
				message: error instanceof Error ? error.message : 'Failed to list calendars',
				status: 0
			}
		};
	}
}

/**
 * @typedef {Object} CalendarSyncResult
 * @property {string} event_id - Selko event UUID
 * @property {string} google_calendar_event_id - Google Calendar event ID
 * @property {string} synced_at - ISO timestamp
 * @property {string} status - "synced"
 */

/**
 * Sync an approved event to Google Calendar
 * Requires server-side Google Calendar API credentials
 * @param {string} eventId - The event UUID to sync
 * @returns {Promise<{data: CalendarSyncResult | null, error: ApiError | null}>}
 */
export async function syncEventToCalendar(eventId) {
	try {
		const response = await apiRequest(`/events/${eventId}/sync`, {
			method: 'POST'
		});

		if (!response.ok) {
			const error = await parseApiError(response);
			return { data: null, error };
		}

		const data = await response.json();
		return { data, error: null };
	} catch (error) {
		return {
			data: null,
			error: {
				message: error instanceof Error ? error.message : 'Calendar sync failed',
				status: 0
			}
		};
	}
}

/**
 * Apply a pending_change proposal (Changes lane approve).
 * @param {string} eventId
 * @returns {Promise<{data: {event_id: string, status: string} | null, error: ApiError | null}>}
 */
export async function applyEventChange(eventId) {
	try {
		const response = await apiRequest(`/events/${eventId}/apply-change`, {
			method: 'POST'
		});
		if (!response.ok) {
			return { data: null, error: await parseApiError(response) };
		}
		return { data: await response.json(), error: null };
	} catch (error) {
		return {
			data: null,
			error: {
				message: error instanceof Error ? error.message : 'Apply change failed',
				status: 0
			}
		};
	}
}

/**
 * Reject a pending_change proposal (Changes lane reject).
 * @param {string} eventId
 * @returns {Promise<{data: {event_id: string, status: string} | null, error: ApiError | null}>}
 */
export async function rejectEventChange(eventId) {
	try {
		const response = await apiRequest(`/events/${eventId}/reject-change`, {
			method: 'POST'
		});
		if (!response.ok) {
			return { data: null, error: await parseApiError(response) };
		}
		return { data: await response.json(), error: null };
	} catch (error) {
		return {
			data: null,
			error: {
				message: error instanceof Error ? error.message : 'Reject change failed',
				status: 0
			}
		};
	}
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
	try {
		const response = await apiRequest(`/events/${eventId}/undo`, {
			method: 'POST',
			body: JSON.stringify({ force })
		});
		if (!response.ok) {
			return { data: null, error: await parseApiError(response) };
		}
		return { data: await response.json(), error: null };
	} catch (error) {
		return {
			data: null,
			error: {
				message: error instanceof Error ? error.message : 'Undo failed',
				status: 0
			}
		};
	}
}

// ============================================================================
// OAuth Operations
// ============================================================================

/**
 * Get the Gmail OAuth authorization URL
 * Opens in a new window/tab for the user to authorize
 * @param {string} [redirectUri] - Optional custom redirect URI
 * @returns {string} The authorization URL
 */
export function getGmailAuthUrl(redirectUri) {
	const baseUrl = getApiBaseUrl();
	const params = new URLSearchParams();
	if (redirectUri) {
		params.set('redirect_uri', redirectUri);
	}
	const queryString = params.toString();
	return `${baseUrl}/integrations/gmail/auth${queryString ? `?${queryString}` : ''}`;
}

/**
 * Fetch Google auth_url from the API with the user's Bearer token, then navigate.
 * Browser navigation alone cannot send Authorization headers.
 * @param {string} endpointUrl
 * @returns {Promise<void>}
 */
async function startOAuthRedirect(endpointUrl) {
	const token = await getAccessToken();
	if (!token) {
		throw new Error('Not authenticated');
	}

	const response = await fetch(endpointUrl, {
		headers: {
			Authorization: `Bearer ${token}`,
			Accept: 'application/json'
		}
	});

	if (!response.ok) {
		const err = await parseApiError(response);
		throw new Error(err.message || 'Failed to start OAuth');
	}

	const data = await response.json();
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
 * Initiate Gmail OAuth flow
 * Fetches Google consent URL with auth, then opens it in the current window
 * @param {string} [redirectUri] - Optional custom redirect URI
 * @returns {Promise<void>}
 */
export async function initiateGmailAuth(redirectUri) {
	await startOAuthRedirect(getGmailAuthUrl(redirectUri));
}

/**
 * Get the Outlook OAuth authorization URL.
 * @param {string} [redirectUri] - Optional custom redirect URI
 * @returns {string} The authorization URL
 */
export function getOutlookAuthUrl(redirectUri) {
	const baseUrl = getApiBaseUrl();
	const params = new URLSearchParams();
	if (redirectUri) {
		params.set('redirect_uri', redirectUri);
	}
	const queryString = params.toString();
	return `${baseUrl}/integrations/outlook/auth${queryString ? `?${queryString}` : ''}`;
}

/**
 * Initiate Outlook OAuth flow.
 * @param {string} [redirectUri] - Optional custom redirect URI
 * @returns {Promise<void>}
 */
export async function initiateOutlookAuth(redirectUri) {
	await startOAuthRedirect(getOutlookAuthUrl(redirectUri));
}

// ============================================================================
// Calendar OAuth Operations
// ============================================================================

/**
 * Get the Google Calendar OAuth authorization URL
 * Opens in a new window/tab for the user to authorize
 * @param {string} [redirectUri] - Optional custom redirect URI
 * @returns {string} The authorization URL
 */
export function getCalendarAuthUrl(redirectUri) {
	const baseUrl = getApiBaseUrl();
	const params = new URLSearchParams();
	if (redirectUri) {
		params.set('redirect_uri', redirectUri);
	}
	const queryString = params.toString();
	return `${baseUrl}/integrations/calendar/auth${queryString ? `?${queryString}` : ''}`;
}

/**
 * Initiate Google Calendar OAuth flow
 * Fetches Google consent URL with auth, then opens it in the current window
 * @param {string} [redirectUri] - Optional custom redirect URI
 * @returns {Promise<void>}
 */
export async function initiateCalendarAuth(redirectUri) {
	await startOAuthRedirect(getCalendarAuthUrl(redirectUri));
}

// ============================================================================
// Google Photos OAuth Operations
// ============================================================================

/**
 * Get the Google Photos OAuth authorization URL
 * @param {string} [redirectUri] - Optional custom redirect URI
 * @returns {string} The authorization URL
 */
export function getPhotosAuthUrl(redirectUri) {
	const baseUrl = getApiBaseUrl();
	const params = new URLSearchParams();
	if (redirectUri) {
		params.set('redirect_uri', redirectUri);
	}
	const queryString = params.toString();
	return `${baseUrl}/integrations/photos/auth${queryString ? `?${queryString}` : ''}`;
}

/**
 * Initiate Google Photos OAuth flow
 * Fetches Google consent URL with auth, then opens it in the current window
 * @param {string} [redirectUri] - Optional custom redirect URI
 * @returns {Promise<void>}
 */
export async function initiatePhotosAuth(redirectUri) {
	await startOAuthRedirect(getPhotosAuthUrl(redirectUri));
}

// ============================================================================
// Health Check
// ============================================================================

/**
 * @typedef {Object} HealthStatus
 * @property {string} status - "healthy" or "unhealthy"
 */

/**
 * Check if the backend API is healthy
 * @returns {Promise<{data: HealthStatus | null, error: ApiError | null}>}
 */
export async function checkHealth() {
	try {
		const url = `${getApiBaseUrl()}/health`;
		const response = await fetch(url);

		if (!response.ok) {
			const error = await parseApiError(response);
			return { data: null, error };
		}

		const data = await response.json();
		return { data, error: null };
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
