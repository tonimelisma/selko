// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { mockEvents } from '../../../../tests/fixtures/mock-data.js';

const mockApiFetch = vi.fn();
vi.mock('$lib/api/client.js', () => ({
	apiFetch: (...args) => mockApiFetch(...args)
}));

const {
	fetchPendingEventsWithSources,
	fetchActivityEvents,
	getEvent,
	updateEventStatus,
	updateEvent,
	isNewReviewEvent,
	isChangeReviewEvent,
	isHistoryEvent,
	pendingEventProposal
} = await import('../events.js');

const ok = (data) => ({ data, error: null, status: 200 });
const fail = (message, status = 500, code) => ({ data: null, error: { message, status, code }, status });

describe('events service', () => {
	beforeEach(() => {
		mockApiFetch.mockReset();
	});

	describe('fetchPendingEventsWithSources', () => {
		it('reads the review queue from GET /events/review', async () => {
			const queue = [
				{
					...mockEvents[0],
					status: 'pending_review',
					event_sources: [{ id: 'src-1', emails: { id: 'email-1', subject: 'Test', from_email: 'a@b.com' } }]
				}
			];
			mockApiFetch.mockResolvedValue(ok(queue));

			const result = await fetchPendingEventsWithSources();

			expect(mockApiFetch).toHaveBeenCalledWith('/events/review');
			expect(result.data).toEqual(queue);
			expect(result.error).toBeNull();
		});

		it('returns an empty list and the error on failure', async () => {
			mockApiFetch.mockResolvedValue(fail('Database error'));

			const result = await fetchPendingEventsWithSources();

			expect(result.data).toEqual([]);
			expect(result.error.message).toBe('Database error');
			expect(result.error.status).toBe(500);
		});

		it('returns an empty list when the body is empty', async () => {
			mockApiFetch.mockResolvedValue(ok(null));

			const result = await fetchPendingEventsWithSources();

			expect(result.data).toEqual([]);
			expect(result.error).toBeNull();
		});
	});

	describe('fetchActivityEvents', () => {
		it('asks for the default page and maps {items, total} to {data, count}', async () => {
			mockApiFetch.mockResolvedValue(ok({ items: [mockEvents[1]], total: 1, offset: 0, limit: 20 }));

			const result = await fetchActivityEvents();

			expect(mockApiFetch).toHaveBeenCalledWith('/events/activity', { query: { limit: 20, offset: 0 } });
			expect(result.data).toEqual([mockEvents[1]]);
			expect(result.count).toBe(1);
			expect(result.error).toBeNull();
		});

		it('passes a custom limit and offset', async () => {
			mockApiFetch.mockResolvedValue(ok({ items: [], total: 0 }));

			await fetchActivityEvents({ limit: 10, offset: 20 });

			expect(mockApiFetch).toHaveBeenCalledWith('/events/activity', { query: { limit: 10, offset: 20 } });
		});

		it('clamps the page size to what the API accepts', async () => {
			mockApiFetch.mockResolvedValue(ok({ items: [], total: 0 }));

			await fetchActivityEvents({ limit: 900, offset: -5 });

			expect(mockApiFetch).toHaveBeenCalledWith('/events/activity', { query: { limit: 500, offset: 0 } });
		});

		it('pages through history without repeating rows', async () => {
			const pages = [
				{ items: [{ ...mockEvents[1], id: 'history-1' }, { ...mockEvents[1], id: 'history-2' }], total: 4 },
				{ items: [{ ...mockEvents[1], id: 'history-3' }, { ...mockEvents[1], id: 'history-4' }], total: 4 }
			];
			mockApiFetch.mockImplementation(async () => ok(pages.shift()));

			const firstPage = await fetchActivityEvents({ limit: 2, offset: 0 });
			const secondPage = await fetchActivityEvents({ limit: 2, offset: 2 });

			expect(firstPage.data.map((event) => event.id)).toEqual(['history-1', 'history-2']);
			expect(secondPage.data.map((event) => event.id)).toEqual(['history-3', 'history-4']);
			expect(firstPage.count).toBe(4);
			expect(secondPage.count).toBe(4);
		});

		it('returns an empty page and a null count on failure', async () => {
			mockApiFetch.mockResolvedValue(fail('Database error'));

			const result = await fetchActivityEvents();

			expect(result.data).toEqual([]);
			expect(result.count).toBeNull();
			expect(result.error.message).toBe('Database error');
		});
	});

	describe('getEvent', () => {
		it('fetches one event with its relations', async () => {
			mockApiFetch.mockResolvedValue(ok(mockEvents[0]));

			const result = await getEvent('event-1');

			expect(mockApiFetch).toHaveBeenCalledWith('/events/event-1');
			expect(result.data).toEqual(mockEvents[0]);
			expect(result.error).toBeNull();
		});

		it('reports a missing event', async () => {
			mockApiFetch.mockResolvedValue(fail('Event not found', 404));

			const result = await getEvent('nonexistent');

			expect(result.data).toBeNull();
			expect(result.error.message).toBe('Event not found');
			expect(result.error.status).toBe(404);
		});
	});

	describe('updateEventStatus', () => {
		it('approves an event with POST /events/{id}/accept', async () => {
			const decision = { event_id: 'event-1', review_status: 'active', work_item_id: 'w1', generation: 1 };
			mockApiFetch.mockResolvedValue(ok(decision));

			const result = await updateEventStatus('event-1', 'approved');

			expect(mockApiFetch).toHaveBeenCalledWith('/events/event-1/accept', { method: 'POST' });
			expect(result.data).toEqual(decision);
			expect(result.error).toBeNull();
		});

		it('rejects an event with POST /events/{id}/reject', async () => {
			mockApiFetch.mockResolvedValue(ok({ event_id: 'event-1', review_status: 'rejected' }));

			const result = await updateEventStatus('event-1', 'rejected');

			expect(mockApiFetch).toHaveBeenCalledWith('/events/event-1/reject', { method: 'POST' });
			expect(result.error).toBeNull();
		});

		it('refuses any other transition without calling the API', async () => {
			const result = await updateEventStatus('event-1', 'synced');

			expect(mockApiFetch).not.toHaveBeenCalled();
			expect(result.error.message).toContain('Unsupported review transition');
		});

		it('returns the API error', async () => {
			mockApiFetch.mockResolvedValue(fail('Event not found', 404));

			const result = await updateEventStatus('event-1', 'approved');

			expect(result.data).toBeNull();
			expect(result.error.status).toBe(404);
		});
	});

	describe('updateEvent', () => {
		it('PATCHes only the given fields and returns the full event', async () => {
			const updated = { ...mockEvents[0], title: 'Updated', status: 'pending_review', event_sources: [] };
			mockApiFetch.mockResolvedValue(ok(updated));

			const result = await updateEvent('event-1', { title: 'Updated', location: undefined, all_day: false });

			expect(mockApiFetch).toHaveBeenCalledWith('/events/event-1', {
				method: 'PATCH',
				body: { title: 'Updated', all_day: false }
			});
			expect(result.data).toEqual(updated);
		});

		it('sends datetime fields as given', async () => {
			mockApiFetch.mockResolvedValue(ok(mockEvents[0]));

			await updateEvent('event-1', {
				start_datetime: '2026-02-01T10:00:00Z',
				end_datetime: '2026-02-01T11:00:00Z'
			});

			expect(mockApiFetch.mock.calls[0][1].body).toEqual({
				start_datetime: '2026-02-01T10:00:00Z',
				end_datetime: '2026-02-01T11:00:00Z'
			});
		});

		it('returns the API error', async () => {
			mockApiFetch.mockResolvedValue(fail('title must not be blank', 422));

			const result = await updateEvent('event-1', { title: ' ' });

			expect(result.data).toBeNull();
			expect(result.error.message).toBe('title must not be blank');
		});
	});

	describe('lane helpers', () => {
		const pending = { review_status: 'pending_review', event_change_proposals: [] };
		const changed = { review_status: 'active', event_change_proposals: [{ id: 'p1', status: 'pending' }] };
		const decided = { review_status: 'active', event_change_proposals: [{ id: 'p2', status: 'applied' }] };

		it('classifies New, Changes and History events', () => {
			expect(isNewReviewEvent(pending)).toBe(true);
			expect(isChangeReviewEvent(changed)).toBe(true);
			expect(pendingEventProposal(changed).id).toBe('p1');
			expect(isHistoryEvent(decided)).toBe(true);
			expect(isHistoryEvent(pending)).toBe(false);
			expect(isHistoryEvent(changed)).toBe(false);
		});
	});
});
