// @ts-nocheck
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const mockAuth = { token: 'token-1', refresh: vi.fn() };
vi.mock('$lib/auth.js', () => ({
	getAccessToken: () => mockAuth.token,
	refresh: (...args) => mockAuth.refresh(...args)
}));

const encoder = new TextEncoder();

/** A controllable SSE response body. */
function sseResponse(status = 200) {
	const queue = [];
	let waiting = null;
	let closed = false;
	const reader = {
		read() {
			if (queue.length) return Promise.resolve({ value: queue.shift(), done: false });
			if (closed) return Promise.resolve({ value: undefined, done: true });
			return new Promise((resolve, reject) => {
				waiting = { resolve, reject };
			});
		},
		cancel() {
			closed = true;
			waiting?.resolve({ value: undefined, done: true });
			waiting = null;
			return Promise.resolve();
		}
	};
	const stream = {
		response: { ok: status >= 200 && status < 300, status, body: { getReader: () => reader } },
		push(text) {
			const value = encoder.encode(text);
			if (waiting) {
				const w = waiting;
				waiting = null;
				w.resolve({ value, done: false });
			} else queue.push(value);
		},
		end() {
			closed = true;
			waiting?.resolve({ value: undefined, done: true });
			waiting = null;
		},
		fail(error) {
			waiting?.reject(error);
			waiting = null;
		}
	};
	return stream;
}

/** @type {ReturnType<typeof sseResponse>[]} */
let streams = [];
const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

const live = await import('../live-updates.js');

const READY = 'event: ready\ndata: {"user_id":"u1","heartbeat_seconds":25}\n\n';
const invalidate = (resource, operation = 'UPDATE') =>
	`event: invalidate\ndata: {"resource":"${resource}","operation":"${operation}","occurred_at":"2026-11-25T18:04:05+00:00"}\n\n`;

/** Let pending promises and zero-delay timers run. */
const flush = () => vi.advanceTimersByTimeAsync(0);

describe('live-updates SSE client', () => {
	beforeEach(() => {
		vi.useFakeTimers();
		vi.spyOn(Math, 'random').mockReturnValue(0); // no jitter
		live.__resetForTests();
		streams = [];
		mockAuth.token = 'token-1';
		mockAuth.refresh.mockReset().mockResolvedValue(null);
		mockFetch.mockReset().mockImplementation(async (_url, init) => {
			const stream = sseResponse();
			init.signal.addEventListener('abort', () => {
				const error = new Error('aborted');
				error.name = 'AbortError';
				stream.fail(error);
			});
			streams.push(stream);
			return stream.response;
		});
	});

	afterEach(() => {
		live.__resetForTests();
		vi.useRealTimers();
		vi.restoreAllMocks();
	});

	it('opens GET /live with the Bearer token (no token in the URL)', async () => {
		await live.start('u1');
		await flush();

		expect(mockFetch).toHaveBeenCalledTimes(1);
		const [url, init] = mockFetch.mock.calls[0];
		expect(url).toBe('http://localhost:8000/live');
		expect(init.headers.Authorization).toBe('Bearer token-1');
		expect(live.getStatus()).toBe('connecting');
	});

	it('catches up every subscribed resource on ready', async () => {
		const events = vi.fn();
		const emails = vi.fn();
		live.subscribe('events', events);
		live.subscribe('emails', emails);

		await live.start('u1');
		await flush();
		streams[0].push(READY);
		await flush();
		expect(live.getStatus()).toBe('connected');
		await vi.advanceTimersByTimeAsync(350);

		expect(events).toHaveBeenCalledWith(expect.objectContaining({ resource: 'events', operation: 'CATCHUP' }));
		expect(emails).toHaveBeenCalledWith(expect.objectContaining({ resource: 'emails', operation: 'CATCHUP' }));
	});

	it('hands an invalidate frame to its resource’s handler, debounced', async () => {
		const events = vi.fn();
		live.subscribe('events', events);
		await live.start('u1');
		await flush();

		// Two frames in one chunk, and one split across chunks.
		streams[0].push(invalidate('events') + invalidate('events', 'INSERT'));
		streams[0].push('event: invali');
		streams[0].push('date\ndata: {"resource":"events","operation":"DELETE"}\n\n');
		await vi.advanceTimersByTimeAsync(349);
		expect(events).not.toHaveBeenCalled();
		await vi.advanceTimersByTimeAsync(1);

		expect(events).toHaveBeenCalledTimes(1);
		expect(events).toHaveBeenCalledWith(expect.objectContaining({ resource: 'events', operation: 'DELETE' }));
	});

	it('ignores resources outside the allowlist and heartbeat comments', async () => {
		const session = vi.fn();
		live.subscribe('session', session);
		await live.start('u1');
		await flush();

		streams[0].push(': ping\n\n' + invalidate('session'));
		await vi.advanceTimersByTimeAsync(1000);

		expect(session).not.toHaveBeenCalled();
	});

	it('reconnects with a doubling backoff when the stream ends', async () => {
		await live.start('u1');
		await flush();

		streams[0].end();
		await flush();
		expect(live.getStatus()).toBe('reconnecting');
		await vi.advanceTimersByTimeAsync(999);
		expect(mockFetch).toHaveBeenCalledTimes(1);
		await vi.advanceTimersByTimeAsync(1);
		expect(mockFetch).toHaveBeenCalledTimes(2);

		// The counter is module-scoped, so the second failure waits longer.
		streams[1].end();
		await flush();
		await vi.advanceTimersByTimeAsync(1999);
		expect(mockFetch).toHaveBeenCalledTimes(2);
		await vi.advanceTimersByTimeAsync(1);
		expect(mockFetch).toHaveBeenCalledTimes(3);
		expect(live.getRejoinAttempts()).toBe(2);
	});

	it('reconnects after a network error and resets the backoff on ready', async () => {
		mockFetch.mockRejectedValueOnce(new TypeError('Failed to fetch'));
		await live.start('u1');
		await flush();
		expect(live.getRejoinAttempts()).toBe(1);

		await vi.advanceTimersByTimeAsync(1000);
		expect(mockFetch).toHaveBeenCalledTimes(2);
		streams[0].push(READY);
		await flush();

		expect(live.getRejoinAttempts()).toBe(0);
	});

	it('caps the backoff at 60 s', async () => {
		const times = [];
		mockFetch.mockImplementation(async () => {
			times.push(Date.now());
			throw new TypeError('Failed to fetch');
		});
		await live.start('u1');
		await flush();
		await vi.advanceTimersByTimeAsync(10 * 60_000);

		const gaps = times.slice(1).map((t, i) => t - times[i]);
		expect(gaps.slice(0, 7)).toEqual([1000, 2000, 4000, 8000, 16000, 32000, 60000]);
		expect(Math.max(...gaps)).toBe(60000);
	});

	it('does not reconnect after a deliberate stop', async () => {
		await live.start('u1');
		await flush();

		await live.stop();
		await vi.advanceTimersByTimeAsync(120_000);

		expect(mockFetch).toHaveBeenCalledTimes(1);
		expect(live.getStatus()).toBe('disconnected');
	});

	it('stops for good when the session is revoked', async () => {
		await live.start('u1');
		await flush();

		streams[0].push('event: revoked\n\n');
		await flush();
		await vi.advanceTimersByTimeAsync(120_000);

		expect(mockFetch).toHaveBeenCalledTimes(1);
		expect(live.getStatus()).toBe('disconnected');
	});

	it('reconnects when the server asks for re-auth', async () => {
		await live.start('u1');
		await flush();

		streams[0].push('event: reauth\n\n');
		await flush();
		await vi.advanceTimersByTimeAsync(1000);

		expect(mockFetch).toHaveBeenCalledTimes(2);
	});

	it('reconnects after 60 s of silence', async () => {
		await live.start('u1');
		await flush();

		await vi.advanceTimersByTimeAsync(59_999);
		expect(live.getStatus()).toBe('connecting');
		await vi.advanceTimersByTimeAsync(1);
		expect(live.getStatus()).toBe('reconnecting');
		await vi.advanceTimersByTimeAsync(1000);

		expect(mockFetch).toHaveBeenCalledTimes(2);
	});

	it('on 401 refreshes the token, then reconnects with the new one', async () => {
		mockFetch.mockResolvedValueOnce({ ok: false, status: 401, body: null });
		mockAuth.refresh.mockImplementation(async () => {
			mockAuth.token = 'token-2';
			return 'token-2';
		});

		await live.start('u1');
		await flush();
		await vi.advanceTimersByTimeAsync(1000);

		expect(mockAuth.refresh).toHaveBeenCalledTimes(1);
		expect(mockFetch).toHaveBeenCalledTimes(2);
		expect(mockFetch.mock.calls[1][1].headers.Authorization).toBe('Bearer token-2');
	});

	it('on 401 with a failed refresh stops', async () => {
		mockFetch.mockResolvedValueOnce({ ok: false, status: 401, body: null });

		await live.start('u1');
		await flush();
		await vi.advanceTimersByTimeAsync(120_000);

		expect(mockFetch).toHaveBeenCalledTimes(1);
		expect(live.getStatus()).toBe('disconnected');
	});

	it('backs off on 429 (too many streams)', async () => {
		mockFetch.mockResolvedValueOnce({ ok: false, status: 429, body: null });

		await live.start('u1');
		await flush();
		expect(mockFetch).toHaveBeenCalledTimes(1);
		await vi.advanceTimersByTimeAsync(1000);

		expect(mockFetch).toHaveBeenCalledTimes(2);
	});

	it('refreshAuth restarts the stream with the rotated token', async () => {
		await live.start('u1');
		await flush();
		mockAuth.token = 'token-rotated';

		await live.refreshAuth();
		await flush();

		expect(mockFetch).toHaveBeenCalledTimes(2);
		expect(mockFetch.mock.calls[1][1].headers.Authorization).toBe('Bearer token-rotated');
		// The abandoned stream does not schedule a reconnect of its own.
		await vi.advanceTimersByTimeAsync(5000);
		expect(mockFetch).toHaveBeenCalledTimes(2);
	});

	it('refreshAuth is a no-op while stopped', async () => {
		await live.refreshAuth();
		await flush();

		expect(mockFetch).not.toHaveBeenCalled();
	});

	it('start is idempotent for the same user', async () => {
		await live.start('u1');
		await live.start('u1');
		await flush();

		expect(mockFetch).toHaveBeenCalledTimes(1);
	});

	it('catchUp refetches even while the stream is open', async () => {
		const events = vi.fn();
		live.subscribe('events', events);
		await live.start('u1');
		await flush();

		live.catchUp();
		await vi.advanceTimersByTimeAsync(350);

		expect(events).toHaveBeenCalledWith(expect.objectContaining({ operation: 'CATCHUP' }));
	});
});
