/**
 * Shared HTTP helpers for talking to Selko's API: the base URL and the one
 * error parser every caller uses. Kept free of imports so both the API client
 * and the auth module can depend on it without a cycle.
 */

/** Default timeout for API requests (ms). */
export const API_REQUEST_TIMEOUT_MS = 30_000;

/**
 * The API's base URL. Empty means same origin: the web app is served by the
 * same process as the API. `VITE_API_URL` points a dev server elsewhere.
 * @returns {string}
 */
export function getApiBaseUrl() {
	const configured = import.meta.env.VITE_API_URL ?? '';
	return String(configured).replace(/\/+$/, '');
}

/**
 * @typedef {Object} ApiError
 * @property {string} message
 * @property {number} status
 * @property {string} [detail]
 * @property {string} [code]
 * @property {{ changed_fields?: string[], differences?: Array<{ field: string, selko: unknown, google: unknown }>, google_event_url?: string | null }} [conflict]
 */

/**
 * Extract a human-readable message from FastAPI-style error payloads:
 * plain strings, `{error, detail}` / `{code, message}` objects, and
 * validation-error arrays (`[{msg}]`).
 * @param {unknown} detail
 * @returns {string | null}
 */
function extractErrorMessage(detail) {
	if (typeof detail === 'string' && detail.trim()) {
		return detail;
	}
	if (Array.isArray(detail)) {
		const first = detail.find((entry) => entry && typeof entry.msg === 'string');
		return first ? first.msg : null;
	}
	if (detail && typeof detail === 'object') {
		const nested = /** @type {{ detail?: unknown, message?: unknown, error?: unknown }} */ (detail);
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
 * Extract a machine-readable error code from FastAPI-style payloads.
 * @param {any} data
 * @returns {string | null}
 */
function extractErrorCode(data) {
	if (!data || typeof data !== 'object') return null;
	if (typeof data.error === 'string' && data.error.trim()) return data.error;
	const detail = data.detail;
	if (detail && typeof detail === 'object' && !Array.isArray(detail)) {
		if (typeof detail.error === 'string') return detail.error;
		if (typeof detail.code === 'string') return detail.code;
	}
	return null;
}

/**
 * Parse an error response into `{message, status, detail, code, conflict}`.
 * @param {Response} response
 * @returns {Promise<ApiError>}
 */
export async function parseApiError(response) {
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
			code: extractErrorCode(data) || undefined,
			conflict:
				data.detail && typeof data.detail === 'object' && data.detail.conflict
					? data.detail.conflict
					: undefined
		};
	} catch {
		return {
			message: `API request failed with status ${response.status}`,
			status: response.status
		};
	}
}
