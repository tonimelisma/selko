import { describe, it, expect } from 'vitest';
import { formatEventDateTime } from '../format-event-datetime.js';

/** @type {(key: string) => string} */
const t = (key) => (key === 'events.allDay' ? 'All Day' : key);

describe('formatEventDateTime', () => {
	it('formats a timed event with start and end', () => {
		const result = formatEventDateTime(
			{ all_day: false, start_datetime: '2026-07-16T15:00:00Z', end_datetime: '2026-07-16T16:00:00Z' },
			t
		);
		expect(result).toContain('-');
		expect(result).not.toContain('All Day');
	});

	it('formats a timed event with no end', () => {
		const result = formatEventDateTime(
			{ all_day: false, start_datetime: '2026-07-16T15:00:00Z' },
			t
		);
		expect(result.length).toBeGreaterThan(0);
	});

	it('returns empty string for a timed event with no start', () => {
		expect(formatEventDateTime({ all_day: false }, t)).toBe('');
	});

	it('formats a single-day all-day event with a date and "All Day"', () => {
		// Stored as local-midnight..local-23:59:59 (America/Los_Angeles, UTC-7 in summer)
		const result = formatEventDateTime(
			{ all_day: true, start_datetime: '2026-07-16T07:00:00Z', end_datetime: '2026-07-17T06:59:59Z' },
			t
		);
		expect(result).toContain('All Day');
		expect(result).not.toContain('–');
	});

	it('formats a multi-day all-day event with a date range', () => {
		// Worked example from the spec: a 3-day closure, Aug 12-14 local (America/Los_Angeles)
		const result = formatEventDateTime(
			{ all_day: true, start_datetime: '2026-08-12T07:00:00Z', end_datetime: '2026-08-15T06:59:59Z' },
			t
		);
		expect(result).toContain('All Day');
		expect(result).toContain('–');
	});

	it('formats an all-day event with no end_datetime', () => {
		const result = formatEventDateTime({ all_day: true, start_datetime: '2026-07-16T07:00:00Z' }, t);
		expect(result).toContain('All Day');
		expect(result).not.toContain('–');
	});

	it('returns just the all-day label when start_datetime is null', () => {
		expect(formatEventDateTime({ all_day: true, start_datetime: null }, t)).toBe('All Day');
	});
});
