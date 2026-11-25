// @ts-nocheck — node built-ins; the app's jsconfig has no Node types.
// The web app talks only to Selko's API (03-api-auth-web.md §A.6). This guard
// fails when Supabase client code — an import, a `supabase.` call, a PostgREST
// `.from(...)` query on a client or an `.rpc(...)` — comes back into src.
import { describe, it, expect } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative, resolve } from 'node:path';

// vitest runs from frontend/ (vitest.config.js); the file-count check below
// fails loudly if that ever stops being true.
const SRC = resolve(process.cwd(), 'src');

/** @param {string} dir @returns {string[]} */
function sourceFiles(dir) {
	/** @type {string[]} */
	const out = [];
	for (const name of readdirSync(dir)) {
		const path = join(dir, name);
		if (statSync(path).isDirectory()) {
			if (name === '__tests__') continue;
			out.push(...sourceFiles(path));
		} else if (/\.(js|ts|svelte)$/.test(name) && !/\.(test|spec)\.(js|ts)$/.test(name)) {
			out.push(path);
		}
	}
	return out;
}

const FORBIDDEN = [
	{ name: '@supabase import', pattern: /@supabase/ },
	{ name: 'supabase client use', pattern: /\bsupabase\s*\./i },
	{ name: 'PostgREST .from( on a client', pattern: /\b(supabase|client|db|storage)\s*\.\s*from\s*\(/i },
	{ name: '.rpc( call', pattern: /\.rpc\s*\(/ },
	{ name: 'VITE_SUPABASE_* env', pattern: /VITE_SUPABASE_/ }
];

describe('no Supabase in the web app', () => {
	const files = sourceFiles(SRC);

	it('scans a real file set', () => {
		// A guard over an empty set passes vacuously.
		expect(files.length).toBeGreaterThan(40);
		expect(files.some((f) => f.endsWith(join('lib', 'api', 'client.js')))).toBe(true);
	});

	for (const { name, pattern } of FORBIDDEN) {
		it(`has no ${name}`, () => {
			const offenders = files
				.filter((file) => pattern.test(readFileSync(file, 'utf8')))
				.map((file) => relative(SRC, file));
			expect(offenders).toEqual([]);
		});
	}
});
