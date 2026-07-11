// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { mockEvents, mockErrors } from '../../../../tests/fixtures/mock-data.js';

// Mock supabase module
const mockFrom = vi.fn();
vi.mock('$lib/supabase.js', () => ({
	supabase: {
		from: (...args) => mockFrom(...args)
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
	});

	describe('fetchPendingEvents', () => {
		it('fetches events with pending_review status', async () => {
			const pendingEvents = mockEvents.filter((e) => e.status === 'pending_review');
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				eq: vi.fn().mockReturnThis(),
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
			expect(mockQuery.eq).toHaveBeenCalledWith('status', 'pending_review');
			expect(mockQuery.order).toHaveBeenCalledWith('start_datetime', { ascending: true });
			expect(result.data).toEqual(pendingEvents);
			expect(result.count).toBe(pendingEvents.length);
			expect(result.error).toBeNull();
		});

		it('handles errors gracefully', async () => {
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				eq: vi.fn().mockReturnThis(),
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
			const eventsWithSources = [
				{
					...mockEvents[0],
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
				order: vi.fn().mockResolvedValue({
					data: eventsWithSources,
					error: null
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			const result = await fetchPendingEventsWithSources();

			expect(mockFrom).toHaveBeenCalledWith('events');
			expect(mockQuery.select).toHaveBeenCalledWith(
				'*, event_sources(*, emails(id, subject, from_email, from_name, date_sent))'
			);
			expect(mockQuery.in).toHaveBeenCalledWith('status', ['pending_review', 'pending_change']);
			expect(mockQuery.order).toHaveBeenCalledWith('start_datetime', { ascending: true });
			expect(result.data).toEqual(eventsWithSources);
			expect(result.error).toBeNull();
		});

		it('handles errors gracefully', async () => {
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				in: vi.fn().mockReturnThis(),
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
	});

	describe('fetchActivityEvents', () => {
		it('fetches activity events with default options', async () => {
			const activityEvents = mockEvents.filter((e) => e.status === 'approved');
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				in: vi.fn().mockReturnThis(),
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
			expect(mockQuery.in).toHaveBeenCalledWith('status', [
				'approved',
				'synced',
				'sync_failed',
				'rejected',
				'cancelled'
			]);
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

		it('handles errors gracefully', async () => {
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				in: vi.fn().mockReturnThis(),
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

		it('filters by statuses', async () => {
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				order: vi.fn().mockReturnThis(),
				range: vi.fn().mockReturnThis(),
				in: vi.fn().mockResolvedValue({
					data: mockEvents.filter((e) => e.status === 'approved'),
					error: null,
					count: 1
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			const result = await fetchEvents({ statuses: ['approved', 'synced'] });

			expect(mockQuery.in).toHaveBeenCalledWith('status', ['approved', 'synced']);
			expect(result.data.every((e) => e.status === 'approved')).toBe(true);
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
			expect(mockQuery.select).toHaveBeenCalledWith('*');
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
			const approvedEvent = { ...mockEvents[0], status: 'approved' };
			const mockQuery = {
				update: vi.fn().mockReturnThis(),
				eq: vi.fn().mockReturnThis(),
				select: vi.fn().mockReturnThis(),
				single: vi.fn().mockResolvedValue({
					data: approvedEvent,
					error: null
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			const result = await updateEventStatus(mockEvents[0].id, 'approved');

			expect(mockFrom).toHaveBeenCalledWith('events');
			expect(mockQuery.update).toHaveBeenCalledWith({ status: 'approved' });
			expect(mockQuery.eq).toHaveBeenCalledWith('id', mockEvents[0].id);
			expect(result.data?.status).toBe('approved');
		});

		it('rejects an event', async () => {
			const rejectedEvent = { ...mockEvents[0], status: 'rejected' };
			const mockQuery = {
				update: vi.fn().mockReturnThis(),
				eq: vi.fn().mockReturnThis(),
				select: vi.fn().mockReturnThis(),
				single: vi.fn().mockResolvedValue({
					data: rejectedEvent,
					error: null
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			const result = await updateEventStatus(mockEvents[0].id, 'rejected');

			expect(mockQuery.update).toHaveBeenCalledWith({ status: 'rejected' });
			expect(result.data?.status).toBe('rejected');
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
