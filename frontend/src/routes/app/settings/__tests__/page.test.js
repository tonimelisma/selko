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
	initiateCalendarAuth: (...args) => mockInitiateCalendarAuth(...args)
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
			const emailInput = screen.getByLabelText(/email/i);
			expect(emailInput.value).toBe('test@example.com');
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
});
