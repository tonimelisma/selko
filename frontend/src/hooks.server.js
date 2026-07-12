/**
 * Skip JS modulepreload. Safari can cancel those fetches and then fail the
 * matching import() with an empty MIME type.
 *
 * @type {import('@sveltejs/kit').Handle}
 */
export async function handle({ event, resolve }) {
	return resolve(event, {
		preload: ({ type }) => type === 'css'
	});
}
