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
