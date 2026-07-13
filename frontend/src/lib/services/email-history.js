import { supabase } from '$lib/supabase.js';
import { parseSupabaseError } from '$lib/errors.js';
import { reprocessEmail } from '$lib/api/backend.js';

/**
 * Fetch the narrow user-facing processing history. Event sources are joined only
 * to display structured outcomes already known by the normal pipeline.
 * @param {{limit?: number, offset?: number}} [options]
 */
export async function fetchEmailHistory(options = {}) {
	const { limit = 20, offset = 0 } = options;
	try {
		const { data, error, count } = await supabase
			.from('emails')
			.select(
				'id,email_provider,subject,from_email,from_name,date_sent,processing_status,processing_error,processing_outcome,processing_explanation,processed_at,event_sources(id,event_id,source_type,is_undone,change_set,events(id,title,status))',
				{ count: 'exact' }
			)
			.in('processing_status', ['processed', 'failed'])
			.order('date_sent', { ascending: false })
			.range(offset, offset + limit - 1);
		if (error) throw error;
		return { data: data ?? [], count, error: null };
	} catch (error) {
		return { data: [], count: null, error: parseSupabaseError(error) };
	}
}

/**
 * Reprocess an email, returning the API error without mutating the visible row
 * until the next refresh confirms the queued state.
 * @param {string} emailId
 */
export async function queueEmailReprocess(emailId) {
	return reprocessEmail(emailId);
}
