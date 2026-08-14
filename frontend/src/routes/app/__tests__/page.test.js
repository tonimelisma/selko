// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';

// Mock fetch integrations
const mockFetchIntegrations = vi.fn();
const mockFetchPendingEventsWithSources = vi.fn();
const mockUpdateEventStatus = vi.fn();
const mockLiveUpdateCallbacks = new Map();

vi.mock('$lib/services/integrations.js', () => ({
	fetchIntegrations: (...args) => mockFetchIntegrations(...args),
	fetchCalendarRecovery: () => Promise.resolve({ data: null, error: null })
}));

vi.mock('$lib/services/events.js', () => ({
	fetchPendingEventsWithSources: (...args) => mockFetchPendingEventsWithSources(...args),
	updateEventStatus: (...args) => mockUpdateEventStatus(...args)
}));

vi.mock('$lib/live-updates.js', () => ({
	subscribe: (resource, callback) => {
		if (!mockLiveUpdateCallbacks.has(resource)) mockLiveUpdateCallbacks.set(resource, new Set());
		mockLiveUpdateCallbacks.get(resource).add(callback);
		return () => mockLiveUpdateCallbacks.get(resource)?.delete(callback);
	}
}));

async function emitLiveUpdate(resource) {
	const callbacks = [...(mockLiveUpdateCallbacks.get(resource) || [])];
	await Promise.all(callbacks.map((callback) => callback({ resource, operation: 'UPDATE' })));
}

const mockCreateSenderRule = vi.fn();
const mockIgnoreSenderRetroactive = vi.fn();

vi.mock('$lib/services/sender-rules.js', () => ({
	createSenderRule: (...args) => mockCreateSenderRule(...args),
	ignoreSenderRetroactive: (...args) => mockIgnoreSenderRetroactive(...args)
}));

const mockSyncEventToCalendar = vi.fn();
const mockInitiateGmailAuth = vi.fn();
const mockInitiateOutlookAuth = vi.fn();
const mockInitiateCalendarAuth = vi.fn();
const mockUndoHistoryEvent = vi.fn();

vi.mock('$lib/api/backend.js', () => ({
	syncEventToCalendar: (...args) => mockSyncEventToCalendar(...args),
	initiateGmailAuth: (...args) => mockInitiateGmailAuth(...args),
	initiateOutlookAuth: (...args) => mockInitiateOutlookAuth(...args),
	initiateCalendarAuth: (...args) => mockInitiateCalendarAuth(...args),
	applyEventChange: vi.fn().mockResolvedValue({ data: { status: 'approved' }, error: null }),
	rejectEventChange: vi.fn().mockResolvedValue({ data: { status: 'deleted' }, error: null }),
	undoHistoryEvent: (...args) => mockUndoHistoryEvent(...args)
}));

// Import after mocking
const { default: AppPage } = await import('../+page.svelte');

describe('Review Queue (App Page)', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockLiveUpdateCallbacks.clear();
		mockSyncEventToCalendar.mockResolvedValue({ data: null, error: null });
		mockFetchPendingEventsWithSources.mockResolvedValue({ data: [], error: null });
		mockUndoHistoryEvent.mockResolvedValue({ data: { event_id: 'evt-1', status: 'pending_review' }, error: null });
		mockUpdateEventStatus.mockResolvedValue({ data: null, error: null });
		mockCreateSenderRule.mockResolvedValue({ data: { id: 'rule-1' }, error: null });
		mockIgnoreSenderRetroactive.mockResolvedValue({
			data: { rejected_new: 1, discarded_changes: 0 },
			error: null
		});
	});

	it('shows loading spinner while fetching integrations', () => {
		mockFetchIntegrations.mockReturnValue(new Promise(() => {}));

		render(AppPage);

		expect(document.querySelector('.loading.loading-spinner')).toBeTruthy();
	});

	it('shows setup mode when integrations not connected', async () => {
		mockFetchIntegrations.mockResolvedValue({
			data: [],
			error: null
		});

		render(AppPage);

		await waitFor(() => {
			expect(screen.getByText('Welcome to Selko')).toBeInTheDocument();
		});
	});

	it('keeps the review surface and requests calendar recovery when only gmail is connected', async () => {
		mockFetchIntegrations.mockResolvedValue({
			data: [
				{ id: '1', provider: 'gmail', status: 'active', provider_email: 'test@gmail.com' }
			],
			error: null
		});

		render(AppPage);

		await waitFor(() => {
			expect(
				screen.getByRole('heading', { name: 'Reconnect Google Calendar' })
			).toBeInTheDocument();
			expect(screen.getByText('All caught up!')).toBeInTheDocument();
		});
	});

	it('treats active Outlook as a connected email provider', async () => {
		mockFetchIntegrations.mockResolvedValue({
			data: [
				{ id: '1', provider: 'gmail', status: 'expired' },
				{ id: '2', provider: 'outlook', status: 'active' },
				{ id: '3', provider: 'google_calendar', status: 'active' }
			],
			error: null
		});
		mockFetchPendingEventsWithSources.mockResolvedValue({ data: [], error: null });

		render(AppPage);

		await waitFor(() => {
			expect(screen.getByText('All caught up!')).toBeInTheDocument();
			expect(screen.getByText('Connection needs attention')).toBeInTheDocument();
			expect(screen.queryByText('Reconnect an email account')).not.toBeInTheDocument();
		});
	});

	it('keeps suggestions readable and disables acceptance when calendar OAuth is expired', async () => {
		mockFetchIntegrations.mockResolvedValue({
			data: [
				{ id: '1', provider: 'outlook', status: 'active' },
				{ id: '2', provider: 'google_calendar', status: 'expired' }
			],
			error: null
		});
		mockFetchPendingEventsWithSources.mockResolvedValue({
			data: [
				{
					id: 'evt-expired-calendar',
					title: 'Readable suggestion',
					start_datetime: '2026-07-29T14:00:00',
					status: 'pending_review',
					event_sources: []
				}
			],
			error: null
		});

		render(AppPage);

		await waitFor(() => expect(screen.getByText('Readable suggestion')).toBeInTheDocument());
		expect(
			screen.getByRole('button', {
				name: /^Accept Readable suggestion\./
			})
		).toBeDisabled();
		expect(screen.getByRole('button', { name: /reject readable suggestion/i })).toBeEnabled();
		expect(screen.getByRole('button', { name: 'Reconnect Google Calendar' })).toBeEnabled();
	});

	it('shows empty state when fully connected with no events', async () => {
		mockFetchIntegrations.mockResolvedValue({
			data: [
				{ id: '1', provider: 'gmail', status: 'active' },
				{ id: '2', provider: 'google_calendar', status: 'active' }
			],
			error: null
		});
		mockFetchPendingEventsWithSources.mockResolvedValue({
			data: [],
			error: null
		});

		render(AppPage);

		await waitFor(() => {
			expect(screen.getByText('All caught up!')).toBeInTheDocument();
		});
	});

	it('shows events grouped by sender when connected', async () => {
		mockFetchIntegrations.mockResolvedValue({
			data: [
				{ id: '1', provider: 'gmail', status: 'active' },
				{ id: '2', provider: 'google_calendar', status: 'active' }
			],
			error: null
		});
		mockFetchPendingEventsWithSources.mockResolvedValue({
			data: [
				{
					id: 'evt-1',
					title: 'Team Meeting',
					start_datetime: '2024-01-20T14:00:00Z',
					status: 'pending_review',
					event_sources: [
						{
							emails: {
								id: 'email-1',
								subject: 'Meeting Invite',
								from_email: 'boss@company.com',
								from_name: 'Boss',
								date_sent: '2024-01-15T10:00:00Z'
							}
						}
					]
				}
			],
			error: null
		});

		render(AppPage);

		await waitFor(() => {
			expect(screen.getByText('Team Meeting')).toBeInTheDocument();
			expect(screen.getByText('Boss')).toBeInTheDocument();
		});
	});

	it('keeps the current event list visible during a background integration refresh', async () => {
		const integrations = [
			{ id: '1', provider: 'gmail', status: 'active' },
			{ id: '2', provider: 'google_calendar', status: 'active' }
		];
		mockFetchIntegrations.mockResolvedValueOnce({ data: integrations, error: null });
		mockFetchPendingEventsWithSources.mockResolvedValue({
			data: [
				{
					id: 'evt-stable',
					title: 'Stable during refresh',
					start_datetime: '2027-01-20T14:00:00Z',
					status: 'pending_review',
					event_sources: []
				}
			],
			error: null
		});

		render(AppPage);
		await waitFor(() => expect(screen.getByText('Stable during refresh')).toBeInTheDocument());

		mockFetchIntegrations.mockReturnValueOnce(new Promise(() => {}));
		void emitLiveUpdate('integrations');

		expect(screen.getByText('Stable during refresh')).toBeInTheDocument();
		expect(document.querySelector('.loading.loading-spinner')).toBeNull();
		expect(mockFetchPendingEventsWithSources).toHaveBeenCalledTimes(1);
	});

	it('coalesces event and event-source invalidations into one list refresh', async () => {
		mockFetchIntegrations.mockResolvedValue({
			data: [
				{ id: '1', provider: 'gmail', status: 'active' },
				{ id: '2', provider: 'google_calendar', status: 'active' }
			],
			error: null
		});
		mockFetchPendingEventsWithSources.mockResolvedValue({ data: [], error: null });

		render(AppPage);
		await waitFor(() => expect(screen.getByText('All caught up!')).toBeInTheDocument());
		expect(mockFetchPendingEventsWithSources).toHaveBeenCalledTimes(1);

		vi.useFakeTimers();
		void emitLiveUpdate('events');
		void emitLiveUpdate('event_sources');
		await vi.advanceTimersByTimeAsync(150);
		expect(mockFetchPendingEventsWithSources).toHaveBeenCalledTimes(2);
		vi.useRealTimers();
	});

	it('shows error when integration fetch fails', async () => {
		mockFetchIntegrations.mockResolvedValue({
			data: [],
			error: { message: 'Network error', code: 'NETWORK_ERROR' }
		});

		render(AppPage);

		await waitFor(() => {
			expect(screen.getByText('Network error')).toBeInTheDocument();
			expect(screen.queryByText('Welcome to Selko')).not.toBeInTheDocument();
		});
	});

	it('removes event from list on approve', async () => {
		const user = userEvent.setup();

		mockFetchIntegrations.mockResolvedValue({
			data: [
				{ id: '1', provider: 'gmail', status: 'active' },
				{ id: '2', provider: 'google_calendar', status: 'active' }
			],
			error: null
		});
		mockFetchPendingEventsWithSources.mockResolvedValue({
			data: [
				{
					id: 'evt-1',
					title: 'Team Meeting',
					start_datetime: '2024-01-20T14:00:00Z',
					status: 'pending_review',
					event_sources: [
						{
							emails: {
								id: 'email-1',
								subject: 'Meeting Invite',
								from_email: 'boss@company.com',
								from_name: 'Boss',
								date_sent: '2024-01-15T10:00:00Z'
							}
						}
					]
				}
			],
			error: null
		});

		render(AppPage);

		await waitFor(() => {
			expect(screen.getByText('Team Meeting')).toBeInTheDocument();
		});

		const approveBtn = screen.getByRole('button', { name: /accept team meeting/i });
		await user.click(approveBtn);

		await waitFor(() => {
			expect(mockUpdateEventStatus).toHaveBeenCalledWith('evt-1', 'approved');
			expect(screen.queryByText('Team Meeting')).not.toBeInTheDocument();
		});
		expect(mockSyncEventToCalendar).not.toHaveBeenCalled();
	});

	it('removes event from list on reject', async () => {
		const user = userEvent.setup();

		mockFetchIntegrations.mockResolvedValue({
			data: [
				{ id: '1', provider: 'gmail', status: 'active' },
				{ id: '2', provider: 'google_calendar', status: 'active' }
			],
			error: null
		});
		mockFetchPendingEventsWithSources.mockResolvedValue({
			data: [
				{
					id: 'evt-1',
					title: 'Team Meeting',
					start_datetime: '2024-01-20T14:00:00Z',
					status: 'pending_review',
					event_sources: [
						{
							emails: {
								id: 'email-1',
								subject: 'Meeting Invite',
								from_email: 'boss@company.com',
								from_name: 'Boss',
								date_sent: '2024-01-15T10:00:00Z'
							}
						}
					]
				}
			],
			error: null
		});

		render(AppPage);

		await waitFor(() => {
			expect(screen.getByText('Team Meeting')).toBeInTheDocument();
		});

		const rejectBtn = screen.getByRole('button', { name: /reject team meeting/i });
		await user.click(rejectBtn);

		await waitFor(() => {
			expect(mockUpdateEventStatus).toHaveBeenCalledWith('evt-1', 'rejected');
			expect(screen.queryByText('Team Meeting')).not.toBeInTheDocument();
		});
	});

	it('keeps a sender group in place when its earliest event is rejected', async () => {
		const user = userEvent.setup();
		mockFetchIntegrations.mockResolvedValue({
			data: [
				{ id: '1', provider: 'gmail', status: 'active' },
				{ id: '2', provider: 'google_calendar', status: 'active' }
			],
			error: null
		});
		const source = (id, fromEmail, fromName) => [
			{
				emails: {
					id,
					subject: id,
					from_email: fromEmail,
					from_name: fromName,
					date_sent: '2026-07-13T10:00:00Z'
				}
			}
		];
		mockFetchPendingEventsWithSources.mockResolvedValue({
			data: [
				{
					id: 'grantmaking',
					title: 'Grantmaking.ai',
					start_datetime: '2026-07-13T00:00:00Z',
					status: 'pending_review',
					event_sources: source('email-1', 'astral@example.com', 'Astral')
				},
				{
					id: 'intervening',
					title: 'Intervening Event',
					start_datetime: '2026-07-28T00:00:00Z',
					status: 'pending_review',
					event_sources: source('email-2', 'other@example.com', 'Other')
				},
				{
					id: 'mats',
					title: 'MATS Research Fellowship',
					start_datetime: '2026-09-28T00:00:00Z',
					status: 'pending_review',
					event_sources: source('email-3', 'astral@example.com', 'Astral')
				}
			],
			error: null
		});

		render(AppPage);
		await waitFor(() => expect(screen.getByText('Grantmaking.ai')).toBeInTheDocument());

		const reviewSurface = document.querySelector('.review-surface');
		expect(reviewSurface).toHaveClass('max-w-[var(--review-max-width)]');
		const senderGroups = document.querySelectorAll('.review-sender-groups');
		expect(senderGroups).toHaveLength(1);
		expect(senderGroups[0]).toHaveClass('grid');
		expect(senderGroups[0]).not.toHaveClass('lg:grid-cols-2');

		const grantmakingCard = screen.getByText('Grantmaking.ai').closest('div.border-b');
		const rejectButton = grantmakingCard.querySelector('button.peer-action-destructive');
		await user.click(rejectButton);

		await waitFor(() => {
			expect(mockUpdateEventStatus).toHaveBeenCalledWith('grantmaking', 'rejected');
			expect(screen.queryByText('Grantmaking.ai')).not.toBeInTheDocument();
		});
		const titles = screen.getAllByRole('heading', { level: 4 }).map((heading) => heading.textContent);
		expect(titles).toEqual(['MATS Research Fellowship', 'Intervening Event']);
	});

	it('shows sender menu for single-event groups', async () => {
		mockFetchIntegrations.mockResolvedValue({
			data: [
				{ id: '1', provider: 'gmail', status: 'active' },
				{ id: '2', provider: 'google_calendar', status: 'active' }
			],
			error: null
		});
		mockFetchPendingEventsWithSources.mockResolvedValue({
			data: [
				{
					id: 'evt-1',
					title: 'Solo Event',
					start_datetime: '2024-01-20T14:00:00Z',
					status: 'pending_review',
					event_sources: [
						{
							emails: {
								id: 'email-1',
								subject: 'Invite',
								from_email: 'sender@example.com',
								from_name: 'Sender',
								date_sent: '2024-01-15T10:00:00Z'
							}
						}
					]
				}
			],
			error: null
		});

		render(AppPage);

		await waitFor(() => {
			expect(screen.getByText('Sender')).toBeInTheDocument();
			// Menu button should be visible even for single event
			expect(screen.getByRole('button', { name: /actions for/i })).toBeInTheDocument();
		});
	});

	it('creates ignore sender rule and rejects events', async () => {
		const user = userEvent.setup();

		mockFetchIntegrations.mockResolvedValue({
			data: [
				{ id: '1', provider: 'gmail', status: 'active' },
				{ id: '2', provider: 'google_calendar', status: 'active' }
			],
			error: null
		});
		mockFetchPendingEventsWithSources.mockResolvedValue({
			data: [
				{
					id: 'evt-1',
					title: 'Spam Event',
					start_datetime: '2024-01-20T14:00:00Z',
					status: 'pending_review',
					event_sources: [
						{
							emails: {
								id: 'email-1',
								subject: 'Spam',
								from_email: 'spammer@example.com',
								from_name: 'Spammer',
								date_sent: '2024-01-15T10:00:00Z'
							}
						}
					]
				}
			],
			error: null
		});

		render(AppPage);

		await waitFor(() => {
			expect(screen.getByText('Spam Event')).toBeInTheDocument();
		});

		await user.click(screen.getByRole('button', { name: /actions for/i }));
		await user.click(screen.getByText('Ignore sender'));

		await waitFor(() => {
			expect(mockIgnoreSenderRetroactive).toHaveBeenCalledWith('spammer@example.com');
			// Ignoring is retroactive + atomic server-side; the client just refetches
			// both lanes rather than looping over one lane's events itself.
			expect(mockFetchPendingEventsWithSources).toHaveBeenCalledTimes(2);
			expect(mockCreateSenderRule).not.toHaveBeenCalled();
			expect(mockUpdateEventStatus).not.toHaveBeenCalled();
		});
	});

	it('does not call the ignore rpc for pseudo (non-email) senders', async () => {
		const user = userEvent.setup();

		mockFetchIntegrations.mockResolvedValue({
			data: [
				{ id: '1', provider: 'gmail', status: 'active' },
				{ id: '2', provider: 'google_calendar', status: 'active' }
			],
			error: null
		});
		mockFetchPendingEventsWithSources.mockResolvedValue({
			data: [
				{
					id: 'evt-1',
					title: 'Calendar Event',
					start_datetime: '2024-01-20T14:00:00Z',
					status: 'pending_review',
					event_sources: [{ source_origin: 'google_calendar' }]
				}
			],
			error: null
		});

		render(AppPage);

		await waitFor(() => {
			expect(screen.getByText('Calendar Event')).toBeInTheDocument();
		});

		await user.click(screen.getByRole('button', { name: /actions for/i }));
		await user.click(screen.getByText('Ignore sender'));

		await waitFor(() => {
			expect(screen.getByText(/can't be ignored/i)).toBeInTheDocument();
		});
		expect(mockIgnoreSenderRetroactive).not.toHaveBeenCalled();
	});

	it('creates auto-approve sender rule and approves events', async () => {
		const user = userEvent.setup();

		mockFetchIntegrations.mockResolvedValue({
			data: [
				{ id: '1', provider: 'gmail', status: 'active' },
				{ id: '2', provider: 'google_calendar', status: 'active' }
			],
			error: null
		});
		mockFetchPendingEventsWithSources.mockResolvedValue({
			data: [
				{
					id: 'evt-1',
					title: 'Trusted Event',
					start_datetime: '2024-01-20T14:00:00Z',
					status: 'pending_review',
					event_sources: [
						{
							emails: {
								id: 'email-1',
								subject: 'Meeting',
								from_email: 'boss@company.com',
								from_name: 'Boss',
								date_sent: '2024-01-15T10:00:00Z'
							}
						}
					]
				}
			],
			error: null
		});

		render(AppPage);

		await waitFor(() => {
			expect(screen.getByText('Trusted Event')).toBeInTheDocument();
		});

		await user.click(screen.getByRole('button', { name: /actions for/i }));
		await user.click(screen.getByText('Auto-approve sender'));

		await waitFor(() => {
			expect(mockCreateSenderRule).toHaveBeenCalledWith({
				sender_email: 'boss@company.com',
				action: 'auto_approve'
			});
			expect(mockUpdateEventStatus).toHaveBeenCalledWith('evt-1', 'approved');
		});
	});

	it('hides sender rule buttons for photo source groups', async () => {
		mockFetchIntegrations.mockResolvedValue({
			data: [
				{ id: '1', provider: 'gmail', status: 'active' },
				{ id: '2', provider: 'google_calendar', status: 'active' }
			],
			error: null
		});
		mockFetchPendingEventsWithSources.mockResolvedValue({
			data: [
				{
					id: 'evt-photo-1',
					title: 'Birthday Party',
					start_datetime: '2024-01-20T14:00:00Z',
					status: 'pending_review',
					event_sources: [
						{
							source_origin: 'google_photos'
						}
					]
				}
			],
			error: null
		});

		render(AppPage);

		await waitFor(() => {
			expect(screen.getByText('Birthday Party')).toBeInTheDocument();
		});

		// Sender rule buttons should not be present for photo sources
		expect(screen.queryByText('Ignore sender')).not.toBeInTheDocument();
		expect(screen.queryByText('Auto-approve sender')).not.toBeInTheDocument();
	});

	it('optimistically removes event from queue while approve is in flight', async () => {
		const user = userEvent.setup();

		// Make updateEventStatus hang so we can assert optimistic UI
		let resolveUpdate;
		mockUpdateEventStatus.mockImplementation(
			() => new Promise((resolve) => { resolveUpdate = resolve; })
		);

		mockFetchIntegrations.mockResolvedValue({
			data: [
				{ id: '1', provider: 'gmail', status: 'active' },
				{ id: '2', provider: 'google_calendar', status: 'active' }
			],
			error: null
		});
		mockFetchPendingEventsWithSources.mockResolvedValue({
			data: [
				{
					id: 'evt-1',
					title: 'Processing Test',
					start_datetime: '2024-01-20T14:00:00Z',
					status: 'pending_review',
					event_sources: [
						{
							emails: {
								id: 'email-1',
								subject: 'Test',
								from_email: 'test@example.com',
								from_name: 'Test',
								date_sent: '2024-01-15T10:00:00Z'
							}
						}
					]
				}
			],
			error: null
		});

		render(AppPage);

		await waitFor(() => {
			expect(screen.getByText('Processing Test')).toBeInTheDocument();
		});

		const approveBtn = screen.getByRole('button', { name: /accept processing test/i });
		expect(approveBtn).not.toBeDisabled();

		await user.click(approveBtn);

		await waitFor(() => {
			expect(screen.queryByText('Processing Test')).not.toBeInTheDocument();
		});

		resolveUpdate({ data: null, error: null });
	});

	it('shows undo toast after reject and restores event on undo', async () => {
		const user = userEvent.setup();

		mockFetchIntegrations.mockResolvedValue({
			data: [
				{ id: '1', provider: 'gmail', status: 'active' },
				{ id: '2', provider: 'google_calendar', status: 'active' }
			],
			error: null
		});
		mockFetchPendingEventsWithSources.mockResolvedValue({
			data: [
				{
					id: 'evt-undo-1',
					title: 'Undo Test',
					start_datetime: '2024-01-20T14:00:00Z',
					status: 'pending_review',
					event_sources: [
						{
							emails: {
								id: 'email-1',
								subject: 'Test',
								from_email: 'test@example.com',
								from_name: 'Test',
								date_sent: '2024-01-15T10:00:00Z'
							}
						}
					]
				}
			],
			error: null
		});
		mockUpdateEventStatus.mockResolvedValue({ data: { id: 'evt-undo-1', status: 'rejected' }, error: null });

		render(AppPage);

		await waitFor(() => {
			expect(screen.getByText('Undo Test')).toBeInTheDocument();
		});

		const rejectBtn = screen.getByRole('button', { name: /reject undo test/i });
		await user.click(rejectBtn);

		await waitFor(() => {
			expect(screen.queryByText('Undo Test')).not.toBeInTheDocument();
		});
		// Undo toast should appear
		expect(screen.getByText('Event rejected')).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Undo' })).toBeInTheDocument();

		// Click undo
		await user.click(screen.getByRole('button', { name: 'Undo' }));

		await waitFor(() => {
			expect(mockUndoHistoryEvent).toHaveBeenCalledWith('evt-undo-1');
		});
		// After undo, event should be restored (optimistically and then via reload)
		await waitFor(() => {
			expect(screen.getByText('Undo Test')).toBeInTheDocument();
		});
	});

	it('shows count and batches multiple rejects into one undo toast', async () => {
		const user = userEvent.setup();

		mockFetchIntegrations.mockResolvedValue({
			data: [
				{ id: '1', provider: 'gmail', status: 'active' },
				{ id: '2', provider: 'google_calendar', status: 'active' }
			],
			error: null
		});
		mockFetchPendingEventsWithSources.mockResolvedValue({
			data: [
				{
					id: 'evt-batch-1',
					title: 'Batch One',
					start_datetime: '2024-01-20T14:00:00Z',
					status: 'pending_review',
					event_sources: [{ emails: { id: 'e1', subject: 'S', from_email: 'a@b.com', from_name: 'A', date_sent: '2024-01-15T10:00:00Z' } }]
				},
				{
					id: 'evt-batch-2',
					title: 'Batch Two',
					start_datetime: '2024-01-20T15:00:00Z',
					status: 'pending_review',
					event_sources: [{ emails: { id: 'e2', subject: 'S', from_email: 'a@b.com', from_name: 'A', date_sent: '2024-01-15T10:00:00Z' } }]
				}
			],
			error: null
		});

		render(AppPage);

		await waitFor(() => {
			expect(screen.getByText('Batch One')).toBeInTheDocument();
			expect(screen.getByText('Batch Two')).toBeInTheDocument();
		});

		const rejectButtons = screen.getAllByRole('button', { name: /reject batch/i });
		// Reject first event
		await user.click(rejectButtons[0]);
		await waitFor(() => expect(screen.queryByText('Batch One')).not.toBeInTheDocument());
		expect(screen.getByText('Event rejected')).toBeInTheDocument();

		// Reject second event - should batch into same toast with count
		await user.click(rejectButtons[1] || screen.getByRole('button', { name: /reject batch two/i }));
		await waitFor(() => expect(screen.queryByText('Batch Two')).not.toBeInTheDocument());
		await waitFor(() => expect(screen.getByText('2 events rejected')).toBeInTheDocument());

		await user.click(screen.getByRole('button', { name: 'Undo' }));
		await waitFor(() => expect(mockUndoHistoryEvent).toHaveBeenCalledTimes(2));
	});

});
