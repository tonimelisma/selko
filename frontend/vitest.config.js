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
		// Pin test-time env so CI (which has no frontend/.env) matches local runs.
		// Without this, $lib/supabase.js calls createClient(undefined, undefined) at
		// module scope and every service importer throws on import in CI.
		env: {
			VITE_SUPABASE_URL: 'http://localhost:54321',
			VITE_SUPABASE_ANON_KEY: 'test-anon-key'
		},
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
	},
	// Ensure intl-messageformat and related packages resolve correctly in test environment
	ssr: {
		noExternal: ['svelte-i18n', 'intl-messageformat', '@formatjs/icu-messageformat-parser', '@formatjs/fast-memoize', '@formatjs/ecma402-abstract']
	}
});
