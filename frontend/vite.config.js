import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [tailwindcss(), sveltekit()],
	build: {
		// Match hooks.server.js: do not inject <link rel="modulepreload"> for JS.
		modulePreload: false
	}
});
