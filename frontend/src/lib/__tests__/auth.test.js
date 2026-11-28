// @ts-nocheck
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

/** A BroadcastChannel double: every instance with the same name hears the others. */
class FakeChannel {
	static all = [];
	constructor(name) {
		this.name = name;
		this.onmessage = null;
		this.posted = [];
		FakeChannel.all.push(this);
	}
	postMessage(data) {
		this.posted.push(data);
		for (const other of FakeChannel.all) {
			if (other !== this && other.name === this.name) other.onmessage?.({ data });
		}
	}
	close() {
		FakeChannel.all = FakeChannel.all.filter((c) => c !== this);
	}
}
vi.stubGlobal('BroadcastChannel', FakeChannel);

const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

const auth = await import('../auth.js');

const nowSeconds = () => Math.floor(Date.now() / 1000);
function tokenBody(token = 'access-1', user = { id: 'u1', email: 'a@b.com' }) {
	return { access_token: token, token_type: 'bearer', expires_in: 3600, expires_at: nowSeconds() + 3600, user };
}
function respond(status, body = {}) {
	return { ok: status >= 200 && status < 300, status, json: () => Promise.resolve(body) };
}

describe('auth', () => {
	beforeEach(() => {
		auth.__resetForTests();
		FakeChannel.all = [];
		mockFetch.mockReset();
	});

	afterEach(() => {
		vi.useRealTimers();
	});

	describe('restoreSession', () => {
		// Validates: SEL-503, SEL-725
		it('on 200 keeps the access token in memory and returns the user', async () => {
			mockFetch.mockResolvedValue(respond(200, tokenBody()));

			const result = await auth.restoreSession();

			expect(result).toEqual({ user: { id: 'u1', email: 'a@b.com' }, unavailable: false });
			expect(auth.getAccessToken()).toBe('access-1');
			const [url, init] = mockFetch.mock.calls[0];
			expect(url).toBe('http://localhost:8000/auth/token');
			expect(init.method).toBe('POST');
			expect(init.credentials).toBe('include');
			expect(init.headers['Content-Type']).toBe('application/json');
			expect(JSON.parse(init.body)).toEqual({ grant_type: 'refresh_token' });
		});

		// Validates: SEL-506
		it('on 401 is signed out, not unavailable', async () => {
			mockFetch.mockResolvedValue(respond(401, { detail: { code: 'INVALID_GRANT', message: 'Session expired' } }));

			const result = await auth.restoreSession();

			expect(result).toEqual({ user: null, unavailable: false });
			expect(auth.getAccessToken()).toBeNull();
		});

		// Validates: SEL-506
		it('on a network failure reports Selko unavailable', async () => {
			mockFetch.mockRejectedValue(new TypeError('Failed to fetch'));

			const result = await auth.restoreSession();

			expect(result).toEqual({ user: null, unavailable: true });
		});

		// Validates: SEL-506
		it('on a server error reports Selko unavailable', async () => {
			mockFetch.mockResolvedValue(respond(502));

			expect(await auth.restoreSession()).toEqual({ user: null, unavailable: true });
		});
	});

	describe('signIn / signUp', () => {
		// Validates: SEL-515
		it('signs in with the password grant and announces it', async () => {
			const events = [];
			auth.onAuthChange((event, user) => events.push([event, user?.id]));
			mockFetch.mockResolvedValue(respond(200, tokenBody('access-2')));

			const result = await auth.signIn('a@b.com', 'secret1');

			expect(JSON.parse(mockFetch.mock.calls[0][1].body)).toEqual({
				grant_type: 'password',
				email: 'a@b.com',
				password: 'secret1'
			});
			expect(result.error).toBeNull();
			expect(auth.getAccessToken()).toBe('access-2');
			expect(events).toEqual([['SIGNED_IN', 'u1']]);
		});

		// Validates: SEL-515
		it('returns the server’s message for bad credentials', async () => {
			mockFetch.mockResolvedValue(
				respond(400, { detail: { code: 'INVALID_CREDENTIALS', message: 'Invalid login credentials' } })
			);

			const result = await auth.signIn('a@b.com', 'wrong');

			expect(result.user).toBeNull();
			expect(result.error).toEqual({ message: 'Invalid login credentials', status: 400, code: 'INVALID_CREDENTIALS' });
			expect(auth.getAccessToken()).toBeNull();
		});

		// Validates: SEL-518
		it('signs up without signing in', async () => {
			mockFetch.mockResolvedValue(
				respond(201, { user: { id: 'u9', email: 'n@b.com', created_at: 'x' }, confirmation_required: false })
			);

			const result = await auth.signUp('n@b.com', 'secret1');

			expect(mockFetch.mock.calls[0][0]).toBe('http://localhost:8000/auth/signup');
			expect(result.data.confirmation_required).toBe(false);
			expect(auth.getAccessToken()).toBeNull();
		});
	});

	describe('refresh', () => {
		// Validates: SEL-502
		it('is single-flight: concurrent callers share one request', async () => {
			let release;
			mockFetch.mockImplementation(
				() =>
					new Promise((resolve) => {
						release = () => resolve(respond(200, tokenBody('access-3')));
					})
			);

			const calls = [auth.refresh(), auth.refresh(), auth.refresh()];
			await vi.waitFor(() => expect(release).toBeTypeOf('function'));
			release();
			const tokens = await Promise.all(calls);

			expect(mockFetch).toHaveBeenCalledTimes(1);
			expect(tokens).toEqual(['access-3', 'access-3', 'access-3']);
		});

		// Validates: SEL-504
		it('renews a minute before the access token expires', async () => {
			vi.useFakeTimers();
			mockFetch.mockResolvedValueOnce(respond(200, tokenBody('access-a')));
			await auth.restoreSession();
			mockFetch.mockImplementationOnce(async () => respond(200, tokenBody('access-b')));

			await vi.advanceTimersByTimeAsync(3600_000 - 61_000);
			expect(mockFetch).toHaveBeenCalledTimes(1);
			await vi.advanceTimersByTimeAsync(2_000);

			expect(mockFetch).toHaveBeenCalledTimes(2);
			expect(auth.getAccessToken()).toBe('access-b');
		});

		// Validates: SEL-505
		it('a refused refresh signs the tab out', async () => {
			mockFetch.mockResolvedValueOnce(respond(200, tokenBody()));
			await auth.restoreSession();
			const events = [];
			auth.onAuthChange((event) => events.push(event));
			mockFetch.mockResolvedValueOnce(respond(401));

			expect(await auth.refresh()).toBeNull();
			expect(auth.getAccessToken()).toBeNull();
			expect(events).toEqual(['SIGNED_OUT']);
		});

		// Validates: SEL-505
		it('an unreachable server keeps the session', async () => {
			mockFetch.mockResolvedValueOnce(respond(200, tokenBody()));
			await auth.restoreSession();
			mockFetch.mockRejectedValueOnce(new TypeError('Failed to fetch'));

			expect(await auth.refresh()).toBeNull();
			expect(auth.getAccessToken()).toBe('access-1');
		});
	});

	describe('signOut and other tabs', () => {
		// Validates: SEL-507, SEL-508
		it('posts the logout with the token, drops it and tells other tabs', async () => {
			mockFetch.mockResolvedValueOnce(respond(200, tokenBody()));
			await auth.restoreSession();
			const otherTab = new FakeChannel('selko-auth');
			const heard = [];
			otherTab.onmessage = (m) => heard.push(m.data);
			mockFetch.mockResolvedValueOnce(respond(204));

			await auth.signOut();

			const [url, init] = mockFetch.mock.calls[1];
			expect(url).toBe('http://localhost:8000/auth/logout');
			expect(init.credentials).toBe('include');
			expect(init.headers.Authorization).toBe('Bearer access-1');
			expect(JSON.parse(init.body)).toEqual({ scope: 'global' });
			expect(auth.getAccessToken()).toBeNull();
			expect(heard).toEqual([{ type: 'SIGNED_OUT' }]);
		});

		// Validates: SEL-507
		it('drops its token at once when another tab signs out', async () => {
			mockFetch.mockResolvedValueOnce(respond(200, tokenBody()));
			await auth.restoreSession();
			const events = [];
			auth.onAuthChange((event) => events.push(event));

			new FakeChannel('selko-auth').postMessage({ type: 'SIGNED_OUT' });

			expect(auth.getAccessToken()).toBeNull();
			expect(auth.getUser()).toBeNull();
			expect(events).toEqual(['SIGNED_OUT']);
			expect(mockFetch).toHaveBeenCalledTimes(1);
		});

		// Validates: SEL-507
		it('picks up the session when another tab signs in', async () => {
			auth.onAuthChange(() => {});
			mockFetch.mockResolvedValueOnce(respond(200, tokenBody('access-other')));

			new FakeChannel('selko-auth').postMessage({ type: 'SIGNED_IN' });

			await vi.waitFor(() => expect(auth.getAccessToken()).toBe('access-other'));
			expect(JSON.parse(mockFetch.mock.calls[0][1].body)).toEqual({ grant_type: 'refresh_token' });
		});

		// Validates: SEL-508
		it('clears the local session even when the logout request fails', async () => {
			mockFetch.mockResolvedValueOnce(respond(200, tokenBody()));
			await auth.restoreSession();
			mockFetch.mockRejectedValueOnce(new TypeError('Failed to fetch'));

			await auth.signOut();

			expect(auth.getAccessToken()).toBeNull();
		});
	});
});
