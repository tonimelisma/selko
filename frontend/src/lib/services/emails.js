import { apiFetch } from '$lib/api/client.js';
import { toAppError } from '$lib/errors.js';

/**
 * @typedef {Object} EmailSummary
 * @property {string} id - UUID
 * @property {string} email_provider
 * @property {string | null} [subject]
 * @property {string | null} [from_email]
 * @property {string | null} [from_name]
 * @property {string | null} [date_sent]
 * @property {string | null} [snippet]
 * @property {boolean} [has_attachments]
 */

/**
 * Get the summary of one email (sender, subject, date, snippet).
 * @param {string} emailId - The email UUID
 * @returns {Promise<{data: EmailSummary | null, error: import('$lib/errors.js').AppError | null}>}
 */
export async function getEmail(emailId) {
	const { data, error } = await apiFetch(`/emails/${encodeURIComponent(emailId)}`);
	if (error) return { data: null, error: toAppError(error) };
	return { data, error: null };
}
