import { supabase } from '$lib/supabase.js';
import { parseSupabaseError } from '$lib/errors.js';

/**
 * @typedef {Object} Attachment
 * @property {string} id - UUID
 * @property {string} user_id - UUID
 * @property {string} email_id - UUID
 * @property {string} [gmail_attachment_id]
 * @property {string} filename
 * @property {string} mime_type
 * @property {number} size_bytes
 * @property {string} [storage_path]
 * @property {string} [content_hash]
 * @property {string} created_at
 */

/**
 * @typedef {import('$lib/types.js').SupabaseServiceResult} SupabaseServiceResult
 */

/**
 * Fetch attachments for an email
 * @param {string} emailId - The email UUID
 * @returns {Promise<SupabaseServiceResult<Attachment[]>>}
 */
export async function fetchAttachments(emailId) {
	try {
		const { data, error } = await supabase
			.from('attachments')
			.select('*')
			.eq('email_id', emailId)
			.order('filename', { ascending: true });

		if (error) throw error;

		return { data: data ?? [], error: null };
	} catch (error) {
		return { data: [], error: parseSupabaseError(error) };
	}
}

/**
 * Get a single attachment by ID
 * @param {string} attachmentId - The attachment UUID
 * @returns {Promise<SupabaseServiceResult<Attachment | null>>}
 */
export async function getAttachment(attachmentId) {
	try {
		const { data, error } = await supabase
			.from('attachments')
			.select('*')
			.eq('id', attachmentId)
			.single();

		if (error) throw error;

		return { data, error: null };
	} catch (error) {
		return { data: null, error: parseSupabaseError(error) };
	}
}

/**
 * Download attachment content from Supabase Storage
 * @param {string} storagePath - The storage path of the attachment
 * @returns {Promise<{data: Blob | null, error: import('$lib/errors.js').SupabaseError | null}>}
 */
export async function downloadAttachment(storagePath) {
	try {
		const { data, error } = await supabase.storage.from('attachments').download(storagePath);

		if (error) throw error;

		return { data, error: null };
	} catch (error) {
		return { data: null, error: parseSupabaseError(error) };
	}
}

/**
 * Get a signed URL for an attachment (for direct browser download)
 * @param {string} storagePath - The storage path of the attachment
 * @param {number} [expiresIn=3600] - URL expiry in seconds (default 1 hour)
 * @returns {Promise<{data: string | null, error: import('$lib/errors.js').SupabaseError | null}>}
 */
export async function getAttachmentUrl(storagePath, expiresIn = 3600) {
	try {
		const { data, error } = await supabase.storage
			.from('attachments')
			.createSignedUrl(storagePath, expiresIn);

		if (error) throw error;

		return { data: data.signedUrl, error: null };
	} catch (error) {
		return { data: null, error: parseSupabaseError(error) };
	}
}
