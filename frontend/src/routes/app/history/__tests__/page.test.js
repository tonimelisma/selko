// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';

const mockFetchActivityEvents = vi.fn();
const mockUpdateEventStatus = vi.fn();

vi.mock('$lib/services/events.js', () => ({
	fetchActivityEvents: (...args) => mockFetchActivityEvents(...args),
	updateEventStatus: (...args) => mockUpdateEventStatus(...args)
}));

const mockSyncEventToCalendar = vi.fn();
const mockUndoHistoryEvent = vi.fn();

vi.mock('$lib/api/backend.js', () => ({
	syncEventToCalendar: (...args) => mockSyncEventToCalendar(...args),
	undoHistoryEvent: (...args) => mockUndoHistoryEvent(...args)
}));

const { default: HistoryPage } = await import('../+page.svelte');

describe('History Page', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockUpdateEventStatus.mockResolvedValue({ data: null, error: null });
		mockSyncEventToCalendar.mockResolvedValue({ data: null, error: null });
		mockUndoHistoryEvent.mockResolvedValue({ data: { event_id: 'evt-1', status: 'pending_review' }, error: null });
	});

	it('shows loading skeleton initially', () => {
		mockFetchActivityEvents.mockReturnValue(new Promise(() => {}));

		render(HistoryPage);

		expect(document.querySelector('.animate-pulse')).toBeTruthy();
	});

	it('shows empty state when no activity', async () => {
		mockFetchActivityEvents.mockResolvedValue({
			data: [],
			count: 0,
			error: null
		});

		render(HistoryPage);

		await waitFor(() => {
			expect(screen.getByText('No activity yet')).toBeInTheDocument();
		});
	});

	it('shows activity events', async () => {
		const now = new Date();
		mockFetchActivityEvents.mockResolvedValue({
			data: [
				{
					id: 'evt-1',
					title: 'Team Meeting',
					status: 'synced',
					updated_at: now.toISOString(),
					event_sources: []
				}
			],
			count: 1,
			error: null
		});

		render(HistoryPage);

		await waitFor(() => {
			expect(screen.getByText('Team Meeting')).toBeInTheDocument();
		});
	});

	it('shows undo button for synced events', async () => {
		const now = new Date();
		mockFetchActivityEvents.mockResolvedValue({
			data: [
				{
					id: 'evt-1',
					title: 'Team Meeting',
					status: 'synced',
					updated_at: now.toISOString(),
					event_sources: []
				}
			],
			count: 1,
			error: null
		});

		render(HistoryPage);

		await waitFor(() => {
			expect(screen.getByText('Undo')).toBeInTheDocument();
		});
	});

	it('shows retry button for failed syncs', async () => {
		const now = new Date();
		mockFetchActivityEvents.mockResolvedValue({
			data: [
				{
					id: 'evt-1',
					title: 'Failed Event',
					status: 'sync_failed',
					updated_at: now.toISOString(),
					event_sources: []
				}
			],
			count: 1,
			error: null
		});

		render(HistoryPage);

		await waitFor(() => {
			expect(screen.getByText('Retry')).toBeInTheDocument();
		});
	});

	it('calls undoHistoryEvent on undo', async () => {
		const user = userEvent.setup();
		const now = new Date();
		mockFetchActivityEvents.mockResolvedValue({
			data: [
				{
					id: 'evt-1',
					title: 'Meeting',
					status: 'approved',
					updated_at: now.toISOString(),
					event_sources: []
				}
			],
			count: 1,
			error: null
		});

		render(HistoryPage);

		await waitFor(() => {
			expect(screen.getByText('Undo')).toBeInTheDocument();
		});

		await user.click(screen.getByText('Undo'));

		expect(mockUndoHistoryEvent).toHaveBeenCalledWith('evt-1');
	});

	it('shows Load More button when more events available', async () => {
		const now = new Date();
		const events = Array.from({ length: 20 }, (_, i) => ({
			id: `evt-${i}`,
			title: `Event ${i}`,
			status: 'synced',
			updated_at: now.toISOString(),
			event_sources: []
		}));

		mockFetchActivityEvents.mockResolvedValue({
			data: events,
			count: 30,
			error: null
		});

		render(HistoryPage);

		await waitFor(() => {
			expect(screen.getByText('Load More')).toBeInTheDocument();
		});
	});

	it('shows error with retry button on failure', async () => {
		mockFetchActivityEvents.mockResolvedValue({
			data: [],
			count: null,
			error: { message: 'Database error', code: 'UNKNOWN' }
		});

		render(HistoryPage);

		await waitFor(() => {
			expect(screen.getByText('Database error')).toBeInTheDocument();
			expect(screen.getByText('Retry')).toBeInTheDocument();
		});
	});

	it('shows spinner immediately on undo and keeps list on failure', async () => {
		const user = userEvent.setup();
		const now = new Date();
		let resolveUndo;
		mockFetchActivityEvents.mockResolvedValue({
			data: [
				{
					id: 'evt-1',
					title: 'Meeting',
					status: 'synced',
					updated_at: now.toISOString(),
					event_sources: []
				}
			],
			count: 1,
			error: null
		});
		mockUndoHistoryEvent.mockReturnValue(
			new Promise((resolve) => {
				resolveUndo = resolve;
			})
		);

		render(HistoryPage);

		await waitFor(() => {
			expect(screen.getByText('Undo')).toBeInTheDocument();
		});

		await user.click(screen.getByText('Undo'));

		await waitFor(() => {
			expect(document.querySelector('.loading.loading-spinner')).toBeTruthy();
			expect(screen.getByText('Meeting')).toBeInTheDocument();
		});

		resolveUndo({ data: null, error: { message: 'Undo failed: server restarting', status: 502 } });

		await waitFor(() => {
			expect(screen.getByText('Undo failed: server restarting')).toBeInTheDocument();
			expect(screen.getByText('Meeting')).toBeInTheDocument();
			expect(screen.getByText('Undo')).toBeInTheDocument();
		});
	});

	it('removes event from list after successful undo', async () => {
		const user = userEvent.setup();
		const now = new Date();
		mockFetchActivityEvents.mockResolvedValue({
			data: [
				{
					id: 'evt-1',
					title: 'Meeting',
					status: 'approved',
					updated_at: now.toISOString(),
					event_sources: []
				}
			],
			count: 1,
			error: null
		});

		render(HistoryPage);

		await waitFor(() => {
			expect(screen.getByText('Undo')).toBeInTheDocument();
		});

		await user.click(screen.getByText('Undo'));

		await waitFor(() => {
			expect(screen.queryByText('Meeting')).not.toBeInTheDocument();
		});
	});
});
