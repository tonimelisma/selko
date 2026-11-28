import { describe, it, expect } from 'vitest';
import { safeNextPath } from '../safe-redirect.js';

// Validates: SEL-517
describe('safeNextPath', () => {
	it('keeps a same-origin path with its query', () => {
		expect(safeNextPath('/app/events/e1?tab=source')).toBe('/app/events/e1?tab=source');
	});

	it.each([
		[null],
		[''],
		['https://evil.example/steal'],
		['//evil.example/steal'],
		['/\\evil.example'],
		['javascript:alert(1)'],
		['app/settings']
	])('falls back to the app for %s', (next) => {
		expect(safeNextPath(next)).toBe('/app');
	});
});
