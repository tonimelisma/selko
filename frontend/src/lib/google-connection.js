/**
 * One Google consent connects Gmail and Google Calendar together, and the
 * callback stores the shared token in both `integrations` rows. The client
 * shows those two rows as one Google connection.
 */

/** Integration providers that share the Google consent. */
export const GOOGLE_PROVIDERS = /** @type {const} */ (['gmail', 'google_calendar']);

/**
 * @typedef {Object} GoogleConnection
 * @property {'not_connected' | 'connected' | 'partial' | 'needs_reconnect'} state
 *   - `partial`: one product is active and the other has no row, because the
 *     user unticked its scope on Google's consent screen.
 *   - `needs_reconnect`: a row exists but is expired, revoked or errored.
 * @property {'gmail' | 'google_calendar' | null} missing - Product absent in `partial`
 * @property {string | null} status - Row status to badge (`needs_reconnect`), else null
 * @property {any[]} rows - The Google integration rows present
 * @property {string | null} email - The connected Google account address
 */

/**
 * Derive the single Google connection from the integrations list.
 * @param {any[]} integrations
 * @returns {GoogleConnection}
 */
export function deriveGoogleConnection(integrations) {
	const gmail = integrations.find((i) => i.provider === 'gmail');
	const calendar = integrations.find((i) => i.provider === 'google_calendar');
	const rows = [gmail, calendar].filter(Boolean);
	const email = rows.find((row) => row.provider_email)?.provider_email ?? null;

	if (rows.length === 0) {
		return { state: 'not_connected', missing: null, status: null, rows, email };
	}
	const inactive = rows.find((row) => row.status !== 'active');
	if (inactive) {
		return { state: 'needs_reconnect', missing: null, status: inactive.status, rows, email };
	}
	if (gmail && calendar) {
		return { state: 'connected', missing: null, status: null, rows, email };
	}
	return {
		state: 'partial',
		missing: gmail ? 'google_calendar' : 'gmail',
		status: null,
		rows,
		email
	};
}
