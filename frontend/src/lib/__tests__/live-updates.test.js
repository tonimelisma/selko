import { describe, expect, it, vi, beforeEach, afterEach } from 'vitest';

vi.mock('$lib/supabase.js', () => ({
	supabase: {
		realtime: {
			setAuth: vi.fn().mockResolvedValue(undefined)
		},
		channel: vi.fn((topic) => ({
			topic,
			on: vi.fn().mockReturnThis(),
			subscribe: vi.fn().mockImplementation((cb) => {
				subscribeCallback = cb;
				return topic;
			})
		})),
		removeChannel: vi.fn().mockResolvedValue(undefined),
		auth: {
			getSession: vi.fn().mockResolvedValue({
				data: { session: { access_token: 'initial-token' } }
			})
		}
	}
}));

/** @type {((status: string) => void) | null} */
let subscribeCallback = null;

import * as liveUpdates from '../live-updates.js';
import { supabase } from '$lib/supabase.js';

describe('live-updates auth + lifecycle (C6)', () => {
	beforeEach(() => {
		subscribeCallback = null;
		liveUpdates.__resetForTests();
		vi.clearAllMocks();
	});

	afterEach(() => {
		liveUpdates.__resetForTests();
	});

	it('re-authorizes realtime on TOKEN_REFRESHED', async () => {
		await liveUpdates.refreshAuth('new-token-123');
		expect(supabase.realtime.setAuth).toHaveBeenCalledWith('new-token-123');
	});

	it('refreshAuth is a no-op without a token', async () => {
		await liveUpdates.refreshAuth(null);
		await liveUpdates.refreshAuth('');
		expect(supabase.realtime.setAuth).not.toHaveBeenCalled();
	});

	it('catchUp refetches even when the channel is already open', async () => {
		/** @type {string[]} */
		const seen = [];
		liveUpdates.subscribe('events', (inv) => seen.push(inv.operation));
		// Channel already established: start() would short-circuit, catchUp() must not.
		await liveUpdates.start('user-1');
		liveUpdates.catchUp();
		await new Promise((r) => setTimeout(r, 450));
		expect(seen).toContain('CATCHUP');
	});

	it('rejoins after CHANNEL_ERROR', async () => {
		vi.useFakeTimers();
		await liveUpdates.start('user-1');
		expect(subscribeCallback).toBeTypeOf('function');

		// Terminal state → schedule a rejoin (stop + start) with backoff.
		subscribeCallback?.('CHANNEL_ERROR');
		expect(supabase.removeChannel).not.toHaveBeenCalled(); // not yet — backoff delay
		await vi.advanceTimersByTimeAsync(1000);
		expect(supabase.removeChannel).toHaveBeenCalled();
		expect(supabase.channel).toHaveBeenCalledTimes(2);
		vi.useRealTimers();
	});
});
