// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
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

	it('shows per-service status when partially connected in setup mode', () => {
		render(IntegrationStatus, {
			props: {
				integrations: [
					{ id: '1', provider: 'gmail', status: 'active', provider_email: 'test@gmail.com' }
				],
				setupMode: true
			}
		});

		expect(screen.getByText('Connect your accounts')).toBeInTheDocument();
		expect(screen.getByText('Gmail')).toBeInTheDocument();
		expect(screen.getByText('Google Calendar')).toBeInTheDocument();
	});

	it('shows disconnect buttons in settings mode', () => {
		render(IntegrationStatus, {
			props: { integrations: activeIntegrations, setupMode: false }
		});

		const disconnectButtons = screen.getAllByText('Disconnect');
		expect(disconnectButtons.length).toBe(2);
	});

	it('calls ondisconnect with integration id', async () => {
		const user = userEvent.setup();
		const mockDisconnect = vi.fn();
		render(IntegrationStatus, {
			props: {
				integrations: activeIntegrations,
				setupMode: false,
				ondisconnect: mockDisconnect
			}
		});

		const disconnectButtons = screen.getAllByText('Disconnect');
		await user.click(disconnectButtons[0]);
		expect(mockDisconnect).toHaveBeenCalledWith('1');
	});

	it('shows reconnect button for expired integrations', () => {
		render(IntegrationStatus, {
			props: {
				integrations: [
					{ id: '1', provider: 'gmail', status: 'expired', provider_email: 'test@gmail.com' }
				],
				setupMode: false
			}
		});

		expect(screen.getByText('Reconnect')).toBeInTheDocument();
	});
});
