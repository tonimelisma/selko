// @ts-nocheck
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';
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
const mockFetchEmailHistory = vi.fn();
const mockFetchEmailProcessingState = vi.fn();
const mockQueueEmailReprocess = vi.fn();

vi.mock('$lib/services/email-history.js', () => ({
	fetchEmailHistory: (...args) => mockFetchEmailHistory(...args),
	fetchEmailProcessingState: (...args) => mockFetchEmailProcessingState(...args),
	queueEmailReprocess: (...args) => mockQueueEmailReprocess(...args)
}));

vi.mock('$lib/api/backend.js', () => ({
	syncEventToCalendar: (...args) => mockSyncEventToCalendar(...args),
	undoHistoryEvent: (...args) => mockUndoHistoryEvent(...args)
}));

const { default: HistoryPage } = await import('../+page.svelte');

describe('History Page', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockFetchEmailHistory.mockResolvedValue({ data: [], count: 0, error: null });
		mockFetchEmailProcessingState.mockResolvedValue({
			data: { processing_status: 'processed', processing_outcome: 'event_matched' },
			error: null
		});
		mockQueueEmailReprocess.mockResolvedValue({
			data: { id: 'email-1', processing_status: 'pending' },
			error: null
		});
		mockUpdateEventStatus.mockResolvedValue({ data: null, error: null });
		mockSyncEventToCalendar.mockResolvedValue({ data: null, error: null });
		mockUndoHistoryEvent.mockResolvedValue({ data: { event_id: 'evt-1', status: 'pending_review' }, error: null });
	});

	afterEach(() => {
		vi.useRealTimers();
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

		expect(mockUndoHistoryEvent).toHaveBeenCalledWith('evt-1', {});
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

	it('shows Force Undo when calendar diverged', async () => {
		const user = userEvent.setup();
		const now = new Date();
		mockFetchActivityEvents.mockResolvedValue({
			data: [
				{
					id: 'evt-1',
					title: 'Bike Fest',
					status: 'synced',
					updated_at: now.toISOString(),
					event_sources: []
				}
			],
			count: 1,
			error: null
		});
		mockUndoHistoryEvent.mockResolvedValueOnce({
			data: null,
			error: {
				message: 'This event was edited in Google Calendar after Selko synced it (title).',
				status: 409,
				code: 'CALENDAR_DIVERGED'
			}
		});

		render(HistoryPage);

		await waitFor(() => {
			expect(screen.getByText('Undo')).toBeInTheDocument();
		});

		await user.click(screen.getByText('Undo'));

		await waitFor(() => {
			expect(screen.getByText(/edited in Google Calendar/i)).toBeInTheDocument();
			expect(screen.getByText('Force Undo')).toBeInTheDocument();
			expect(screen.getByText('Bike Fest')).toBeInTheDocument();
		});

		mockUndoHistoryEvent.mockResolvedValueOnce({
			data: { event_id: 'evt-1', status: 'pending_review' },
			error: null
		});

		await user.click(screen.getByText('Force Undo'));

		await waitFor(() => {
			expect(mockUndoHistoryEvent).toHaveBeenLastCalledWith('evt-1', { force: true });
			expect(screen.queryByText('Bike Fest')).not.toBeInTheDocument();
		});
	});

	it('shows email rows for processed, failed, matched, and pending outcomes', async () => {
		mockFetchEmailHistory.mockResolvedValue({
			data: [
				{ id: 'email-1', subject: 'Matched', email_provider: 'gmail', processing_status: 'processed', processing_outcome: 'event_matched', date_sent: new Date().toISOString() },
				{ id: 'email-2', subject: 'Failed', email_provider: 'outlook', processing_status: 'failed', processing_error: 'Provider failed', date_sent: new Date().toISOString() },
				{ id: 'email-3', subject: 'No event', email_provider: 'gmail', processing_status: 'processed', processing_outcome: 'no_event', date_sent: new Date().toISOString() }
			],
			count: 3,
			error: null
		});

		render(HistoryPage);

		await waitFor(() => {
			expect(screen.getByText('Matched')).toBeInTheDocument();
			expect(screen.getByText('Existing event matched')).toBeInTheDocument();
			expect(screen.getAllByText('Failed')).toHaveLength(2);
			expect(screen.getByText('No event found')).toBeInTheDocument();
		});
	});

	it('polls a reprocessed email until it reaches processed', async () => {
		const user = userEvent.setup();
		mockFetchEmailHistory.mockResolvedValueOnce({
			data: [{ id: 'email-1', subject: 'Retry me', email_provider: 'gmail', processing_status: 'failed', processing_outcome: null, date_sent: new Date().toISOString() }],
			count: 1,
			error: null
		}).mockResolvedValueOnce({
			data: [{ id: 'email-1', subject: 'Retry me', email_provider: 'gmail', processing_status: 'processed', processing_outcome: 'event_matched', date_sent: new Date().toISOString() }],
			count: 1,
			error: null
		});
		mockFetchEmailProcessingState
			.mockResolvedValueOnce({ data: { id: 'email-1', processing_status: 'processing' }, error: null })
			.mockResolvedValueOnce({ data: { id: 'email-1', processing_status: 'processed', processing_outcome: 'event_matched' }, error: null });

		render(HistoryPage);
		await waitFor(() => expect(screen.getByText('Retry me')).toBeInTheDocument());
		await user.click(screen.getByRole('button', { name: 'Reprocess' }));

		await waitFor(() => expect(mockQueueEmailReprocess).toHaveBeenCalledWith('email-1'));
		await waitFor(() => expect(screen.getByText('Existing event matched')).toBeInTheDocument(), { timeout: 3000 });
		expect(mockFetchEmailHistory).toHaveBeenLastCalledWith({ limit: 20, offset: 0 });
		expect(screen.getByRole('button', { name: 'Reprocess' })).not.toBeDisabled();
	});

	it('shows a terminal failed state after reprocessing fails', async () => {
		const user = userEvent.setup();
		mockFetchEmailHistory.mockResolvedValue({
			data: [{ id: 'email-1', subject: 'Fails again', email_provider: 'gmail', processing_status: 'failed', date_sent: new Date().toISOString() }],
			count: 1,
			error: null
		});
		mockFetchEmailProcessingState.mockResolvedValue({
			data: { id: 'email-1', processing_status: 'failed', processing_error: 'Extraction failed' },
			error: null
		});

		render(HistoryPage);
		await waitFor(() => expect(screen.getByText('Fails again')).toBeInTheDocument());
		await user.click(screen.getByRole('button', { name: 'Reprocess' }));

		await waitFor(() => {
			expect(screen.getByText('Failed')).toBeInTheDocument();
			expect(screen.getByRole('button', { name: 'Reprocess' })).not.toBeDisabled();
		});
	});

	it('prevents repeated reprocess clicks while the current attempt is pending', async () => {
		const user = userEvent.setup();
		mockFetchEmailHistory.mockResolvedValue({
			data: [{ id: 'email-1', subject: 'Only once', email_provider: 'gmail', processing_status: 'failed', date_sent: new Date().toISOString() }],
			count: 1,
			error: null
		});
		mockQueueEmailReprocess.mockResolvedValue({ data: { id: 'email-1', processing_status: 'pending' }, error: null });
		mockFetchEmailProcessingState.mockReturnValue(new Promise(() => {}));

		render(HistoryPage);
		await waitFor(() => expect(screen.getByText('Only once')).toBeInTheDocument());
		const button = screen.getByRole('button', { name: 'Reprocess' });
		await user.click(button);
		await waitFor(() => expect(button).toBeDisabled());
		await user.click(button);
		expect(mockQueueEmailReprocess).toHaveBeenCalledTimes(1);
	});

	it('stops polling and re-enables the action after a polling error', async () => {
		const user = userEvent.setup();
		mockFetchEmailHistory.mockResolvedValue({
			data: [{ id: 'email-1', subject: 'Polling error', email_provider: 'gmail', processing_status: 'failed', date_sent: new Date().toISOString() }],
			count: 1,
			error: null
		});
		mockFetchEmailProcessingState.mockResolvedValue({ data: null, error: { message: 'Status unavailable' } });

		render(HistoryPage);
		await waitFor(() => expect(screen.getByText('Polling error')).toBeInTheDocument());
		await user.click(screen.getByRole('button', { name: 'Reprocess' }));

		await waitFor(() => {
			expect(screen.getByText('Status unavailable')).toBeInTheDocument();
			expect(screen.getByRole('button', { name: 'Reprocess' })).not.toBeDisabled();
		});
	});

	it('stops polling at the bounded timeout', async () => {
		vi.useFakeTimers();
		const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
		mockFetchEmailHistory.mockResolvedValue({
			data: [{ id: 'email-1', subject: 'Polling timeout', email_provider: 'gmail', processing_status: 'failed', date_sent: new Date().toISOString() }],
			count: 1,
			error: null
		});
		mockFetchEmailProcessingState.mockResolvedValue({
			data: { id: 'email-1', processing_status: 'processing' },
			error: null
		});

		render(HistoryPage);
		await vi.waitFor(() => expect(screen.getByText('Polling timeout')).toBeInTheDocument());
		await user.click(screen.getByRole('button', { name: 'Reprocess' }));
		await vi.waitFor(() => expect(mockQueueEmailReprocess).toHaveBeenCalled());
		await vi.advanceTimersByTimeAsync(31_000);

		expect(screen.getByText(/Reprocessing is taking longer/)).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Reprocess' })).not.toBeDisabled();
	});

	it('loads more email history without duplicating rows', async () => {
		mockFetchEmailHistory
			.mockResolvedValueOnce({
				data: [{ id: 'email-1', subject: 'First page', email_provider: 'gmail', processing_status: 'processed', date_sent: new Date().toISOString() }],
				count: 2,
				error: null
			})
			.mockResolvedValueOnce({
				data: [{ id: 'email-1', subject: 'First page', email_provider: 'gmail', processing_status: 'processed', date_sent: new Date().toISOString() }, { id: 'email-2', subject: 'Second page', email_provider: 'outlook', processing_status: 'failed', date_sent: new Date().toISOString() }],
				count: 2,
				error: null
			});

		render(HistoryPage);
		await waitFor(() => expect(screen.getByText('Load More')).toBeInTheDocument());
		await userEvent.click(screen.getByText('Load More'));
		await waitFor(() => expect(screen.getByText('Second page')).toBeInTheDocument());
		expect(screen.getAllByText('First page')).toHaveLength(1);
	});
});
