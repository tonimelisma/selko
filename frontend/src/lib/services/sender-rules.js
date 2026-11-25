import { apiFetch } from '$lib/api/client.js';
import { toAppError } from '$lib/errors.js';

/**
 * @typedef {'auto_approve' | 'ignore'} SenderRuleAction
 */

/**
 * @typedef {Object} SenderRule
 * @property {string} id - UUID
 * @property {string} user_id - UUID
 * @property {string | null} sender_domain - Domain to match (e.g., "example.com")
 * @property {string | null} sender_email - Email to match (takes precedence over domain)
 * @property {SenderRuleAction} action
 * @property {string} created_at
 * @property {string} updated_at
 */

/**
 * Fetch all sender rules for the current user, newest first.
 * @returns {Promise<{data: SenderRule[], error: import('$lib/errors.js').AppError | null}>}
 */
export async function fetchSenderRules() {
	const { data, error } = await apiFetch('/sender-rules');
	if (error) return { data: [], error: toAppError(error) };
	return { data: data ?? [], error: null };
}

/**
 * Create a new sender rule. The server takes the user from the token.
 * @param {Object} rule
 * @param {string} [rule.sender_domain] - Domain to match (e.g., "example.com")
 * @param {string} [rule.sender_email] - Email to match (takes precedence over domain)
 * @param {SenderRuleAction} rule.action - Action to take
 * @returns {Promise<{data: SenderRule | null, error: import('$lib/errors.js').AppError | null}>}
 */
export async function createSenderRule(rule) {
	if (!rule.sender_domain && !rule.sender_email) {
		return {
			data: null,
			error: toAppError(new Error('Either sender_domain or sender_email must be provided'))
		};
	}
	/** @type {Record<string, string>} */
	const body = { action: rule.action };
	if (rule.sender_email) body.sender_email = rule.sender_email;
	if (rule.sender_domain) body.sender_domain = rule.sender_domain;
	const { data, error } = await apiFetch('/sender-rules', { method: 'POST', body });
	if (error) return { data: null, error: toAppError(error) };
	return { data, error: null };
}

/**
 * Ignore a sender retroactively: creates the ignore rule and, in the same
 * atomic server-side call, rejects their pending events in the New lane AND
 * discards their proposals in the Changes lane.
 * @param {string} senderEmail - The sender's email address
 * @returns {Promise<{data: {rejected_new: number, discarded_changes: number} | null, error: import('$lib/errors.js').AppError | null}>}
 */
export async function ignoreSenderRetroactive(senderEmail) {
	const { data, error } = await apiFetch('/sender-rules/ignore-sender', {
		method: 'POST',
		body: { sender_email: senderEmail }
	});
	if (error) return { data: null, error: toAppError(error) };
	return { data, error: null };
}

/**
 * Delete a sender rule
 * @param {string} ruleId - The rule UUID
 * @returns {Promise<{error: import('$lib/errors.js').AppError | null}>}
 */
export async function deleteSenderRule(ruleId) {
	const { error } = await apiFetch(`/sender-rules/${encodeURIComponent(ruleId)}`, { method: 'DELETE' });
	return { error: error ? toAppError(error) : null };
}
