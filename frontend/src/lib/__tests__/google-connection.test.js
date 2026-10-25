import { describe, it, expect } from 'vitest';
import { deriveGoogleConnection } from '../google-connection.js';

const gmail = { id: 'g', provider: 'gmail', status: 'active', provider_email: 'a@gmail.com' };
const calendar = { id: 'c', provider: 'google_calendar', status: 'active', provider_email: 'a@gmail.com' };
const outlook = { id: 'o', provider: 'outlook', status: 'expired' };

describe('deriveGoogleConnection', () => {
	it('is not connected with no Google rows, ignoring Outlook', () => {
		expect(deriveGoogleConnection([outlook])).toMatchObject({ state: 'not_connected', rows: [] });
	});

	it('is connected only when both rows are active', () => {
		expect(deriveGoogleConnection([gmail, calendar, outlook])).toMatchObject({
			state: 'connected',
			email: 'a@gmail.com'
		});
	});

	it('is partial and names the missing product', () => {
		expect(deriveGoogleConnection([gmail])).toMatchObject({ state: 'partial', missing: 'google_calendar' });
		expect(deriveGoogleConnection([calendar])).toMatchObject({ state: 'partial', missing: 'gmail' });
	});

	it('needs reconnect when either row is inactive, even if the other is missing', () => {
		expect(
			deriveGoogleConnection([gmail, { ...calendar, status: 'expired' }])
		).toMatchObject({ state: 'needs_reconnect', status: 'expired' });
		expect(deriveGoogleConnection([{ ...gmail, status: 'revoked' }])).toMatchObject({
			state: 'needs_reconnect',
			status: 'revoked'
		});
	});
});
