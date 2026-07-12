import adapter from '@sveltejs/adapter-static';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	kit: {
		adapter: adapter({
			fallback: 'index.html'
		}),
		output: {
			// Official Safari/iOS-friendly strategy if any JS preloads slip through.
			// Primary fix is hooks.server.js (no JS preloads); this is belt-and-suspenders.
			preloadStrategy: 'preload-js'
		}
	}
};

export default config;
