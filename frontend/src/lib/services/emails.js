import { supabase } from '$lib/supabase.js';
import { parseSupabaseError } from '$lib/errors.js';

/**
 * @typedef {import('$lib/types.js').Email} Email
 * @typedef {import('$lib/types.js').SupabaseServiceResult} SupabaseServiceResult
 */

/**
 * @typedef {Object} FetchEmailsOptions
 * @property {number} [limit=50] - Maximum number of emails to fetch
 * @property {number} [offset=0] - Offset for pagination
 * @property {boolean} [excludeSpam=true] - Exclude spam emails
 * @property {boolean} [excludeTrash=true] - Exclude trash emails
 * @property {boolean} [excludePromotions=false] - Exclude promotional emails
 * @property {boolean} [unreadOnly=false] - Only fetch unread emails
 */

/**
 * Fetch emails for the current user
 * @param {FetchEmailsOptions} [options={}]
 * @returns {Promise<SupabaseServiceResult<Email[]>>}
 */
export async function fetchEmails(options = {}) {
	const {
		limit = 50,
		offset = 0,
		excludeSpam = true,
		excludeTrash = true,
		excludePromotions = false,
		unreadOnly = false
	} = options;

	try {
		let query = supabase
			.from('emails')
			.select('*', { count: 'exact' })
			.order('date_sent', { ascending: false })
			.range(offset, offset + limit - 1);

		if (excludeSpam) {
			query = query.eq('is_spam', false);
		}
		if (excludeTrash) {
			query = query.eq('is_trash', false);
		}
		if (excludePromotions) {
			query = query.eq('is_promotions', false);
		}
		if (unreadOnly) {
			query = query.eq('is_unread', true);
		}

		const { data, error, count } = await query;

		if (error) throw error;

		return { data: data ?? [], count, error: null };
	} catch (error) {
		return { data: [], count: null, error: parseSupabaseError(error) };
	}
}

/**
 * Get a single email by ID
 * @param {string} emailId - The email UUID
 * @returns {Promise<SupabaseServiceResult<Email | null>>}
 */
export async function getEmail(emailId) {
	try {
		const { data, error } = await supabase.from('emails').select('*').eq('id', emailId).single();

		if (error) throw error;

		return { data, error: null };
	} catch (error) {
		return { data: null, error: parseSupabaseError(error) };
	}
}

/**
 * Update email read status (marks as read/unread)
 * Note: This updates the local database flag only, not Gmail
 * @param {string} emailId - The email UUID
 * @param {boolean} isUnread - Whether the email should be marked as unread
 * @returns {Promise<SupabaseServiceResult<Email | null>>}
 */
export async function updateEmailReadStatus(emailId, isUnread) {
	try {
		const { data, error } = await supabase
			.from('emails')
			.update({ is_unread: isUnread })
			.eq('id', emailId)
			.select()
			.single();

		if (error) throw error;

		return { data, error: null };
	} catch (error) {
		return { data: null, error: parseSupabaseError(error) };
	}
}
