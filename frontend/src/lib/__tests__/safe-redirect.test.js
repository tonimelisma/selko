import { describe, it, expect } from 'vitest';
import { safeNextPath } from '../safe-redirect.js';

describe('safeNextPath', () => {
	it('keeps a same-origin path with its query', () => {
		expect(safeNextPath('/oauth/consent?authorization_id=abc')).toBe('/oauth/consent?authorization_id=abc');
	});

	it.each([
		[null],
		[''],
		['https://evil.example/steal'],
		['//evil.example/steal'],
		['/\\evil.example'],
		['javascript:alert(1)'],
		['oauth/consent']
	])('falls back to the app for %s', (next) => {
		expect(safeNextPath(next)).toBe('/app');
	});
});
