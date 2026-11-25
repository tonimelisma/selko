// @ts-nocheck
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const mockAuth = { token: 'old-token', getAccessToken: vi.fn(), refresh: vi.fn() };
vi.mock('$lib/auth.js', () => ({
	getAccessToken: (...args) => mockAuth.getAccessToken(...args),
	refresh: (...args) => mockAuth.refresh(...args)
}));

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

const { apiFetch } = await import('../api/client.js');

/** @param {number} status @param {any} body */
function respond(status, body = {}) {
	return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body), blob: () => Promise.resolve(new Blob(['x'])) };
}

const authHeader = (call) => call[1].headers.Authorization;

describe('apiFetch', () => {
	beforeEach(() => {
		mockFetch.mockReset();
		mockAuth.getAccessToken.mockReset().mockImplementation(() => mockAuth.token);
		mockAuth.refresh.mockReset();
		mockAuth.token = 'old-token';
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	it('sends the Bearer token, JSON body and query to the API', async () => {
		mockFetch.mockResolvedValue(respond(200, { ok: 1 }));

		const result = await apiFetch('/events/activity', { method: 'POST', body: { a: 1 }, query: { limit: 5, offset: 0, skip: undefined } });

		expect(mockFetch).toHaveBeenCalledWith(
			'http://localhost:8000/events/activity?limit=5&offset=0',
			expect.objectContaining({
				method: 'POST',
				body: JSON.stringify({ a: 1 }),
				headers: expect.objectContaining({ Authorization: 'Bearer old-token', 'Content-Type': 'application/json' })
			})
		);
		expect(result).toEqual({ data: { ok: 1 }, error: null, status: 200 });
	});

	it('answers 401 with one refresh and one retry carrying the new token', async () => {
		mockAuth.refresh.mockImplementation(async () => {
			mockAuth.token = 'new-token';
			return 'new-token';
		});
		mockFetch.mockResolvedValueOnce(respond(401, { detail: 'Invalid or expired token' }));
		mockFetch.mockResolvedValueOnce(respond(200, [1, 2]));

		const result = await apiFetch('/integrations');

		expect(mockAuth.refresh).toHaveBeenCalledTimes(1);
		expect(mockFetch).toHaveBeenCalledTimes(2);
		expect(authHeader(mockFetch.mock.calls[0])).toBe('Bearer old-token');
		expect(authHeader(mockFetch.mock.calls[1])).toBe('Bearer new-token');
		expect(result.data).toEqual([1, 2]);
		expect(result.error).toBeNull();
	});

	it('retries only once: a second 401 is returned as the error', async () => {
		mockAuth.refresh.mockResolvedValue('new-token');
		mockFetch.mockResolvedValue(respond(401, { detail: 'Invalid or expired token' }));

		const result = await apiFetch('/integrations');

		expect(mockFetch).toHaveBeenCalledTimes(2);
		expect(mockAuth.refresh).toHaveBeenCalledTimes(1);
		expect(result.error).toMatchObject({ status: 401, message: 'Invalid or expired token' });
	});

	it('does not retry when the refresh fails', async () => {
		mockAuth.refresh.mockResolvedValue(null);
		mockFetch.mockResolvedValue(respond(401, { detail: 'Invalid or expired token' }));

		const result = await apiFetch('/integrations');

		expect(mockFetch).toHaveBeenCalledTimes(1);
		expect(result.error.status).toBe(401);
	});

	it('concurrent 401s share the refresh the auth module single-flights', async () => {
		// The real auth.refresh() returns one shared promise to concurrent callers.
		let resolveRefresh;
		const shared = new Promise((resolve) => {
			resolveRefresh = resolve;
		});
		mockAuth.refresh.mockImplementation(() => shared);
		mockFetch.mockImplementation(async (_url, init) =>
			init.headers.Authorization === 'Bearer new-token' ? respond(200, 'ok') : respond(401)
		);

		const pending = Promise.all([apiFetch('/a'), apiFetch('/b'), apiFetch('/c')]);
		await vi.waitFor(() => expect(mockAuth.refresh).toHaveBeenCalledTimes(3));
		mockAuth.token = 'new-token';
		resolveRefresh('new-token');
		const results = await pending;

		expect(results.map((r) => r.data)).toEqual(['ok', 'ok', 'ok']);
		expect(mockFetch).toHaveBeenCalledTimes(6);
	});

	it('times out a request that never answers', async () => {
		vi.useFakeTimers();
		mockFetch.mockImplementation(
			(_url, init) =>
				new Promise((_resolve, reject) => {
					init.signal.addEventListener('abort', () => {
						const error = new Error('aborted');
						error.name = 'AbortError';
						reject(error);
					});
				})
		);

		const pending = apiFetch('/slow', { timeoutMs: 1000 });
		await vi.advanceTimersByTimeAsync(1001);
		const result = await pending;

		expect(result.error).toMatchObject({ status: 0, code: 'TIMEOUT', message: 'Request timed out. Please try again.' });
	});

	it('reports a network failure without throwing', async () => {
		mockFetch.mockRejectedValue(new TypeError('Failed to fetch'));

		const result = await apiFetch('/integrations');

		expect(result.data).toBeNull();
		expect(result.error).toMatchObject({ status: 0, code: 'NETWORK_ERROR' });
	});

	it('refreshes first when there is no token yet, and refuses without one', async () => {
		mockAuth.token = null;
		mockAuth.refresh.mockResolvedValue(null);

		const result = await apiFetch('/integrations');

		expect(mockAuth.refresh).toHaveBeenCalledTimes(1);
		expect(mockFetch).not.toHaveBeenCalled();
		expect(result.error).toMatchObject({ status: 401, message: 'Not authenticated' });
	});

	it('parses the API error shapes', async () => {
		mockFetch.mockResolvedValueOnce(respond(404, { detail: 'Event not found' }));
		mockFetch.mockResolvedValueOnce(respond(400, { detail: { code: 'INVALID_CREDENTIALS', message: 'Invalid login credentials' } }));
		mockFetch.mockResolvedValueOnce(respond(422, { detail: [{ loc: ['body', 'title'], msg: 'title must not be blank' }] }));

		const a = await apiFetch('/x');
		const b = await apiFetch('/x');
		const c = await apiFetch('/x');

		expect(a.error).toMatchObject({ status: 404, message: 'Event not found' });
		expect(b.error).toMatchObject({ status: 400, code: 'INVALID_CREDENTIALS', message: 'Invalid login credentials' });
		expect(c.error).toMatchObject({ status: 422, message: 'title must not be blank' });
	});

	it('returns null data for 204 and a Blob for responseType blob', async () => {
		mockFetch.mockResolvedValueOnce(respond(204));
		mockFetch.mockResolvedValueOnce(respond(200));

		const empty = await apiFetch('/sender-rules/r1', { method: 'DELETE' });
		const file = await apiFetch('/attachments/a1/content', { responseType: 'blob' });

		expect(empty).toEqual({ data: null, error: null, status: 204 });
		expect(file.data).toBeInstanceOf(Blob);
	});
});
