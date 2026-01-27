import { supabase } from '$lib/supabase.js';
import { parseSupabaseError } from '$lib/errors.js';

/**
 * @typedef {import('$lib/types.js').Integration} Integration
 * @typedef {import('$lib/types.js').IntegrationProvider} IntegrationProvider
 * @typedef {import('$lib/types.js').SupabaseServiceResult} SupabaseServiceResult
 */

/**
 * Fetch all integrations for the current user
 * @returns {Promise<SupabaseServiceResult<Integration[]>>}
 */
export async function fetchIntegrations() {
	try {
		const { data, error, count } = await supabase
			.from('integrations')
			.select('id, user_id, provider, status, provider_email, scopes, last_sync_at, created_at, updated_at', { count: 'exact' })
			.order('created_at', { ascending: false });

		if (error) throw error;

		return { data: data ?? [], count, error: null };
	} catch (error) {
		return { data: [], count: null, error: parseSupabaseError(error) };
	}
}

/**
 * Get a single integration by ID
 * @param {string} integrationId - The integration UUID
 * @returns {Promise<SupabaseServiceResult<Integration | null>>}
 */
export async function getIntegration(integrationId) {
	try {
		const { data, error } = await supabase
			.from('integrations')
			.select('id, user_id, provider, status, provider_email, scopes, last_sync_at, created_at, updated_at')
			.eq('id', integrationId)
			.single();

		if (error) throw error;

		return { data, error: null };
	} catch (error) {
		return { data: null, error: parseSupabaseError(error) };
	}
}

/**
 * Get integration by provider
 * @param {IntegrationProvider} provider - The provider name
 * @returns {Promise<SupabaseServiceResult<Integration | null>>}
 */
export async function getIntegrationByProvider(provider) {
	try {
		const { data, error } = await supabase
			.from('integrations')
			.select('id, user_id, provider, status, provider_email, scopes, last_sync_at, created_at, updated_at')
			.eq('provider', provider)
			.single();

		if (error) {
			// Not found is not an error for this use case
			if (error.code === 'PGRST116') {
				return { data: null, error: null };
			}
			throw error;
		}

		return { data, error: null };
	} catch (error) {
		return { data: null, error: parseSupabaseError(error) };
	}
}

/**
 * Check if a provider is connected and active
 * @param {IntegrationProvider} provider - The provider name
 * @returns {Promise<boolean>}
 */
export async function isProviderConnected(provider) {
	const { data, error } = await getIntegrationByProvider(provider);

	if (error || !data) {
		return false;
	}

	return data.status === 'active';
}
