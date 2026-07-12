import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [tailwindcss(), sveltekit()],
	build: {
		// Do not inject runtime <link rel="modulepreload"> for dynamic imports.
		// Safari can cancel those fetches and then fail the real import() with
		// TypeError: '' is not a valid JavaScript MIME type.
		modulePreload: false
	}
});
