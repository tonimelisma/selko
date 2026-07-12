/**
 * Skip JS modulepreload / preload links in HTML.
 *
 * Safari (and some content blockers) can cancel `<link rel="modulepreload">`
 * fetches for same-origin chunks. That leaves an empty MIME type on the
 * cancelled response; the matching `import()` then throws
 * `TypeError: '' is not a valid JavaScript MIME type`, and SvelteKit paints
 * a client-side 500 even though the CDN returns 200 + application/javascript.
 *
 * CSS preloads are kept — they do not use the module credentials path.
 *
 * @type {import('@sveltejs/kit').Handle}
 */
export async function handle({ event, resolve }) {
	return resolve(event, {
		preload: ({ type }) => type === 'css' || type === 'font'
	});
}
