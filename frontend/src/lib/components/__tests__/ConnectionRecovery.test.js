// @ts-nocheck
import { describe, it, expect, vi } from 'vitest';
import { render, screen, fireEvent } from '@testing-library/svelte';

const { default: ConnectionRecovery } = await import('../ConnectionRecovery.svelte');

/** @param {object[]} integrations */
function renderBanner(integrations, onauthorize = vi.fn().mockResolvedValue(undefined)) {
	render(ConnectionRecovery, { props: { integrations, onauthorize } });
	return onauthorize;
}

describe('ConnectionRecovery', () => {
	it('shows nothing when every connection works', () => {
		renderBanner([
			{ id: '1', provider: 'gmail', status: 'active' },
			{ id: '2', provider: 'google_calendar', status: 'active' },
			{ id: '3', provider: 'google_photos', status: 'expired' }
		]);

		expect(screen.queryByRole('heading')).not.toBeInTheDocument();
		expect(screen.queryByRole('button')).not.toBeInTheDocument();
	});

	it('names the Google account, not a calendar, when Google signed out beside a mail-only Outlook', async () => {
		// Regression: production showed "Reconnect your calendar" with equal
		// "Reconnect Outlook" and "Reconnect Google" buttons, although Gmail was
		// down too and Outlook had never been the user's calendar.
		const onauthorize = renderBanner([
			{ id: '1', provider: 'gmail', status: 'expired' },
			{ id: '2', provider: 'google_calendar', status: 'expired' },
			{ id: '3', provider: 'outlook', status: 'active', scopes: ['Mail.Read'] }
		]);

		expect(screen.getByRole('heading', { name: 'Reconnect your Google account' })).toBeInTheDocument();
		expect(screen.getByText(/can’t read new Gmail or add events to Google Calendar/)).toBeInTheDocument();
		expect(screen.getAllByRole('button')).toHaveLength(1);
		expect(screen.queryByRole('button', { name: /outlook/i })).not.toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Reconnect Google' }));
		expect(onauthorize).toHaveBeenCalledWith('google');
	});

	it('keeps Manage connections as a secondary link', () => {
		renderBanner([{ id: '1', provider: 'gmail', status: 'expired' }]);

		const manage = screen.getByRole('link', { name: 'Manage connections' });
		expect(manage).toHaveAttribute('href', '/app/settings');
		expect(manage).not.toHaveClass('btn-primary');
	});

	it('puts the actions below the message so the text keeps the card width', () => {
		renderBanner([{ id: '1', provider: 'gmail', status: 'expired' }]);

		const description = screen.getByText(/Selko lost access to Google/);
		const button = screen.getByRole('button', { name: 'Reconnect Google' });
		expect(description.parentElement?.contains(button)).toBe(true);
	});

	it('says only mail is affected when Gmail lapsed and the calendar works', () => {
		renderBanner([
			{ id: '1', provider: 'gmail', status: 'expired' },
			{ id: '2', provider: 'outlook', status: 'active', scopes: ['Mail.Read', 'Calendars.ReadWrite'] }
		]);

		expect(screen.getByRole('heading', { name: 'Reconnect your Google account' })).toBeInTheDocument();
		expect(screen.getByText(/can’t read new Gmail\./)).toBeInTheDocument();
	});

	it('says only the calendar is affected when Google Calendar lapsed and Gmail works', () => {
		renderBanner([
			{ id: '1', provider: 'gmail', status: 'active' },
			{ id: '2', provider: 'google_calendar', status: 'revoked' }
		]);

		expect(screen.getByRole('heading', { name: 'Reconnect your Google account' })).toBeInTheDocument();
		expect(screen.getByText(/lost access to Google Calendar/)).toBeInTheDocument();
		expect(screen.getAllByRole('button')).toHaveLength(1);
	});

	it('does not prompt for a lapsed Google Calendar while Outlook Calendar works', () => {
		renderBanner([
			{ id: '1', provider: 'outlook', status: 'active', scopes: ['Calendars.ReadWrite'] },
			{ id: '2', provider: 'google_calendar', status: 'expired' }
		]);

		expect(screen.queryByRole('button')).not.toBeInTheDocument();
	});

	it('asks to reconnect Outlook when the Outlook sign-in lapsed', async () => {
		const onauthorize = renderBanner([
			{ id: '1', provider: 'outlook', status: 'expired', scopes: ['Mail.Read', 'Calendars.ReadWrite'] }
		]);

		expect(screen.getByRole('heading', { name: 'Reconnect your Outlook account' })).toBeInTheDocument();
		expect(screen.getByText(/can’t read new mail or add events to Outlook Calendar/)).toBeInTheDocument();
		await fireEvent.click(screen.getByRole('button', { name: 'Reconnect Outlook' }));
		expect(onauthorize).toHaveBeenCalledWith('outlook');
	});

	it('offers both sign-ins only when both lapsed', () => {
		renderBanner([
			{ id: '1', provider: 'gmail', status: 'expired' },
			{ id: '2', provider: 'outlook', status: 'expired' }
		]);

		expect(screen.getByRole('heading', { name: 'Reconnect your accounts' })).toBeInTheDocument();
		expect(screen.getAllByRole('button').map((b) => b.textContent?.trim())).toEqual([
			'Reconnect Google',
			'Reconnect Outlook'
		]);
	});

	it('offers the Outlook calendar for a mail-only Outlook user', async () => {
		const onauthorize = renderBanner([
			{ id: '1', provider: 'outlook', status: 'active', scopes: ['Mail.Read'] }
		]);

		expect(screen.getByRole('heading', { name: 'Connect a calendar' })).toBeInTheDocument();
		expect(screen.getAllByRole('button')).toHaveLength(1);
		await fireEvent.click(screen.getByRole('button', { name: 'Connect Outlook Calendar' }));
		expect(onauthorize).toHaveBeenCalledWith('outlook');
	});

	it('offers Google Calendar to a Gmail user without a calendar', () => {
		renderBanner([{ id: '1', provider: 'gmail', status: 'active' }]);

		expect(screen.getByRole('heading', { name: 'Connect a calendar' })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Connect Google Calendar' })).toBeInTheDocument();
	});

	it('treats a calendar-scoped Outlook connection as complete', () => {
		renderBanner([
			{ id: '1', provider: 'outlook', status: 'active', scopes: ['Mail.Read', 'Calendars.ReadWrite'] }
		]);

		expect(screen.queryByRole('button')).not.toBeInTheDocument();
	});
});
