import { describe, it, expect } from 'vitest';
import { formatChangeValue } from '../format-change-value.js';

describe('formatChangeValue', () => {
	it('does not treat TechCorp-style location text as a datetime', () => {
		expect(formatChangeValue('TechCorp HQ, Building 5, Conference Room A')).toBe(
			'TechCorp HQ, Building 5, Conference Room A'
		);
	});

	it('formats valid ISO datetimes', () => {
		const result = formatChangeValue('2026-07-15T15:00:00.000Z');
		expect(result).not.toBe('Invalid Date');
		expect(result).not.toBe('2026-07-15T15:00:00.000Z');
	});

	it('returns none label for empty values', () => {
		expect(formatChangeValue(null, 'None')).toBe('None');
		expect(formatChangeValue('', 'None')).toBe('None');
	});

	it('formats booleans', () => {
		expect(formatChangeValue(true)).toBe('Yes');
		expect(formatChangeValue(false)).toBe('No');
	});
});
