// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { writable, readable } from 'svelte/store';

const mockUser = writable({ id: '123', email: 'test@example.com' });

vi.mock('$lib/stores.js', () => ({
	user: mockUser,
	loading: writable(false)
}));

const mockGoto = vi.fn();
vi.mock('$app/navigation', () => ({
	goto: (...args) => mockGoto(...args),
	page: readable({
		url: { pathname: '/app/settings' },
		params: {},
		route: { id: '' },
		status: 200,
		error: null,
		data: {},
		form: null
	}),
	navigating: readable(null),
	updated: { subscribe: readable(false).subscribe, check: vi.fn() }
}));

vi.mock('$app/stores', () => ({
	goto: (...args) => mockGoto(...args),
	page: readable({
		url: { pathname: '/app/settings' },
		params: {},
		route: { id: '' },
		status: 200,
		error: null,
		data: {},
		form: null
	}),
	navigating: readable(null),
	updated: { subscribe: readable(false).subscribe, check: vi.fn() }
}));

const mockSignOut = vi.fn();
const mockFetchIntegrations = vi.fn();
const mockDisconnectIntegration = vi.fn();
const mockGetCalendarSettings = vi.fn();
const mockUpdateCalendarSettings = vi.fn();
const mockListCalendars = vi.fn();
const mockInitiateGmailAuth = vi.fn();
const mockInitiateCalendarAuth = vi.fn();

vi.mock('$lib/supabase.js', () => ({
	supabase: {
		auth: { signOut: (...args) => mockSignOut(...args) }
	}
}));

vi.mock('$lib/services/integrations.js', () => ({
	fetchIntegrations: (...args) => mockFetchIntegrations(...args),
	disconnectIntegration: (...args) => mockDisconnectIntegration(...args)
}));

vi.mock('$lib/services/calendar-settings.js', () => ({
	getCalendarSettings: (...args) => mockGetCalendarSettings(...args),
	updateCalendarSettings: (...args) => mockUpdateCalendarSettings(...args)
}));

vi.mock('$lib/api/backend.js', () => ({
	listCalendars: (...args) => mockListCalendars(...args),
	initiateGmailAuth: (...args) => mockInitiateGmailAuth(...args),
	initiateOutlookAuth: vi.fn(),
	initiateCalendarAuth: (...args) => mockInitiateCalendarAuth(...args)
}));

const mockFetchSenderRules = vi.fn();
const mockCreateSenderRule = vi.fn();
const mockDeleteSenderRule = vi.fn();

const mockFetchEmailFolders = vi.fn();
const mockUpdateEmailFolder = vi.fn();

vi.mock('$lib/services/email-folders.js', () => ({
	fetchEmailFolders: (...args) => mockFetchEmailFolders(...args),
	updateEmailFolder: (...args) => mockUpdateEmailFolder(...args)
}));

vi.mock('$lib/services/sender-rules.js', () => ({
	fetchSenderRules: (...args) => mockFetchSenderRules(...args),
	createSenderRule: (...args) => mockCreateSenderRule(...args),
	deleteSenderRule: (...args) => mockDeleteSenderRule(...args)
}));

const { default: SettingsPage } = await import('../+page.svelte');

describe('Settings Page', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockSignOut.mockResolvedValue({ error: null });
		mockGetCalendarSettings.mockResolvedValue({ data: null, error: null });
		mockListCalendars.mockResolvedValue({ data: null, error: null });
		mockUpdateCalendarSettings.mockResolvedValue({ data: null, error: null });
		mockDisconnectIntegration.mockResolvedValue({ data: true, error: null });
		mockFetchSenderRules.mockResolvedValue({ data: [], error: null });
		mockFetchEmailFolders.mockResolvedValue({ data: [], error: null });
		mockUpdateEmailFolder.mockResolvedValue({ data: null, error: null });
	});

	it('shows loading spinner initially', () => {
		mockFetchIntegrations.mockReturnValue(new Promise(() => {}));
		mockGetCalendarSettings.mockReturnValue(new Promise(() => {}));

		render(SettingsPage);

		expect(document.querySelector('.loading.loading-spinner')).toBeTruthy();
	});

	it('displays page title', async () => {
		mockFetchIntegrations.mockResolvedValue({ data: [], error: null });

		render(SettingsPage);

		await waitFor(() => {
			expect(screen.getByText('Settings')).toBeInTheDocument();
		});
	});

	it('shows Connected Accounts section', async () => {
		mockFetchIntegrations.mockResolvedValue({
			data: [
				{ id: '1', provider: 'gmail', status: 'active', provider_email: 'test@gmail.com' }
			],
			error: null
		});

		render(SettingsPage);

		await waitFor(() => {
			expect(screen.getByText('Connected Accounts')).toBeInTheDocument();
			expect(screen.getByText('Gmail')).toBeInTheDocument();
		});
	});

	it('shows user email in account section', async () => {
		mockFetchIntegrations.mockResolvedValue({ data: [], error: null });

		render(SettingsPage);

		await waitFor(() => {
			expect(screen.getByText('Account')).toBeInTheDocument();
			expect(screen.getByText('test@example.com')).toBeInTheDocument();
			expect(screen.queryByRole('textbox', { name: /email/i })).not.toBeInTheDocument();
		});
	});

	it('shows calendar settings when Google Calendar is connected', async () => {
		mockFetchIntegrations.mockResolvedValue({
			data: [
				{
					id: '2',
					provider: 'google_calendar',
					status: 'active',
					provider_email: 'test@gmail.com'
				}
			],
			error: null
		});
		mockListCalendars.mockResolvedValue({
			data: [
				{ id: 'cal1', name: 'My Calendar', is_primary: true },
				{ id: 'cal2', name: 'Work', is_primary: false }
			],
			error: null
		});

		render(SettingsPage);

		await waitFor(() => {
			expect(screen.getByText('Calendar Defaults')).toBeInTheDocument();
			expect(screen.getByLabelText(/target calendar/i)).toBeInTheDocument();
		});
	});

	it('shows message when Google Calendar is not connected', async () => {
		mockFetchIntegrations.mockResolvedValue({ data: [], error: null });

		render(SettingsPage);

		await waitFor(() => {
			expect(screen.getByText(/Connect Google Calendar to configure/)).toBeInTheDocument();
		});
	});

	it('shows Automation Rules section', async () => {
		mockFetchIntegrations.mockResolvedValue({ data: [], error: null });

		render(SettingsPage);

		await waitFor(() => {
			expect(screen.getByText('Automation Rules')).toBeInTheDocument();
		});
	});

	it('shows disconnect buttons for connected integrations', async () => {
		mockFetchIntegrations.mockResolvedValue({
			data: [
				{
					id: '1',
					provider: 'gmail',
					status: 'active',
					provider_email: 'test@gmail.com'
				},
				{
					id: '2',
					provider: 'google_calendar',
					status: 'active',
					provider_email: 'test@gmail.com'
				}
			],
			error: null
		});
		mockListCalendars.mockResolvedValue({ data: [], error: null });

		render(SettingsPage);

		await waitFor(() => {
			const disconnectButtons = screen.getAllByText('Disconnect');
			expect(disconnectButtons.length).toBe(2);
		});
	});

	it('shows Gmail and Outlook user folders with recommendation reasons', async () => {
		mockFetchIntegrations.mockResolvedValue({
			data: [
				{ id: 'gmail-1', provider: 'gmail', status: 'active', provider_email: 'test@gmail.com' },
				{ id: 'outlook-1', provider: 'outlook', status: 'active', provider_email: 'test@outlook.com' }
			],
			error: null
		});
		mockFetchEmailFolders.mockImplementation(async (provider) => ({
			data: provider === 'gmail'
				? [{ id: 'folder-gmail', full_path: 'Newsletters', is_included: false, classification_decision: 'exclude', classification_reason: 'Marketing mail', user_override: false }]
				: [{ id: 'folder-outlook', full_path: 'Projects', is_included: true, classification_decision: 'include', classification_reason: null, user_override: true }],
			error: null
		}));

		render(SettingsPage);

		await waitFor(() => {
			expect(screen.getByText('Newsletters')).toBeInTheDocument();
			expect(screen.getByText('Projects')).toBeInTheDocument();
			expect(screen.getByText('Recommendation: Marketing mail')).toBeInTheDocument();
		});
		expect(screen.queryByText('Inbox')).not.toBeInTheDocument();
	});

	it('updates a folder override through the folder service', async () => {
		const user = userEvent.setup();
		mockFetchIntegrations.mockResolvedValue({
			data: [{ id: 'gmail-1', provider: 'gmail', status: 'active', provider_email: 'test@gmail.com' }],
			error: null
		});
		mockFetchEmailFolders.mockResolvedValue({
			data: [{ id: 'folder-gmail', full_path: 'Newsletters', is_included: false, classification_decision: 'exclude', classification_reason: 'Marketing mail', user_override: false }],
			error: null
		});
		mockUpdateEmailFolder.mockResolvedValue({
			data: { id: 'folder-gmail', is_included: true, user_override: true },
			error: null
		});

		render(SettingsPage);
		await waitFor(() => expect(screen.getByText('Newsletters')).toBeInTheDocument());
		await user.click(screen.getByRole('switch', { name: 'Include' }));

		await waitFor(() => expect(mockUpdateEmailFolder).toHaveBeenCalledWith('gmail', 'folder-gmail', true));
		expect(screen.getByRole('switch', { name: 'Exclude' })).toHaveAttribute('aria-checked', 'true');
	});

	it('rolls back a failed folder update and retries only that row', async () => {
		const user = userEvent.setup();
		mockFetchIntegrations.mockResolvedValue({
			data: [{ id: 'gmail-1', provider: 'gmail', status: 'active', provider_email: 'test@gmail.com' }],
			error: null
		});
		mockFetchEmailFolders.mockResolvedValue({
			data: [{ id: 'folder-gmail', full_path: 'Newsletters', is_included: false, classification_decision: 'exclude', classification_reason: 'Marketing mail', user_override: false }],
			error: null
		});
		mockUpdateEmailFolder
			.mockResolvedValueOnce({ data: null, error: { message: 'Could not save folder' } })
			.mockResolvedValueOnce({ data: { id: 'folder-gmail', is_included: true, user_override: true }, error: null });

		render(SettingsPage);
		await waitFor(() => expect(screen.getByText('Newsletters')).toBeInTheDocument());
		await user.click(screen.getByRole('switch', { name: 'Include' }));

		await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Could not save folder'));
		expect(screen.getByRole('switch', { name: 'Include' })).toHaveAttribute('aria-checked', 'false');
		await user.click(screen.getByRole('button', { name: 'Retry' }));

		await waitFor(() => expect(mockUpdateEmailFolder).toHaveBeenCalledTimes(2));
		expect(screen.getByRole('switch', { name: 'Exclude' })).toHaveAttribute('aria-checked', 'true');
	});

	it('loads and saves date-only event preference', async () => {
		const user = userEvent.setup();
		mockGetCalendarSettings.mockResolvedValue({
			data: {
				user_id: '123',
				target_calendar_id: null,
				default_invitees: null,
				all_day_display_mode: 'all_day',
				all_day_custom_start: null,
				all_day_custom_end: null,
				updated_at: '2026-07-22T00:00:00Z'
			},
			error: null
		});
		mockUpdateCalendarSettings.mockResolvedValue({
			data: {
				user_id: '123',
				all_day_display_mode: 'day_9_to_5',
				updated_at: '2026-07-22T00:00:00Z'
			},
			error: null
		});

		render(SettingsPage);
		await waitFor(() => expect(screen.getByLabelText('Date-only events')).toBeInTheDocument());

		const select = screen.getByLabelText('Date-only events');
		await user.selectOptions(select, 'day_9_to_5');

		await waitFor(() =>
			expect(mockUpdateCalendarSettings).toHaveBeenCalledWith({
				all_day_display_mode: 'day_9_to_5'
			})
		);
		expect(screen.getByText(/Example: Water Day/)).toBeInTheDocument();
	});

	it('shows an inline error when custom end is not later than start', async () => {
		const user = userEvent.setup();
		mockGetCalendarSettings.mockResolvedValue({
			data: {
				user_id: '123',
				all_day_display_mode: 'custom',
				all_day_custom_start: '09:00:00',
				all_day_custom_end: '17:00:00',
				updated_at: '2026-07-22T00:00:00Z'
			},
			error: null
		});

		render(SettingsPage);
		await waitFor(() => expect(screen.getByLabelText('Custom start')).toBeInTheDocument());

		const endInput = screen.getByLabelText('Custom end');
		await user.clear(endInput);
		await user.type(endInput, '08:00');
		endInput.dispatchEvent(new Event('change', { bubbles: true }));

		await waitFor(() =>
			expect(screen.getByRole('alert')).toHaveTextContent('End time must be later than start time.')
		);
		expect(mockUpdateCalendarSettings).not.toHaveBeenCalled();
	});
});
