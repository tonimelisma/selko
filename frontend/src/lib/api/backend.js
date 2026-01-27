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
	const response = await fetch(url, {
		...options,
		headers: {
			'Content-Type': 'application/json',
			Authorization: `Bearer ${token}`,
			...options.headers
		}
	});

	return response;
}

/**
 * @typedef {Object} ApiError
 * @property {string} message
 * @property {number} status
 * @property {string} [detail]
 */

/**
 * Parse API error response
 * @param {Response} response
 * @returns {Promise<ApiError>}
 */
async function parseApiError(response) {
	try {
		const data = await response.json();
		return {
			message: data.detail || data.message || 'API request failed',
			status: response.status,
			detail: data.detail
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
 * Initiate Gmail OAuth flow
 * Opens OAuth consent screen in current window
 * @param {string} [redirectUri] - Optional custom redirect URI
 */
export function initiateGmailAuth(redirectUri) {
	window.location.href = getGmailAuthUrl(redirectUri);
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
