import * as backend from '$lib/api/backend.js';

/**
 * The provider's user-configurable folders (system folders excluded).
 * @param {'gmail' | 'outlook'} provider
 */
export async function fetchEmailFolders(provider) {
	return backend.fetchEmailFolders(provider);
}

/**
 * @param {'gmail' | 'outlook'} provider
 * @param {string} folderId
 * @param {boolean} isIncluded
 */
export async function updateEmailFolder(provider, folderId, isIncluded) {
	return backend.updateEmailFolder(provider, folderId, isIncluded);
}
