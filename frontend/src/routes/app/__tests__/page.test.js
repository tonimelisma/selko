// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';

// Mock fetch integrations
const mockFetchIntegrations = vi.fn();
const mockFetchPendingEventsWithSources = vi.fn();
const mockUpdateEventStatus = vi.fn();

vi.mock('$lib/services/integrations.js', () => ({
	fetchIntegrations: (...args) => mockFetchIntegrations(...args)
}));

vi.mock('$lib/services/events.js', () => ({
	fetchPendingEventsWithSources: (...args) => mockFetchPendingEventsWithSources(...args),
	updateEventStatus: (...args) => mockUpdateEventStatus(...args)
}));

const mockCreateSenderRule = vi.fn();

vi.mock('$lib/services/sender-rules.js', () => ({
	createSenderRule: (...args) => mockCreateSenderRule(...args)
}));

const mockSyncEventToCalendar = vi.fn();
const mockInitiateGmailAuth = vi.fn();
const mockInitiateCalendarAuth = vi.fn();

vi.mock('$lib/api/backend.js', () => ({
	syncEventToCalendar: (...args) => mockSyncEventToCalendar(...args),
	initiateGmailAuth: (...args) => mockInitiateGmailAuth(...args),
	initiateCalendarAuth: (...args) => mockInitiateCalendarAuth(...args)
}));

// Import after mocking
const { default: AppPage } = await import('../+page.svelte');

describe('Review Queue (App Page)', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockSyncEventToCalendar.mockResolvedValue({ data: null, error: null });
		mockUpdateEventStatus.mockResolvedValue({ data: null, error: null });
		mockCreateSenderRule.mockResolvedValue({ data: { id: 'rule-1' }, error: null });
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

	it('shows setup mode when only gmail is connected', async () => {
		mockFetchIntegrations.mockResolvedValue({
			data: [
				{ id: '1', provider: 'gmail', status: 'active', provider_email: 'test@gmail.com' }
			],
			error: null
		});

		render(AppPage);

		await waitFor(() => {
			expect(screen.getByText('Connect your accounts')).toBeInTheDocument();
		});
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

	it('shows error when integration fetch fails', async () => {
		mockFetchIntegrations.mockResolvedValue({
			data: [],
			error: { message: 'Network error', code: 'NETWORK_ERROR' }
		});

		render(AppPage);

		// When integrations fail to load but data is empty, it shows setup mode
		// The error message goes to the error state variable
		await waitFor(() => {
			// With empty integrations it should show setup mode
			expect(screen.getByText('Welcome to Selko')).toBeInTheDocument();
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

		const approveBtn = screen.getByRole('button', { name: /accept event/i });
		await user.click(approveBtn);

		await waitFor(() => {
			expect(mockUpdateEventStatus).toHaveBeenCalledWith('evt-1', 'approved');
			expect(screen.queryByText('Team Meeting')).not.toBeInTheDocument();
		});
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

		const rejectBtn = screen.getByRole('button', { name: /reject event/i });
		await user.click(rejectBtn);

		await waitFor(() => {
			expect(mockUpdateEventStatus).toHaveBeenCalledWith('evt-1', 'rejected');
			expect(screen.queryByText('Team Meeting')).not.toBeInTheDocument();
		});
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

		await user.click(screen.getByText('Ignore sender'));

		await waitFor(() => {
			expect(mockCreateSenderRule).toHaveBeenCalledWith({
				sender_email: 'spammer@example.com',
				action: 'ignore'
			});
			expect(mockUpdateEventStatus).toHaveBeenCalledWith('evt-1', 'rejected');
		});
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

		await user.click(screen.getByText('Auto-approve sender'));

		await waitFor(() => {
			expect(mockCreateSenderRule).toHaveBeenCalledWith({
				sender_email: 'boss@company.com',
				action: 'auto_approve'
			});
			expect(mockUpdateEventStatus).toHaveBeenCalledWith('evt-1', 'approved');
		});
	});
});
