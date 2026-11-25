/**
 * Resolve the human-facing sender for an event from its event_sources.
 *
 * Prefer an email source (the person who wrote), then calendar.
 * Never use sources[0] alone — GCal-adopted changes insert a calendar row first.
 *
 * @param {any} event
 * @param {{ unknownSender?: string, googleCalendar?: string }} [labels]
 * @returns {{ senderKey: string, senderName: string }}
 */
export function resolveEventSender(event, labels = {}) {
	const unknownSender = labels.unknownSender || 'Unknown Sender';
	const googleCalendar = labels.googleCalendar || 'Google Calendar';

	/** @type {any[]} */
	const rawSources = event?.event_sources || [];
	const sources = rawSources;

	const emailSource = sources.find(
		/** @param {any} s */
		(s) =>
			(s?.source_origin === 'email' || !s?.source_origin) &&
			(s?.emails?.from_email || s?.emails?.from_name)
	);
	if (emailSource?.emails) {
		const email = emailSource.emails;
		return {
			senderKey: email.from_email || unknownSender,
			senderName: email.from_name || email.from_email || unknownSender
		};
	}

	const calendarSource = sources.find(
		/** @param {any} s */ (s) => s?.source_origin === 'google_calendar'
	);
	if (calendarSource) {
		return {
			senderKey: 'google_calendar',
			senderName: googleCalendar
		};
	}

	return {
		senderKey: unknownSender,
		senderName: unknownSender
	};
}
