import { defineConfig } from 'vitest/config';
import { svelte } from '@sveltejs/vite-plugin-svelte';

export default defineConfig({
	plugins: [
		svelte({
			compilerOptions: {
				// Enable runes for Svelte 5
				runes: true
			}
		})
	],
	test: {
		include: ['src/**/*.{test,spec}.{js,ts}', 'tests/**/*.{test,spec}.{js,ts}'],
		exclude: ['tests/e2e/**'],
		globals: true,
		environment: 'jsdom',
		setupFiles: ['./vitest.setup.js'],
		coverage: {
			provider: 'v8',
			reporter: ['text', 'json', 'html'],
			include: ['src/lib/**/*.js'],
			exclude: ['src/lib/**/*.test.js', 'src/lib/**/*.spec.js']
		},
		alias: {
			$lib: new URL('./src/lib', import.meta.url).pathname,
			'$app/navigation': new URL('./vitest.setup.js', import.meta.url).pathname,
			'$app/stores': new URL('./vitest.setup.js', import.meta.url).pathname
		}
	},
	resolve: {
		conditions: ['browser']
	}
});
