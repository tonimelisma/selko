import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [tailwindcss(), sveltekit()],
	build: {
		// Safari cancels Vite modulepreload link fetches for same-origin chunks
		// (Network shows status "—", no request/response headers), then throws
		// TypeError: '' is not a valid JavaScript MIME type and SvelteKit paints 500.
		// Skip dependency preloads; keep stylesheet injection via the runtime helper.
		modulePreload: {
			polyfill: false,
			resolveDependencies: () => []
		}
	}
});
