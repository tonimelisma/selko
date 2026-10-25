// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, within } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';

const { default: IntegrationStatus } = await import('../IntegrationStatus.svelte');

const activeIntegrations = [
	{ id: '1', provider: 'gmail', status: 'active', provider_email: 'test@gmail.com' },
	{ id: '2', provider: 'google_calendar', status: 'active', provider_email: 'test@gmail.com' }
];

describe('IntegrationStatus', () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it('shows welcome message in setup mode with no integrations', () => {
		render(IntegrationStatus, {
			props: { integrations: [], setupMode: true }
		});

		expect(screen.getByText('Welcome to Selko')).toBeInTheDocument();
		expect(screen.getByText('Connect Google Account')).toBeInTheDocument();
	});

	it('calls onconnect when connect button clicked in setup mode', async () => {
		const user = userEvent.setup();
		const mockConnect = vi.fn();
		render(IntegrationStatus, {
			props: { integrations: [], setupMode: true, onconnect: mockConnect }
		});

		await user.click(screen.getByText('Connect Google Account'));
		expect(mockConnect).toHaveBeenCalled();
	});

	it('shows one Google card when partially connected in setup mode', () => {
		render(IntegrationStatus, {
			props: {
				integrations: [
					{ id: '1', provider: 'gmail', status: 'active', provider_email: 'test@gmail.com' }
				],
				setupMode: true
			}
		});

		expect(screen.getByText('Connect your accounts')).toBeInTheDocument();
		expect(screen.getByText('Google')).toBeInTheDocument();
		expect(screen.getByText('Outlook')).toBeInTheDocument();
		expect(screen.queryByText('Gmail', { selector: 'h3' })).not.toBeInTheDocument();
		expect(screen.queryByText('Google Calendar', { selector: 'h3' })).not.toBeInTheDocument();
	});

	it('shows Connected and one Disconnect when both Google rows are active', () => {
		render(IntegrationStatus, {
			props: { integrations: activeIntegrations, setupMode: false }
		});

		const card = screen.getByTestId('connection-card-google');
		expect(within(card).getByText('Connected')).toBeInTheDocument();
		expect(within(card).getByText('test@gmail.com')).toBeInTheDocument();
		expect(within(card).getAllByRole('button', { name: 'Disconnect' })).toHaveLength(1);
		expect(within(card).queryByRole('button', { name: /reconnect/i })).not.toBeInTheDocument();
	});

	it('calls ondisconnect with the google card key', async () => {
		const user = userEvent.setup();
		const mockDisconnect = vi.fn();
		render(IntegrationStatus, {
			props: {
				integrations: activeIntegrations,
				setupMode: false,
				ondisconnect: mockDisconnect
			}
		});

		const card = screen.getByTestId('connection-card-google');
		await user.click(within(card).getByRole('button', { name: 'Disconnect' }));
		expect(mockDisconnect).toHaveBeenCalledWith('google');
	});

	it('names the missing product when only Gmail was granted', async () => {
		const user = userEvent.setup();
		const mockAuthorize = vi.fn();
		render(IntegrationStatus, {
			props: {
				integrations: [activeIntegrations[0]],
				setupMode: false,
				onauthorize: mockAuthorize
			}
		});

		const card = screen.getByTestId('connection-card-google');
		expect(within(card).getByText('Google Calendar not connected')).toBeInTheDocument();
		expect(within(card).getByText(/didn’t allow Google Calendar/)).toBeInTheDocument();
		await user.click(within(card).getByRole('button', { name: 'Reconnect Google' }));
		expect(mockAuthorize).toHaveBeenCalledWith('google');
	});

	it('names Gmail as missing when only Calendar was granted', () => {
		render(IntegrationStatus, {
			props: { integrations: [activeIntegrations[1]], setupMode: false }
		});

		const card = screen.getByTestId('connection-card-google');
		expect(within(card).getByText('Gmail not connected')).toBeInTheDocument();
		expect(within(card).getByRole('button', { name: 'Reconnect Google' })).toBeInTheDocument();
	});

	it('shows Reconnect Google when either Google row is expired', () => {
		render(IntegrationStatus, {
			props: {
				integrations: [
					activeIntegrations[0],
					{ ...activeIntegrations[1], status: 'expired' }
				],
				setupMode: false
			}
		});

		const card = screen.getByTestId('connection-card-google');
		expect(within(card).getByText('Expired')).toBeInTheDocument();
		expect(within(card).getByRole('button', { name: 'Reconnect Google' })).toBeInTheDocument();
		expect(within(card).getByRole('button', { name: 'Disconnect' })).toBeInTheDocument();
	});

	it('connects Google with one button when nothing is stored', async () => {
		const user = userEvent.setup();
		const mockAuthorize = vi.fn();
		render(IntegrationStatus, {
			props: { integrations: [], setupMode: false, onauthorize: mockAuthorize }
		});

		const card = screen.getByTestId('connection-card-google');
		expect(within(card).getByText('Not Connected')).toBeInTheDocument();
		expect(within(card).queryByRole('button', { name: 'Disconnect' })).not.toBeInTheDocument();
		await user.click(within(card).getByRole('button', { name: 'Connect' }));
		expect(mockAuthorize).toHaveBeenCalledWith('google');
	});

	it('keeps a plain Reconnect for an expired Outlook account', () => {
		render(IntegrationStatus, {
			props: {
				integrations: [
					{ id: '3', provider: 'outlook', status: 'expired', provider_email: 'a@outlook.com' }
				],
				setupMode: false
			}
		});

		const card = screen.getByTestId('connection-card-outlook');
		expect(within(card).getByRole('button', { name: 'Reconnect' })).toBeInTheDocument();
	});

	it('shows connecting spinner while OAuth starts', async () => {
		const user = userEvent.setup();
		let resolveConnect;
		const mockConnect = vi.fn(
			() =>
				new Promise((resolve) => {
					resolveConnect = resolve;
				})
		);

		render(IntegrationStatus, {
			props: { integrations: [], setupMode: true, onconnect: mockConnect }
		});

		await user.click(screen.getByRole('button', { name: /connect google account/i }));

		expect(await screen.findByText('Connecting…')).toBeInTheDocument();
		expect(document.querySelector('.loading.loading-spinner')).toBeTruthy();
		expect(screen.getByRole('button', { name: /connecting/i })).toBeDisabled();

		resolveConnect();
	});

	it('surfaces OAuth start errors', async () => {
		const user = userEvent.setup();
		const mockConnect = vi.fn().mockRejectedValue(new Error('Not authenticated'));

		render(IntegrationStatus, {
			props: { integrations: [], setupMode: true, onconnect: mockConnect }
		});

		await user.click(screen.getByRole('button', { name: /connect google account/i }));

		expect(await screen.findByText('Not authenticated')).toBeInTheDocument();
		expect(screen.getByRole('button', { name: /connect google account/i })).not.toBeDisabled();
	});
});
