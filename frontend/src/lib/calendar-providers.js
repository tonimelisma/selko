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

/** Rows that belong to one Google consent (one sign-in covers both). */
const GOOGLE_ROWS = new Set(['gmail', 'google_calendar']);

/**
 * @typedef {{ provider: 'google' | 'outlook', verb: 'connect' | 'reconnect' }} RecoveryAction
 * @typedef {'email' | 'connectCalendar' | 'reconnectCalendar' | 'attention'} RecoveryTitle
 */

/**
 * What the reconnect banner offers, one action per sign-in rather than per row.
 *
 * Gmail and Google Calendar are separate rows but a single Google consent
 * grants both, so offering both buttons only duplicated the same flow.
 * Outlook mail and Outlook Calendar share one row.
 *
 * @param {IntegrationLike[] | null | undefined} integrations
 * @returns {{ title: RecoveryTitle, actions: RecoveryAction[] }}
 */
export function recoveryActions(integrations) {
	const rows = (integrations ?? []).filter((row) => row?.provider !== 'google_photos');
	const googleRows = rows.filter((row) => GOOGLE_ROWS.has(row.provider ?? ''));
	const outlook = rows.find((row) => row.provider === 'outlook');
	const emailConnected = rows.some(
		(row) => (row.provider === 'gmail' || row.provider === 'outlook') && row.status === 'active'
	);
	const calendarConnected = hasWritableCalendar(rows);

	/** @type {Set<'google' | 'outlook'>} */
	const wanted = new Set();
	if (!emailConnected) {
		wanted.add('google');
		wanted.add('outlook');
	} else if (!calendarConnected) {
		wanted.add('google');
		if (outlook && (outlook.status !== 'active' || !outlookHasCalendarScope(outlook))) {
			wanted.add('outlook');
		}
	}
	// A lapsed Gmail always matters. A lapsed Google Calendar matters only when
	// no calendar is writable, which the branch above already covers; with
	// Outlook Calendar working it is not a reason to prompt.
	if (rows.some((row) => row.provider === 'gmail' && row.status !== 'active')) wanted.add('google');
	if (outlook && outlook.status !== 'active') wanted.add('outlook');

	/** @type {RecoveryAction[]} */
	const google = wanted.has('google')
		? [{ provider: 'google', verb: googleRows.length > 0 ? 'reconnect' : 'connect' }]
		: [];
	/** @type {RecoveryAction[]} */
	const outlookAction = wanted.has('outlook')
		? [{ provider: 'outlook', verb: outlook ? 'reconnect' : 'connect' }]
		: [];
	// An Outlook account that only lacks calendar consent is the shortest fix,
	// so it is offered first.
	const outlookFirst =
		emailConnected &&
		!calendarConnected &&
		outlook?.status === 'active' &&
		!outlookHasCalendarScope(outlook);
	const actions = outlookFirst ? [...outlookAction, ...google] : [...google, ...outlookAction];

	/** @type {RecoveryTitle} */
	let title = 'attention';
	if (!emailConnected) {
		title = 'email';
	} else if (!calendarConnected) {
		const hadCalendar =
			rows.some((row) => row.provider === 'google_calendar') || outlookHasCalendarScope(outlook);
		title = hadCalendar ? 'reconnectCalendar' : 'connectCalendar';
	}
	return { title, actions };
}
