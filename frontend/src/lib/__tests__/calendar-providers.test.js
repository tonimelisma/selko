import { describe, it, expect } from 'vitest';
import {
	outlookHasCalendarScope,
	hasWritableCalendar,
	needsOutlookCalendarReconnect
} from '../calendar-providers.js';

const outlookWithScope = {
	provider: 'outlook',
	status: 'active',
	scopes: ['offline_access', 'Mail.Read', 'https://graph.microsoft.com/Calendars.ReadWrite']
};
const outlookNoScope = { provider: 'outlook', status: 'active', scopes: ['Mail.Read'] };
const gcal = { provider: 'google_calendar', status: 'active', scopes: [] };

describe('outlookHasCalendarScope', () => {
	it('accepts bare and URL-qualified scope names case-insensitively', () => {
		expect(outlookHasCalendarScope({ provider: 'outlook', scopes: ['Calendars.ReadWrite'] })).toBe(true);
		expect(outlookHasCalendarScope({ provider: 'outlook', scopes: ['calendars.readwrite'] })).toBe(true);
		expect(outlookHasCalendarScope(outlookWithScope)).toBe(true);
	});

	it('rejects missing, malformed or read-only scopes and non-Outlook rows', () => {
		expect(outlookHasCalendarScope(outlookNoScope)).toBe(false);
		expect(outlookHasCalendarScope({ provider: 'outlook', scopes: ['Calendars.Read'] })).toBe(false);
		expect(outlookHasCalendarScope({ provider: 'outlook', scopes: null })).toBe(false);
		expect(outlookHasCalendarScope({ provider: 'outlook' })).toBe(false);
		expect(outlookHasCalendarScope({ provider: 'gmail', scopes: ['Calendars.ReadWrite'] })).toBe(false);
		expect(outlookHasCalendarScope(null)).toBe(false);
	});
});

describe('hasWritableCalendar', () => {
	it('is true for active Google Calendar', () => {
		expect(hasWritableCalendar([gcal])).toBe(true);
	});

	it('is true for active Outlook with calendar scope', () => {
		expect(hasWritableCalendar([outlookWithScope])).toBe(true);
	});

	it('is false for Outlook without scope, inactive rows, or nothing', () => {
		expect(hasWritableCalendar([outlookNoScope])).toBe(false);
		expect(hasWritableCalendar([{ ...outlookWithScope, status: 'expired' }])).toBe(false);
		expect(hasWritableCalendar([{ ...gcal, status: 'expired' }])).toBe(false);
		expect(hasWritableCalendar([{ provider: 'gmail', status: 'active' }])).toBe(false);
		expect(hasWritableCalendar([])).toBe(false);
		expect(hasWritableCalendar(undefined)).toBe(false);
	});
});

describe('needsOutlookCalendarReconnect', () => {
	it('is true only for an active Outlook row lacking calendar scope', () => {
		expect(needsOutlookCalendarReconnect([outlookNoScope])).toBe(true);
		expect(needsOutlookCalendarReconnect([gcal, outlookNoScope])).toBe(true);
		expect(needsOutlookCalendarReconnect([outlookWithScope])).toBe(false);
		expect(needsOutlookCalendarReconnect([{ ...outlookNoScope, status: 'expired' }])).toBe(false);
		expect(needsOutlookCalendarReconnect([gcal])).toBe(false);
		expect(needsOutlookCalendarReconnect([])).toBe(false);
	});
});
