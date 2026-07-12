import adapter from '@sveltejs/adapter-static';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	kit: {
		adapter: adapter({
			fallback: 'index.html'
		}),
		output: {
			// One JS + one CSS file — avoids Safari failing on multi-chunk dynamic imports.
			bundleStrategy: 'single',
			preloadStrategy: 'preload-js'
		}
	}
};

export default config;
