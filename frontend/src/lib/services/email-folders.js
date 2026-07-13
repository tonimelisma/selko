import * as backend from '$lib/api/backend.js';
import { supabase } from '$lib/supabase.js';

/** @param {'gmail' | 'outlook'} provider */
export async function fetchEmailFolders(provider) {
	try {
		if (typeof supabase.from !== 'function') {
			return { data: [], error: null };
		}
		const { data, error } = await supabase
			.from('email_folders')
			.select('id,provider,name,full_path,classification_decision,classification_reason,user_override,is_included,is_system')
			.eq('provider', provider)
			.eq('is_system', false)
			.order('full_path');
		if (error) throw error;
		return { data: data ?? [], error: null };
	} catch (error) {
		return {
			data: [],
			error: { message: error instanceof Error ? error.message : 'Failed to load folders', status: 0 }
		};
	}
}

/**
 * @param {'gmail' | 'outlook'} provider
 * @param {string} folderId
 * @param {boolean} isIncluded
 */
export async function updateEmailFolder(provider, folderId, isIncluded) {
	try {
		if (typeof backend.updateEmailFolder !== 'function') {
			return { data: null, error: { message: 'Folder updates are unavailable', status: 0 } };
		}
		return await backend.updateEmailFolder(provider, folderId, isIncluded);
	} catch (error) {
		return {
			data: null,
			error: { message: error instanceof Error ? error.message : 'Failed to update folder', status: 0 }
		};
	}
}
