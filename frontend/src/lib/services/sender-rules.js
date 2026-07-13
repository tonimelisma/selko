import { supabase } from '$lib/supabase.js';
import { parseSupabaseError } from '$lib/errors.js';

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
 * Fetch all sender rules for the current user
 * @returns {Promise<{data: SenderRule[], error: import('$lib/errors.js').SupabaseError | null}>}
 */
export async function fetchSenderRules() {
	try {
		const { data, error } = await supabase
			.from('sender_rules')
			.select('*')
			.order('created_at', { ascending: false });

		if (error) throw error;

		return { data: data ?? [], error: null };
	} catch (error) {
		return { data: [], error: parseSupabaseError(error) };
	}
}

/**
 * Create a new sender rule
 * @param {Object} rule
 * @param {string} [rule.sender_domain] - Domain to match (e.g., "example.com")
 * @param {string} [rule.sender_email] - Email to match (takes precedence over domain)
 * @param {SenderRuleAction} rule.action - Action to take
 * @returns {Promise<{data: SenderRule | null, error: import('$lib/errors.js').SupabaseError | null}>}
 */
export async function createSenderRule(rule) {
	try {
		// Validate that at least one of domain or email is provided
		if (!rule.sender_domain && !rule.sender_email) {
			throw new Error('Either sender_domain or sender_email must be provided');
		}

		const {
			data: { user }
		} = await supabase.auth.getUser();
		if (!user) throw new Error('Not authenticated');

		const { data, error } = await supabase
			.from('sender_rules')
			.insert({ ...rule, user_id: user.id })
			.select()
			.single();

		if (error) throw error;

		return { data, error: null };
	} catch (error) {
		return { data: null, error: parseSupabaseError(error) };
	}
}

/**
 * Ignore a sender retroactively: creates the ignore rule and, in the same
 * atomic server-side call, rejects their pending events in the New lane AND
 * discards their proposals in the Changes lane.
 * @param {string} senderEmail - The sender's email address
 * @returns {Promise<{data: {rejected_new: number, discarded_changes: number} | null, error: import('$lib/errors.js').SupabaseError | null}>}
 */
export async function ignoreSenderRetroactive(senderEmail) {
	try {
		const { data, error } = await supabase.rpc('ignore_sender_and_reject_pending', {
			p_sender_email: senderEmail
		});
		if (error) throw error;
		return { data, error: null };
	} catch (error) {
		return { data: null, error: parseSupabaseError(error) };
	}
}

/**
 * Delete a sender rule
 * @param {string} ruleId - The rule UUID
 * @returns {Promise<{error: import('$lib/errors.js').SupabaseError | null}>}
 */
export async function deleteSenderRule(ruleId) {
	try {
		const { error } = await supabase.from('sender_rules').delete().eq('id', ruleId);

		if (error) throw error;

		return { error: null };
	} catch (error) {
		return { error: parseSupabaseError(error) };
	}
}

/**
 * Check if a sender matches any rule
 * @param {string} senderEmail - The sender's email address
 * @returns {Promise<{data: SenderRule | null, error: import('$lib/errors.js').SupabaseError | null}>}
 */
export async function findMatchingRule(senderEmail) {
	try {
		const domain = senderEmail.split('@')[1];

		// Check for exact email match first, then domain match
		const { data, error } = await supabase
			.from('sender_rules')
			.select('*')
			.or(`sender_email.eq.${senderEmail},sender_domain.eq.${domain}`)
			.order('sender_email', { ascending: false, nullsFirst: false }) // Email matches first
			.limit(1)
			.maybeSingle();

		if (error) throw error;

		return { data, error: null };
	} catch (error) {
		return { data: null, error: parseSupabaseError(error) };
	}
}
