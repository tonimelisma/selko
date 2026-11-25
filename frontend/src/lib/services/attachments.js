import { apiFetch } from '$lib/api/client.js';
import { toAppError } from '$lib/errors.js';

/**
 * @typedef {Object} Attachment
 * @property {string} id - UUID
 * @property {string} email_id - UUID
 * @property {string} filename
 * @property {string | null} [mime_type]
 * @property {number | null} [size_bytes]
 * @property {string} [ingestion_status] - `stored` once the file can be downloaded
 * @property {string} created_at
 */

/**
 * Fetch attachments for an email, by filename.
 * @param {string} emailId - The email UUID
 * @returns {Promise<{data: Attachment[], error: import('$lib/errors.js').AppError | null}>}
 */
export async function fetchAttachments(emailId) {
	const { data, error } = await apiFetch(`/emails/${encodeURIComponent(emailId)}/attachments`);
	if (error) return { data: [], error: toAppError(error) };
	return { data: data ?? [], error: null };
}

/**
 * Whether an attachment's file is stored and can be downloaded.
 * @param {Attachment} attachment
 */
export function isDownloadable(attachment) {
	return attachment?.ingestion_status === 'stored';
}

/**
 * Fetch an attachment's bytes (with the Bearer token, so no token in a URL).
 * @param {string} attachmentId - The attachment UUID
 * @returns {Promise<{data: Blob | null, error: import('$lib/errors.js').AppError | null}>}
 */
async function fetchAttachmentContent(attachmentId) {
	const { data, error } = await apiFetch(`/attachments/${encodeURIComponent(attachmentId)}/content`, {
		responseType: 'blob',
		headers: { Accept: '*/*' }
	});
	if (error) return { data: null, error: toAppError(error) };
	return { data, error: null };
}

/**
 * Download an attachment: fetch it, then save it through a temporary link.
 * @param {Attachment} attachment
 * @returns {Promise<{error: import('$lib/errors.js').AppError | null}>}
 */
export async function downloadAttachment(attachment) {
	const { data, error } = await fetchAttachmentContent(attachment.id);
	if (error || !data) return { error: error ?? toAppError(new Error('Download failed')) };
	const url = URL.createObjectURL(data);
	try {
		const link = document.createElement('a');
		link.href = url;
		link.download = attachment.filename || 'attachment';
		link.rel = 'noopener';
		document.body.appendChild(link);
		link.click();
		link.remove();
	} finally {
		setTimeout(() => URL.revokeObjectURL(url), 0);
	}
	return { error: null };
}
