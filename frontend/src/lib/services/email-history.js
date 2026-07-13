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
			// Calendar invites are skipped (never claimed/processed), but per product
			// decision they must still show up here as the audit trail — not just
			// silently vanish. Other skipped emails (e.g. ignored senders) stay hidden.
			.or(
				'processing_status.in.(processed,failed),' +
					'and(processing_status.eq.skipped,processing_outcome.eq.calendar_invite)'
			)
			.order('date_sent', { ascending: false })
			.order('id', { ascending: false })
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

/**
 * Fetch only the processing fields needed while a user-initiated reprocess is
 * running. Keeping this query narrow avoids refreshing the whole History page.
 * @param {string} emailId
 */
export async function fetchEmailProcessingState(emailId) {
	try {
		const { data, error } = await supabase
			.from('emails')
			.select('id,processing_status,processing_error,processing_outcome,processing_explanation,processed_at')
			.eq('id', emailId)
			.maybeSingle();
		if (error) throw error;
		return { data, error: null };
	} catch (error) {
		return { data: null, error: parseSupabaseError(error) };
	}
}
