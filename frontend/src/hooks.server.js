/**
 * Do not preload JS (Safari cancels modulepreload → empty MIME → blank app).
 * Do not preload every Inter unicode-range font (unused-preload noise; CSS loads them).
 *
 * @type {import('@sveltejs/kit').Handle}
 */
export async function handle({ event, resolve }) {
	return resolve(event, {
		preload: ({ type }) => type === 'css'
	});
}
