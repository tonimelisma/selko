import { describe, it, expect } from 'vitest';
import {
	createLaneOrder,
	seedLaneOrder,
	reconcileLaneOrder,
	sortLaneEvents
} from '../review-queue-order.js';

function senderForEvent(e) {
	return { senderKey: e.sender, senderName: e.sender };
}

describe('review-queue-order', () => {
	it('seeds order from server snapshot in array order', () => {
		const events = [
			{ id: 'a', sender: 'alice@x.com', start_datetime: '2026-08-10T10:00:00Z' },
			{ id: 'b', sender: 'bob@x.com', start_datetime: '2026-08-10T11:00:00Z' },
			{ id: 'c', sender: 'alice@x.com', start_datetime: '2026-08-10T12:00:00Z' }
		];
		const order = seedLaneOrder(events, senderForEvent);
		expect(order.senderRank.get('alice@x.com')).toBe(0);
		expect(order.senderRank.get('bob@x.com')).toBe(1);
		expect(order.eventRank.get('a')).toBe(0);
		expect(order.eventRank.get('b')).toBe(1);
		expect(order.eventRank.get('c')).toBe(2);
	});

	it('keeps sender group in place when earliest event is rejected and realtime refetches', () => {
		// Initial snapshot: alice has 2 events, bob has 1
		const initial = [
			{ id: 'a1', sender: 'alice@x.com' },
			{ id: 'a2', sender: 'alice@x.com' },
			{ id: 'b1', sender: 'bob@x.com' }
		];
		const order = seedLaneOrder(initial, senderForEvent);
		// Alice's earliest (a1) is rejected optimistically, then server returns without a1
		const afterRealtime = [
			{ id: 'a2', sender: 'alice@x.com' },
			{ id: 'b1', sender: 'bob@x.com' }
		];
		reconcileLaneOrder(order, initial, afterRealtime, senderForEvent);
		// Alice should still be before Bob even though her earliest is gone
		expect(order.senderRank.get('alice@x.com')).toBe(0);
		expect(order.senderRank.get('bob@x.com')).toBe(1);
		const sorted = sortLaneEvents(afterRealtime, order, senderForEvent);
		expect(sorted.map((e) => e.id)).toEqual(['a2', 'b1']);
	});

	it('appends new card for existing sender after known cards', () => {
		const initial = [
			{ id: 'a1', sender: 'alice@x.com' },
			{ id: 'b1', sender: 'bob@x.com' }
		];
		const order = seedLaneOrder(initial, senderForEvent);
		const after = [
			{ id: 'a1', sender: 'alice@x.com' },
			{ id: 'b1', sender: 'bob@x.com' },
			{ id: 'a2', sender: 'alice@x.com' } // new for alice
		];
		reconcileLaneOrder(order, initial, after, senderForEvent);
		const sorted = sortLaneEvents(after, order, senderForEvent);
		// Within alice, a1 (rank 0) before a2 (rank 2); bob (sender rank 1) interleaves between?
		// Actually sorted by senderRank first: alice group (0) before bob (1)
		// So a1, a2, b1
		expect(sorted.map((e) => e.id)).toEqual(['a1', 'a2', 'b1']);
	});

	it('appends new sender after all known groups even if older', () => {
		const initial = [
			{ id: 'a1', sender: 'alice@x.com', start_datetime: '2026-08-11T10:00:00Z' }
		];
		const order = seedLaneOrder(initial, senderForEvent);
		const after = [
			{ id: 'a1', sender: 'alice@x.com', start_datetime: '2026-08-11T10:00:00Z' },
			{ id: 'c1', sender: 'carol@x.com', start_datetime: '2026-08-10T09:00:00Z' } // older but new sender
		];
		reconcileLaneOrder(order, initial, after, senderForEvent);
		const sorted = sortLaneEvents(after, order, senderForEvent);
		expect(sorted.map((e) => e.id)).toEqual(['a1', 'c1']); // carol appends, not sorted by date
	});

	it('retains removed rank for Undo', () => {
		const initial = [
			{ id: 'a1', sender: 'alice@x.com' },
			{ id: 'a2', sender: 'alice@x.com' }
		];
		const order = seedLaneOrder(initial, senderForEvent);
		const after = [{ id: 'a2', sender: 'alice@x.com' }];
		reconcileLaneOrder(order, initial, after, senderForEvent);
		// a1 rank retained
		expect(order.eventRank.has('a1')).toBe(true);
		// Undo reinserts a1 — should sort back to original position
		const undone = [
			{ id: 'a1', sender: 'alice@x.com' },
			{ id: 'a2', sender: 'alice@x.com' }
		];
		const sorted = sortLaneEvents(undone, order, senderForEvent);
		expect(sorted.map((e) => e.id)).toEqual(['a1', 'a2']);
	});

	it('sorts within sender by eventRank not start_datetime', () => {
		const events = [
			{ id: 'a2', sender: 'alice@x.com', start_datetime: '2026-08-11T12:00:00Z' },
			{ id: 'a1', sender: 'alice@x.com', start_datetime: '2026-08-10T10:00:00Z' }
		];
		// Seed in given order: a2 rank 0, a1 rank 1
		const order = seedLaneOrder(events, senderForEvent);
		const sorted = sortLaneEvents([...events].reverse(), order, senderForEvent);
		// Even though a1 is earlier chronologically, a2 was seeded first so stays first
		expect(sorted.map((e) => e.id)).toEqual(['a2', 'a1']);
	});
});
