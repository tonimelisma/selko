/**
 * Return the two-character account avatar used by the Warmth shell.
 * @param {string | undefined | null} email
 */
export function initialsFromEmail(email) {
	const localPart = (email || '').split('@')[0].trim();
	if (!localPart) return '?';
	const letters = localPart.replace(/[^a-z0-9]/gi, '');
	return (letters || localPart).slice(0, 2).toUpperCase();
}

/**
 * Pick a stable sender tile color from the Warmth avatar palette.
 * @param {string | undefined | null} sender
 */
export function senderAvatarTone(sender) {
	const value = sender || '';
	let hash = 0;
	for (let index = 0; index < value.length; index += 1) {
		hash = (hash * 31 + value.charCodeAt(index)) | 0;
	}
	return ['primary', 'accent', 'success'][Math.abs(hash) % 3];
}
