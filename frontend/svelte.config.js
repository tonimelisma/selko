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
			bundleStrategy: 'single'
		}
	}
};

export default config;
