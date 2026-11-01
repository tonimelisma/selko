/**
 * Which connected providers can receive calendar writes.
 *
 * Selko writes events to exactly one target calendar, which may live in
 * Google Calendar or Outlook. Google Calendar is its own integration row;
 * Outlook Calendar shares the Outlook mail row and is usable only when that
 * row was granted the Graph `Calendars.ReadWrite` scope. Outlook users who
 * connected before calendar support lack the scope and must reconnect.
 */

/** @typedef {{ provider?: string, status?: string, scopes?: unknown }} IntegrationLike */

/**
 * @param {IntegrationLike | null | undefined} integration
 * @returns {boolean}
 */
export function outlookHasCalendarScope(integration) {
	if (!integration || integration.provider !== 'outlook') return false;
	const scopes = Array.isArray(integration.scopes) ? integration.scopes : [];
	return scopes.some(
		(scope) => typeof scope === 'string' && scope.toLowerCase().endsWith('calendars.readwrite')
	);
}

/**
 * @param {IntegrationLike[] | null | undefined} integrations
 * @returns {boolean}
 */
export function hasWritableCalendar(integrations) {
	return (integrations ?? []).some(
		(integration) =>
			integration?.status === 'active' &&
			(integration.provider === 'google_calendar' || outlookHasCalendarScope(integration))
	);
}

/**
 * True when an active Outlook connection is missing calendar scope, so a
 * reconnect would enable Outlook Calendar.
 * @param {IntegrationLike[] | null | undefined} integrations
 * @returns {boolean}
 */
export function needsOutlookCalendarReconnect(integrations) {
	return (integrations ?? []).some(
		(integration) =>
			integration?.provider === 'outlook' &&
			integration.status === 'active' &&
			!outlookHasCalendarScope(integration)
	);
}

/**
 * @typedef {'google' | 'outlook'} SignIn
 * @typedef {'reconnect' | 'connectEmail' | 'connectCalendar'} RecoveryVerb
 * @typedef {{ provider: SignIn, verb: RecoveryVerb }} RecoveryAction
 * @typedef {'mail' | 'calendar' | 'mailAndCalendar'} LostAccess
 * @typedef {'google' | 'outlook' | 'accounts' | 'connectEmail' | 'connectCalendar'} RecoveryKind
 * @typedef {{ kind: RecoveryKind, lost: LostAccess | null, actions: RecoveryAction[] }} RecoveryPlan
 */

/**
 * @param {boolean} mail
 * @param {boolean} calendar
 * @returns {LostAccess}
 */
function lostAccess(mail, calendar) {
	if (mail && calendar) return 'mailAndCalendar';
	return mail ? 'mail' : 'calendar';
}

/**
 * What the connection banner asks for, written from the user's side: name the
 * account that stopped working and what it stopped doing, then offer the one
 * sign-in that fixes it.
 *
 * A lapsed sign-in comes first, because it is the account the user already
 * chose. Offering a different provider beside it ("or switch to Outlook")
 * made the banner a menu of equal-looking buttons for a problem with one
 * answer. Switching providers stays in Settings.
 *
 * @param {IntegrationLike[] | null | undefined} integrations
 * @returns {RecoveryPlan | null} null when nothing needs the user
 */
export function recoveryPlan(integrations) {
	const rows = (integrations ?? []).filter((row) => row?.provider !== 'google_photos');
	const gmail = rows.find((row) => row.provider === 'gmail');
	const googleCalendar = rows.find((row) => row.provider === 'google_calendar');
	const outlook = rows.find((row) => row.provider === 'outlook');
	const calendarWritable = hasWritableCalendar(rows);

	// A lapsed Google Calendar is not worth a prompt while Outlook Calendar works.
	const googleMailLost = !!gmail && gmail.status !== 'active';
	const googleCalendarLost =
		!!googleCalendar && googleCalendar.status !== 'active' && !calendarWritable;
	const outlookLost = !!outlook && outlook.status !== 'active';

	if (googleMailLost || googleCalendarLost || outlookLost) {
		if ((googleMailLost || googleCalendarLost) && outlookLost) {
			return {
				kind: 'accounts',
				lost: null,
				actions: [
					{ provider: 'google', verb: 'reconnect' },
					{ provider: 'outlook', verb: 'reconnect' }
				]
			};
		}
		if (outlookLost) {
			return {
				kind: 'outlook',
				lost: lostAccess(true, outlookHasCalendarScope(outlook) && !calendarWritable),
				actions: [{ provider: 'outlook', verb: 'reconnect' }]
			};
		}
		return {
			kind: 'google',
			lost: lostAccess(googleMailLost, googleCalendarLost),
			actions: [{ provider: 'google', verb: 'reconnect' }]
		};
	}

	const gmailActive = gmail?.status === 'active';
	const outlookActive = outlook?.status === 'active';
	if (!gmailActive && !outlookActive) {
		// Two equal choices are right here: Selko cannot know which mail the user has.
		return {
			kind: 'connectEmail',
			lost: null,
			actions: [
				{ provider: 'google', verb: 'connectEmail' },
				{ provider: 'outlook', verb: 'connectEmail' }
			]
		};
	}
	if (!calendarWritable) {
		// Offer the calendar of the account the user already signed in with.
		return {
			kind: 'connectCalendar',
			lost: null,
			actions: [{ provider: gmailActive ? 'google' : 'outlook', verb: 'connectCalendar' }]
		};
	}
	return null;
}
