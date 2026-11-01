// @ts-nocheck
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';

const { default: ConnectionRecovery } = await import('../ConnectionRecovery.svelte');

describe('ConnectionRecovery', () => {
	it('ignores parked Google Photos integrations', () => {
		render(ConnectionRecovery, {
			props: {
				integrations: [
					{ id: '1', provider: 'gmail', status: 'active' },
					{ id: '2', provider: 'google_calendar', status: 'active' },
					{ id: '3', provider: 'google_photos', status: 'expired' }
				],
				onauthorize: vi.fn()
			}
		});

		expect(screen.queryByText('Connection needs attention')).not.toBeInTheDocument();
		expect(screen.queryByRole('button', { name: /reconnect/i })).not.toBeInTheDocument();
	});

	it('keeps intrinsic recovery actions out of inline-size containment', () => {
		render(ConnectionRecovery, {
			props: {
				integrations: [
					{ id: '1', provider: 'gmail', status: 'active' },
					{ id: '2', provider: 'google_calendar', status: 'active' },
					{ id: '3', provider: 'outlook', status: 'expired' }
				],
				onauthorize: vi.fn()
			}
		});

		expect(document.querySelector('.peer-action-group--intrinsic')).toBeInTheDocument();
	});

	it('treats a calendar-scoped Outlook connection as a connected calendar', () => {
		render(ConnectionRecovery, {
			props: {
				integrations: [
					{ id: '1', provider: 'outlook', status: 'active', scopes: ['Mail.Read', 'Calendars.ReadWrite'] }
				],
				onauthorize: vi.fn()
			}
		});

		expect(screen.queryByText('Reconnect Google Calendar')).not.toBeInTheDocument();
		expect(screen.queryByText('Connect your calendar')).not.toBeInTheDocument();
		expect(screen.queryByRole('button', { name: /connect/i })).not.toBeInTheDocument();
	});

	it('offers an Outlook reconnect when Outlook lacks calendar scope', async () => {
		const onauthorize = vi.fn().mockResolvedValue(undefined);
		render(ConnectionRecovery, {
			props: {
				integrations: [{ id: '1', provider: 'outlook', status: 'active', scopes: ['Mail.Read'] }],
				onauthorize
			}
		});

		expect(screen.getByRole('heading', { name: 'Connect your calendar' })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Connect Google Calendar' })).toBeInTheDocument();
		const reconnect = screen.getByRole('button', { name: 'Reconnect Outlook' });
		await fireEvent.click(reconnect);
		expect(onauthorize).toHaveBeenCalledWith('outlook');
	});

	it('keeps the Google Calendar title when a Google Calendar row exists', () => {
		render(ConnectionRecovery, {
			props: {
				integrations: [
					{ id: '1', provider: 'outlook', status: 'active', scopes: [] },
					{ id: '2', provider: 'google_calendar', status: 'expired' }
				],
				onauthorize: vi.fn()
			}
		});

		expect(screen.getByRole('heading', { name: 'Reconnect Google Calendar' })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Reconnect Google Calendar' })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Reconnect Outlook' })).toBeInTheDocument();
	});
});
