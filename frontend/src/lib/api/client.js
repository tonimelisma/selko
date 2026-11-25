/**
 * The one way the web app calls Selko's API (03-api-auth-web.md §D.1).
 *
 * `apiFetch` sends the in-memory access token as a Bearer header, JSON in and
 * out, with a 30 s timeout. A 401 triggers one refresh (shared by every
 * request that hit the 401 at the same time) and one retry of the request.
 * It never throws: it resolves to `{data, error, status}`, where `error` is
 * `{message, status, code, ...}` from `parseApiError`.
 */

import { getAccessToken, refresh } from '$lib/auth.js';
import { API_REQUEST_TIMEOUT_MS, getApiBaseUrl, parseApiError } from '$lib/api/http.js';

export { getAccessToken, getApiBaseUrl, parseApiError };

/**
 * @typedef {import('$lib/api/http.js').ApiError} ApiError
 */

/**
 * @typedef {Object} ApiFetchOptions
 * @property {string} [method='GET']
 * @property {unknown} [body] - JSON-serialised when present
 * @property {Record<string, string | number | boolean | null | undefined>} [query]
 * @property {AbortSignal} [signal]
 * @property {Record<string, string>} [headers]
 * @property {'json' | 'blob' | 'response'} [responseType='json']
 * @property {number} [timeoutMs]
 */

/**
 * @param {string} path
 * @param {ApiFetchOptions['query']} query
 */
function buildUrl(path, query) {
	let url = `${getApiBaseUrl()}${path}`;
	if (query) {
		const params = new URLSearchParams();
		for (const [key, value] of Object.entries(query)) {
			if (value !== undefined && value !== null) params.set(key, String(value));
		}
		const qs = params.toString();
		if (qs) url += `${url.includes('?') ? '&' : '?'}${qs}`;
	}
	return url;
}

/**
 * @param {string} url
 * @param {string} token
 * @param {ApiFetchOptions} options
 * @returns {Promise<Response>}
 */
async function send(url, token, options) {
	const { method = 'GET', body, signal, headers = {}, timeoutMs = API_REQUEST_TIMEOUT_MS } = options;
	const controller = new AbortController();
	let timedOut = false;
	const timer = setTimeout(() => {
		timedOut = true;
		controller.abort();
	}, timeoutMs);
	const onAbort = () => controller.abort();
	if (signal) {
		if (signal.aborted) controller.abort();
		else signal.addEventListener('abort', onAbort, { once: true });
	}
	/** @type {Record<string, string>} */
	const requestHeaders = { Accept: 'application/json', Authorization: `Bearer ${token}`, ...headers };
	if (body !== undefined) requestHeaders['Content-Type'] = 'application/json';
	try {
		return await fetch(url, {
			method,
			headers: requestHeaders,
			body: body !== undefined ? JSON.stringify(body) : undefined,
			signal: controller.signal
		});
	} catch (error) {
		if (timedOut) {
			const timeout = new Error('Request timed out. Please try again.');
			timeout.name = 'TimeoutError';
			throw timeout;
		}
		throw error;
	} finally {
		clearTimeout(timer);
		signal?.removeEventListener('abort', onAbort);
	}
}

/**
 * @param {Response} response
 * @param {ApiFetchOptions['responseType']} responseType
 */
async function readBody(response, responseType) {
	if (responseType === 'response') return response;
	if (response.status === 204) return null;
	if (responseType === 'blob') return response.blob();
	try {
		return await response.json();
	} catch {
		return null;
	}
}

/**
 * Call the API. Resolves to `{data, error, status}`; never rejects.
 * @param {string} path - e.g. `/events/review`
 * @param {ApiFetchOptions} [options]
 * @returns {Promise<{ data: any, error: ApiError | null, status: number }>}
 */
export async function apiFetch(path, options = {}) {
	const url = buildUrl(path, options.query);
	try {
		let token = getAccessToken();
		if (!token) token = await refresh();
		if (!token) {
			return {
				data: null,
				error: { message: 'Not authenticated', status: 401, code: 'UNAUTHORIZED' },
				status: 401
			};
		}
		let response = await send(url, token, options);
		if (response.status === 401) {
			const renewed = await refresh();
			if (renewed) response = await send(url, renewed, options);
		}
		if (!response.ok) {
			const error = await parseApiError(response);
			return { data: null, error, status: response.status };
		}
		return { data: await readBody(response, options.responseType), error: null, status: response.status ?? 200 };
	} catch (error) {
		const timedOut = error instanceof Error && error.name === 'TimeoutError';
		return {
			data: null,
			error: {
				message: error instanceof Error && error.message ? error.message : 'Request failed',
				status: 0,
				code: timedOut ? 'TIMEOUT' : 'NETWORK_ERROR'
			},
			status: 0
		};
	}
}
