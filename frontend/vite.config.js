import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { defineConfig } from 'vite';

export default defineConfig({
	plugins: [tailwindcss(), sveltekit()],
	build: {
		// With kit.output.bundleStrategy: 'single', keep Vite from injecting
		// modulepreload for a dependency graph that no longer exists.
		modulePreload: false
	}
});
