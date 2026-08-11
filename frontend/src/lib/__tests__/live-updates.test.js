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

	// F1.1 (D1): rejoinAttempts was declared inside start(), so every rejoin
	// re-declared it at 0 and the backoff never advanced past 1000ms.
	it('grows the rejoin delay across consecutive failures', async () => {
		vi.useFakeTimers();
		await liveUpdates.start('user-1');
		expect(subscribeCallback).toBeTypeOf('function');

		// 1st failure -> 1000ms delay
		subscribeCallback?.('CHANNEL_ERROR');
		await vi.advanceTimersByTimeAsync(999);
		expect(supabase.channel).toHaveBeenCalledTimes(1);
		await vi.advanceTimersByTimeAsync(1);
		expect(supabase.channel).toHaveBeenCalledTimes(2);

		// 2nd failure (on the new channel) -> 2000ms delay
		subscribeCallback?.('CHANNEL_ERROR');
		await vi.advanceTimersByTimeAsync(1999);
		expect(supabase.channel).toHaveBeenCalledTimes(2);
		await vi.advanceTimersByTimeAsync(1);
		expect(supabase.channel).toHaveBeenCalledTimes(3);

		// 3rd failure -> 4000ms delay
		subscribeCallback?.('CHANNEL_ERROR');
		await vi.advanceTimersByTimeAsync(3999);
		expect(supabase.channel).toHaveBeenCalledTimes(3);
		await vi.advanceTimersByTimeAsync(1);
		expect(supabase.channel).toHaveBeenCalledTimes(4);

		vi.useRealTimers();
	});

	it('caps the rejoin delay at 60s', async () => {
		vi.useFakeTimers();
		await liveUpdates.start('user-1');

		const growingDelays = [1000, 2000, 4000, 8000, 16000, 32000];
		for (const delay of growingDelays) {
			subscribeCallback?.('CHANNEL_ERROR');
			await vi.advanceTimersByTimeAsync(delay);
		}

		// 7th failure would be 64000ms uncapped; must cap at 60000ms.
		subscribeCallback?.('CHANNEL_ERROR');
		const callsBefore = vi.mocked(supabase.channel).mock.calls.length;
		await vi.advanceTimersByTimeAsync(59999);
		expect(supabase.channel).toHaveBeenCalledTimes(callsBefore);
		await vi.advanceTimersByTimeAsync(1);
		expect(supabase.channel).toHaveBeenCalledTimes(callsBefore + 1);

		vi.useRealTimers();
	});

	it('resets the delay after a successful SUBSCRIBED', async () => {
		vi.useFakeTimers();
		await liveUpdates.start('user-1');

		subscribeCallback?.('CHANNEL_ERROR'); // 1000ms delay
		await vi.advanceTimersByTimeAsync(1000);

		subscribeCallback?.('CHANNEL_ERROR'); // 2000ms delay
		await vi.advanceTimersByTimeAsync(2000);

		subscribeCallback?.('SUBSCRIBED'); // resets backoff

		subscribeCallback?.('CHANNEL_ERROR'); // should be back to 1000ms
		const callsBefore = vi.mocked(supabase.channel).mock.calls.length;
		await vi.advanceTimersByTimeAsync(999);
		expect(supabase.channel).toHaveBeenCalledTimes(callsBefore);
		await vi.advanceTimersByTimeAsync(1);
		expect(supabase.channel).toHaveBeenCalledTimes(callsBefore + 1);

		vi.useRealTimers();
	});

	it('does not rejoin after a deliberate stop', async () => {
		vi.useFakeTimers();
		await liveUpdates.start('user-1');
		const callsBefore = vi.mocked(supabase.channel).mock.calls.length;

		await liveUpdates.stop();
		subscribeCallback?.('CLOSED');
		await vi.advanceTimersByTimeAsync(60000);

		expect(supabase.channel).toHaveBeenCalledTimes(callsBefore);
		vi.useRealTimers();
	});
});
