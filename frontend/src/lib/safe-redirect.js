/**
 * Where to send a user after sign-in, from a `next` query parameter.
 *
 * Only same-origin paths are honoured, so a crafted link cannot bounce a
 * freshly signed-in user to another site. Anything else falls back to the app.
 *
 * @param {string | null | undefined} next
 * @param {string} [fallback='/app']
 * @returns {string}
 */
export function safeNextPath(next, fallback = '/app') {
	if (typeof next !== 'string' || next === '') return fallback;
	if (!next.startsWith('/') || next.startsWith('//') || next.startsWith('/\\')) return fallback;
	try {
		const resolved = new URL(next, 'https://selko.invalid');
		if (resolved.origin !== 'https://selko.invalid') return fallback;
		return resolved.pathname + resolved.search + resolved.hash;
	} catch {
		return fallback;
	}
}
