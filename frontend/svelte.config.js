import adapter from '@sveltejs/adapter-static';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	kit: {
		adapter: adapter({
			fallback: 'index.html'
		}),
		output: {
			// Safari can intermittently reject split route imports with an empty
			// JavaScript MIME type even when the CDN serves the chunks correctly.
			// A single bundle removes that dynamic-import failure path entirely.
			bundleStrategy: 'single',
			// SvelteKit recommends preload-js for iOS: it avoids modulepreload's
			// Safari-specific request path while still preventing an import waterfall.
			preloadStrategy: 'preload-js'
		}
	}
};

export default config;
