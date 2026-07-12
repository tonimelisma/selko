import { describe, it, expect } from 'vitest';
import { resolveEventSender } from '../event-sender.js';

describe('resolveEventSender', () => {
	it('prefers email source over google_calendar source (Unknown Sender bug)', () => {
		const event = {
			event_sources: [
				{
					source_origin: 'google_calendar',
					emails: null,
					is_undone: false
				},
				{
					source_origin: 'email',
					emails: {
						from_name: 'Cara De Jong',
						from_email: 'Cara@streetsmarts.cc'
					},
					is_undone: false
				}
			]
		};

		const resolved = resolveEventSender(event);
		expect(resolved.senderKey).toBe('Cara@streetsmarts.cc');
		expect(resolved.senderName).toBe('Cara De Jong');
		expect(resolved.isPhotoSource).toBe(false);
	});

	it('uses google photos label when only photo source', () => {
		const event = {
			event_sources: [{ source_origin: 'google_photos', is_undone: false }]
		};
		const resolved = resolveEventSender(event, { googlePhotos: 'Google Photos' });
		expect(resolved.senderKey).toBe('google_photos');
		expect(resolved.senderName).toBe('Google Photos');
		expect(resolved.isPhotoSource).toBe(true);
	});

	it('uses google calendar label when only calendar source', () => {
		const event = {
			event_sources: [{ source_origin: 'google_calendar', is_undone: false }]
		};
		const resolved = resolveEventSender(event, { googleCalendar: 'Google Calendar' });
		expect(resolved.senderKey).toBe('google_calendar');
		expect(resolved.senderName).toBe('Google Calendar');
	});

	it('ignores undone email sources', () => {
		const event = {
			event_sources: [
				{
					source_origin: 'email',
					is_undone: true,
					emails: { from_email: 'old@example.com', from_name: 'Old' }
				},
				{
					source_origin: 'google_calendar',
					is_undone: false
				}
			]
		};
		const resolved = resolveEventSender(event, { googleCalendar: 'Google Calendar' });
		expect(resolved.senderKey).toBe('google_calendar');
	});
});
