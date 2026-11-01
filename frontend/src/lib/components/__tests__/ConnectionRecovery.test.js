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

		expect(screen.queryByText('Reconnect your calendar')).not.toBeInTheDocument();
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
		expect(screen.getByRole('button', { name: 'Connect Google' })).toBeInTheDocument();
		const reconnect = screen.getByRole('button', { name: 'Reconnect Outlook' });
		await fireEvent.click(reconnect);
		expect(onauthorize).toHaveBeenCalledWith('outlook');
	});

	it('asks to reconnect the calendar when an earlier calendar connection lapsed', () => {
		render(ConnectionRecovery, {
			props: {
				integrations: [
					{ id: '1', provider: 'outlook', status: 'active', scopes: [] },
					{ id: '2', provider: 'google_calendar', status: 'expired' }
				],
				onauthorize: vi.fn()
			}
		});

		expect(screen.getByRole('heading', { name: 'Reconnect your calendar' })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Reconnect Google' })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Reconnect Outlook' })).toBeInTheDocument();
	});

	it('offers one Google button when Gmail and Google Calendar both expired', async () => {
		// Regression: one row per product produced "Reconnect Gmail" and
		// "Reconnect Google Calendar", two buttons for the same Google sign-in.
		const onauthorize = vi.fn().mockResolvedValue(undefined);
		render(ConnectionRecovery, {
			props: {
				integrations: [
					{ id: '1', provider: 'gmail', status: 'expired' },
					{ id: '2', provider: 'google_calendar', status: 'expired' }
				],
				onauthorize
			}
		});

		const google = screen.getAllByRole('button', { name: /google/i });
		expect(google).toHaveLength(1);
		expect(google[0]).toHaveAccessibleName('Reconnect Google');
		expect(screen.queryByRole('button', { name: /gmail|calendar/i })).not.toBeInTheDocument();
		expect(screen.getByRole('heading', { name: 'Reconnect your email' })).toBeInTheDocument();
		await fireEvent.click(google[0]);
		expect(onauthorize).toHaveBeenCalledWith('google');
	});

	it('does not prompt for a lapsed Google Calendar while Outlook Calendar works', () => {
		render(ConnectionRecovery, {
			props: {
				integrations: [
					{ id: '1', provider: 'outlook', status: 'active', scopes: ['Calendars.ReadWrite'] },
					{ id: '2', provider: 'google_calendar', status: 'expired' }
				],
				onauthorize: vi.fn()
			}
		});

		expect(screen.queryByRole('button', { name: /google/i })).not.toBeInTheDocument();
	});

	it('offers Outlook first when Outlook only lacks calendar consent', () => {
		render(ConnectionRecovery, {
			props: {
				integrations: [{ id: '1', provider: 'outlook', status: 'active', scopes: ['Mail.Read'] }],
				onauthorize: vi.fn()
			}
		});

		const labels = screen
			.getAllByRole('button', { name: /connect/i })
			.map((button) => button.textContent?.trim());
		expect(labels).toEqual(['Reconnect Outlook', 'Connect Google']);
	});

	it('offers one Google button when only Google Calendar lapsed', () => {
		render(ConnectionRecovery, {
			props: {
				integrations: [
					{ id: '1', provider: 'gmail', status: 'active' },
					{ id: '2', provider: 'google_calendar', status: 'revoked' }
				],
				onauthorize: vi.fn()
			}
		});

		expect(screen.getByRole('heading', { name: 'Reconnect your calendar' })).toBeInTheDocument();
		expect(screen.getAllByRole('button', { name: /reconnect/i })).toHaveLength(1);
		expect(screen.getByRole('button', { name: 'Reconnect Google' })).toBeInTheDocument();
	});
});
