import { supabase } from '$lib/supabase.js';
import { parseSupabaseError } from '$lib/errors.js';

/**
 * @typedef {'email_fetch' | 'email_process' | 'calendar_sync'} JobType
 */

/**
 * @typedef {'pending' | 'processing' | 'completed' | 'failed' | 'dead'} JobStatus
 */

/**
 * @typedef {Object} Job
 * @property {string} id - UUID
 * @property {string} user_id - UUID
 * @property {JobType} job_type
 * @property {Object} payload
 * @property {JobStatus} status
 * @property {number} priority
 * @property {number} attempts
 * @property {number} max_attempts
 * @property {string | null} last_error
 * @property {string} [scheduled_at]
 * @property {string} [started_at]
 * @property {string} [completed_at]
 * @property {string} created_at
 */

/**
 * @typedef {import('$lib/types.js').SupabaseServiceResult} SupabaseServiceResult
 */

/**
 * @typedef {Object} FetchJobsOptions
 * @property {number} [limit=50] - Maximum number of jobs to fetch
 * @property {number} [offset=0] - Offset for pagination
 * @property {JobStatus[]} [statuses] - Filter by status(es)
 * @property {JobType[]} [types] - Filter by job type(s)
 */

/**
 * Fetch jobs for the current user
 * @param {FetchJobsOptions} [options={}]
 * @returns {Promise<SupabaseServiceResult<Job[]>>}
 */
export async function fetchJobs(options = {}) {
	const { limit = 50, offset = 0, statuses, types } = options;

	try {
		let query = supabase
			.from('jobs')
			.select('*', { count: 'exact' })
			.order('created_at', { ascending: false })
			.range(offset, offset + limit - 1);

		if (statuses && statuses.length > 0) {
			query = query.in('status', statuses);
		}
		if (types && types.length > 0) {
			query = query.in('job_type', types);
		}

		const { data, count, error } = await query;

		if (error) throw error;

		return { data: data ?? [], count, error: null };
	} catch (error) {
		return { data: [], count: null, error: parseSupabaseError(error) };
	}
}

/**
 * Get a single job by ID
 * @param {string} jobId - The job UUID
 * @returns {Promise<SupabaseServiceResult<Job | null>>}
 */
export async function getJob(jobId) {
	try {
		const { data, error } = await supabase.from('jobs').select('*').eq('id', jobId).single();

		if (error) throw error;

		return { data, error: null };
	} catch (error) {
		return { data: null, error: parseSupabaseError(error) };
	}
}

/**
 * Get counts of pending jobs grouped by type
 * @returns {Promise<{data: Record<JobType, number>, error: import('$lib/errors.js').SupabaseError | null}>}
 */
export async function getPendingJobCounts() {
	try {
		const { data, error } = await supabase
			.from('jobs')
			.select('job_type')
			.eq('status', 'pending');

		if (error) throw error;

		const counts = /** @type {Record<JobType, number>} */ ({});
		for (const job of data ?? []) {
			counts[job.job_type] = (counts[job.job_type] || 0) + 1;
		}

		return { data: counts, error: null };
	} catch (error) {
		return { data: /** @type {Record<JobType, number>} */ ({}), error: parseSupabaseError(error) };
	}
}

/**
 * Check if any jobs are currently processing
 * @returns {Promise<{isProcessing: boolean, error: import('$lib/errors.js').SupabaseError | null}>}
 */
export async function hasProcessingJobs() {
	try {
		const { count, error } = await supabase
			.from('jobs')
			.select('id', { count: 'exact', head: true })
			.eq('status', 'processing');

		if (error) throw error;

		return { isProcessing: (count ?? 0) > 0, error: null };
	} catch (error) {
		return { isProcessing: false, error: parseSupabaseError(error) };
	}
}
