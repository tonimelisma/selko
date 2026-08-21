// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { mockEvents, mockErrors } from '../../../../tests/fixtures/mock-data.js';

// Mock supabase module
const mockFrom = vi.fn();
const mockRpc = vi.fn();
vi.mock('$lib/supabase.js', () => ({
	supabase: {
		from: (...args) => mockFrom(...args),
		rpc: (...args) => mockRpc(...args)
	}
}));

// Import after mocking
const {
	fetchPendingEvents,
	fetchPendingEventsWithSources,
	fetchActivityEvents,
	fetchEvents,
	getEvent,
	updateEventStatus,
	updateEvent
} = await import('../events.js');

describe('events service', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockRpc.mockReset();
	});

	describe('fetchPendingEvents', () => {
		it('fetches events with pending_review status', async () => {
			const future = new Date(Date.now() + 86400000).toISOString();
			const futureEnd = new Date(Date.now() + 90000000).toISOString();
			const pendingEvents = mockEvents
				.filter((e) => e.status === 'pending_review')
				.map((e) => ({ ...e, start_datetime: future, end_datetime: futureEnd }));
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				eq: vi.fn().mockReturnThis(),
				or: vi.fn().mockReturnThis(),
				order: vi.fn().mockResolvedValue({
					data: pendingEvents,
					error: null,
					count: pendingEvents.length
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			const result = await fetchPendingEvents();

			expect(mockFrom).toHaveBeenCalledWith('events');
			expect(mockQuery.select).toHaveBeenCalledWith('*', { count: 'exact' });
			expect(mockQuery.eq).toHaveBeenCalledWith('review_status', 'pending_review');
			expect(mockQuery.order).toHaveBeenCalledWith('start_datetime', { ascending: true });
			expect(result.data).toEqual(pendingEvents);
			expect(result.count).toBe(pendingEvents.length);
			expect(result.error).toBeNull();
		});

		it('handles errors gracefully', async () => {
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				eq: vi.fn().mockReturnThis(),
				or: vi.fn().mockReturnThis(),
				order: vi.fn().mockResolvedValue({
					data: null,
					error: mockErrors.permissionDenied,
					count: null
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			const result = await fetchPendingEvents();

			expect(result.data).toEqual([]);
			expect(result.error?.code).toBe('42501');
		});
	});

	describe('fetchPendingEventsWithSources', () => {
		it('fetches pending events with source email data', async () => {
			const future = new Date(Date.now() + 86400000).toISOString();
			const futureEnd = new Date(Date.now() + 90000000).toISOString();
			const eventsWithSources = [
				{
					...mockEvents[0],
					start_datetime: future,
					end_datetime: futureEnd,
					event_sources: [
						{
							id: 'src-1',
							emails: { id: 'email-1', subject: 'Test', from_email: 'a@b.com' }
						}
					]
				}
			];
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				in: vi.fn().mockReturnThis(),
				not: vi.fn().mockReturnThis(),
				or: vi.fn().mockReturnThis(),
				order: vi.fn().mockResolvedValue({
					data: eventsWithSources,
					error: null
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			const result = await fetchPendingEventsWithSources();

			expect(mockFrom).toHaveBeenCalledWith('events');
			expect(mockQuery.select.mock.calls[0][0]).toContain('event_change_proposals');
			expect(mockQuery.select.mock.calls[0][0]).toContain('calendar_work_items');
			expect(mockQuery.in).toHaveBeenCalledWith('review_status', ['pending_review', 'active']);
			expect(mockQuery.order).toHaveBeenCalledWith('start_datetime', { ascending: true });
			expect(result.data).toEqual(eventsWithSources);
			expect(result.error).toBeNull();
		});

		it('handles errors gracefully', async () => {
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				in: vi.fn().mockReturnThis(),
				not: vi.fn().mockReturnThis(),
				or: vi.fn().mockReturnThis(),
				order: vi.fn().mockResolvedValue({
					data: null,
					error: mockErrors.permissionDenied
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			const result = await fetchPendingEventsWithSources();

			expect(result.data).toEqual([]);
			expect(result.error?.code).toBe('42501');
		});

		it('returns empty array when data is null', async () => {
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				in: vi.fn().mockReturnThis(),
				not: vi.fn().mockReturnThis(),
				or: vi.fn().mockReturnThis(),
				order: vi.fn().mockResolvedValue({
					data: null,
					error: null
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			const result = await fetchPendingEventsWithSources();

			expect(result.data).toEqual([]);
			expect(result.error).toBeNull();
		});

		it('filters out past events from the review queue', async () => {
			const past = new Date(Date.now() - 86400000).toISOString();
			const pastEnd = new Date(Date.now() - 80000000).toISOString();
			const future = new Date(Date.now() + 86400000).toISOString();
			const futureEnd = new Date(Date.now() + 90000000).toISOString();
			const eventsWithSources = [
				{ ...mockEvents[0], start_datetime: past, end_datetime: pastEnd, event_sources: [] },
				{ ...mockEvents[0], id: 'future-1', start_datetime: future, end_datetime: futureEnd, event_sources: [] }
			];
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				in: vi.fn().mockReturnThis(),
				not: vi.fn().mockReturnThis(),
				or: vi.fn().mockReturnThis(),
				order: vi.fn().mockResolvedValue({ data: eventsWithSources, error: null })
			};
			mockFrom.mockReturnValue(mockQuery);
			const result = await fetchPendingEventsWithSources();
			expect(result.data).toHaveLength(1);
			expect(result.data[0].id).toBe('future-1');
		});

		it('keeps events with no datetime', async () => {
			const eventsWithSources = [
				{ ...mockEvents[0], start_datetime: null, end_datetime: null, event_sources: [] }
			];
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				in: vi.fn().mockReturnThis(),
				not: vi.fn().mockReturnThis(),
				or: vi.fn().mockReturnThis(),
				order: vi.fn().mockResolvedValue({ data: eventsWithSources, error: null })
			};
			mockFrom.mockReturnValue(mockQuery);
			const result = await fetchPendingEventsWithSources();
			expect(result.data).toHaveLength(1);
		});
	});

	describe('fetchActivityEvents', () => {
		it('fetches activity events with default options', async () => {
			const activityEvents = mockEvents.filter((e) => e.status === 'approved');
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				in: vi.fn().mockReturnThis(),
				or: vi.fn().mockReturnThis(),
				not: vi.fn().mockReturnThis(),
				order: vi.fn().mockReturnThis(),
				range: vi.fn().mockResolvedValue({
					data: activityEvents,
					error: null,
					count: activityEvents.length
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			const result = await fetchActivityEvents();

			expect(mockFrom).toHaveBeenCalledWith('events');
			expect(mockQuery.in).toHaveBeenCalledWith('review_status', ['active', 'rejected', 'cancelled']);
			expect(mockQuery.not).toHaveBeenCalledWith('event_change_proposals.status', 'eq', 'pending');
			expect(mockQuery.order).toHaveBeenCalledWith('updated_at', { ascending: false });
			expect(mockQuery.range).toHaveBeenCalledWith(0, 19);
			expect(result.data).toEqual(activityEvents);
			expect(result.count).toBe(activityEvents.length);
			expect(result.error).toBeNull();
		});

		it('applies custom limit and offset', async () => {
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				in: vi.fn().mockReturnThis(),
				not: vi.fn().mockReturnThis(),
				or: vi.fn().mockReturnThis(),
				order: vi.fn().mockReturnThis(),
				range: vi.fn().mockResolvedValue({
					data: [],
					error: null,
					count: 0
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			await fetchActivityEvents({ limit: 10, offset: 20 });

			expect(mockQuery.range).toHaveBeenCalledWith(20, 29);
		});

		it('keeps paginated history on the server-side activity relation filter', async () => {
			const pages = [
				[{ ...mockEvents[1], id: 'history-1' }, { ...mockEvents[1], id: 'history-2' }],
				[{ ...mockEvents[1], id: 'history-3' }, { ...mockEvents[1], id: 'history-4' }]
			];
			const queries = pages.map((page) => ({
				select: vi.fn().mockReturnThis(),
				in: vi.fn().mockReturnThis(),
				not: vi.fn().mockReturnThis(),
				order: vi.fn().mockReturnThis(),
				range: vi.fn().mockResolvedValue({ data: page, error: null, count: 4 })
			}));
			mockFrom.mockImplementation(() => queries.shift());

			const firstPage = await fetchActivityEvents({ limit: 2, offset: 0 });
			const secondPage = await fetchActivityEvents({ limit: 2, offset: 2 });

			expect(firstPage.data.map((event) => event.id)).toEqual(['history-1', 'history-2']);
			expect(secondPage.data.map((event) => event.id)).toEqual(['history-3', 'history-4']);
			expect(new Set([...firstPage.data, ...secondPage.data].map((event) => event.id)).size).toBe(4);
			expect(firstPage.count).toBe(4);
			expect(secondPage.count).toBe(4);
			expect(firstPage.error).toBeNull();
			expect(secondPage.error).toBeNull();
		});

		it('handles errors gracefully', async () => {
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				in: vi.fn().mockReturnThis(),
				not: vi.fn().mockReturnThis(),
				or: vi.fn().mockReturnThis(),
				order: vi.fn().mockReturnThis(),
				range: vi.fn().mockResolvedValue({
					data: null,
					error: mockErrors.permissionDenied,
					count: null
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			const result = await fetchActivityEvents();

			expect(result.data).toEqual([]);
			expect(result.count).toBeNull();
			expect(result.error?.code).toBe('42501');
		});
	});

	describe('fetchEvents', () => {
		it('fetches events with default options', async () => {
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				order: vi.fn().mockReturnThis(),
				range: vi.fn().mockResolvedValue({
					data: mockEvents,
					error: null,
					count: mockEvents.length
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			const result = await fetchEvents();

			expect(mockFrom).toHaveBeenCalledWith('events');
			expect(mockQuery.select).toHaveBeenCalledWith('*', { count: 'exact' });
			expect(mockQuery.order).toHaveBeenCalledWith('start_datetime', { ascending: true });
			expect(mockQuery.range).toHaveBeenCalledWith(0, 49);
			expect(result.data).toEqual(mockEvents);
		});

		it('filters review-lane statuses without querying the removed event status column', async () => {
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				order: vi.fn().mockReturnThis(),
				range: vi.fn().mockResolvedValue({
					data: mockEvents.filter((e) => e.review_status === 'pending_review'),
					error: null,
					count: 2
				}),
				in: vi.fn().mockReturnThis()
			};

			mockFrom.mockReturnValue(mockQuery);

			const result = await fetchEvents({ statuses: ['pending_review'] });

			expect(mockQuery.in).toHaveBeenCalledWith('review_status', ['pending_review']);
			expect(result.data.every((e) => e.status === 'pending_review')).toBe(true);
		});

		it('filters by date range', async () => {
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				order: vi.fn().mockReturnThis(),
				range: vi.fn().mockReturnThis(),
				gte: vi.fn().mockReturnThis(),
				lte: vi.fn().mockResolvedValue({
					data: [],
					error: null,
					count: 0
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			await fetchEvents({
				startAfter: '2024-01-01T00:00:00Z',
				startBefore: '2024-12-31T23:59:59Z'
			});

			expect(mockQuery.gte).toHaveBeenCalledWith('start_datetime', '2024-01-01T00:00:00Z');
			expect(mockQuery.lte).toHaveBeenCalledWith('start_datetime', '2024-12-31T23:59:59Z');
		});

		it('applies pagination', async () => {
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				order: vi.fn().mockReturnThis(),
				range: vi.fn().mockResolvedValue({
					data: [],
					error: null,
					count: 0
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			await fetchEvents({ limit: 25, offset: 50 });

			expect(mockQuery.range).toHaveBeenCalledWith(50, 74);
		});
	});

	describe('getEvent', () => {
		it('fetches a single event by ID', async () => {
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				eq: vi.fn().mockReturnThis(),
				single: vi.fn().mockResolvedValue({
					data: mockEvents[0],
					error: null
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			const result = await getEvent(mockEvents[0].id);

			expect(mockFrom).toHaveBeenCalledWith('events');
			expect(mockQuery.select.mock.calls[0][0]).toContain('event_change_proposals');
			expect(mockQuery.eq).toHaveBeenCalledWith('id', mockEvents[0].id);
			expect(result.data).toEqual(mockEvents[0]);
			expect(result.error).toBeNull();
		});

		it('handles not found', async () => {
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				eq: vi.fn().mockReturnThis(),
				single: vi.fn().mockResolvedValue({
					data: null,
					error: mockErrors.notFound
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			const result = await getEvent('non-existent');

			expect(result.data).toBeNull();
			expect(result.error).not.toBeNull();
		});
	});

	describe('updateEventStatus', () => {
		it('approves an event', async () => {
			mockRpc.mockResolvedValue({ data: { review_status: 'active' }, error: null });

			const result = await updateEventStatus(mockEvents[0].id, 'approved');

			expect(mockRpc).toHaveBeenCalledWith('set_event_review_status', {
				p_event_id: mockEvents[0].id,
				p_review_status: 'active'
			});
			expect(result.data?.status).toBe('approved');
		});

		it('rejects an event', async () => {
			mockRpc.mockResolvedValue({ data: { review_status: 'rejected' }, error: null });

			const result = await updateEventStatus(mockEvents[0].id, 'rejected');

			expect(mockRpc).toHaveBeenCalledWith('set_event_review_status', {
				p_event_id: mockEvents[0].id,
				p_review_status: 'rejected'
			});
			expect(result.data?.status).toBe('rejected');
		});

		it('handles errors', async () => {
			mockRpc.mockResolvedValue({ data: null, error: mockErrors.permissionDenied });

			const result = await updateEventStatus('id', 'approved');

			expect(result.data).toBeNull();
			expect(result.error?.code).toBe('42501');
		});
	});

	describe('updateEvent', () => {
		it('updates event details', async () => {
			const updates = {
				title: 'Updated Title',
				location: 'New Location'
			};
			const updatedEvent = { ...mockEvents[0], ...updates };
			const mockQuery = {
				update: vi.fn().mockReturnThis(),
				eq: vi.fn().mockReturnThis(),
				select: vi.fn().mockReturnThis(),
				single: vi.fn().mockResolvedValue({
					data: updatedEvent,
					error: null
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			const result = await updateEvent(mockEvents[0].id, updates);

			expect(mockFrom).toHaveBeenCalledWith('events');
			expect(mockQuery.update).toHaveBeenCalledWith(updates);
			expect(mockQuery.eq).toHaveBeenCalledWith('id', mockEvents[0].id);
			expect(result.data?.title).toBe('Updated Title');
			expect(result.data?.location).toBe('New Location');
		});

		it('updates datetime fields', async () => {
			const updates = {
				start_datetime: '2024-02-01T14:00:00Z',
				end_datetime: '2024-02-01T15:00:00Z'
			};
			const mockQuery = {
				update: vi.fn().mockReturnThis(),
				eq: vi.fn().mockReturnThis(),
				select: vi.fn().mockReturnThis(),
				single: vi.fn().mockResolvedValue({
					data: { ...mockEvents[0], ...updates },
					error: null
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			const result = await updateEvent(mockEvents[0].id, updates);

			expect(mockQuery.update).toHaveBeenCalledWith(updates);
			expect(result.data?.start_datetime).toBe(updates.start_datetime);
		});

		it('handles errors', async () => {
			const mockQuery = {
				update: vi.fn().mockReturnThis(),
				eq: vi.fn().mockReturnThis(),
				select: vi.fn().mockReturnThis(),
				single: vi.fn().mockResolvedValue({
					data: null,
					error: mockErrors.permissionDenied
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			const result = await updateEvent('id', { title: 'Test' });

			expect(result.data).toBeNull();
			expect(result.error).not.toBeNull();
		});
	});
});
