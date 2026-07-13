// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';

const mockSupabase = { from: vi.fn() };

vi.mock('$lib/supabase.js', () => ({
	supabase: mockSupabase
}));

vi.mock('$lib/api/backend.js', () => ({
	reprocessEmail: vi.fn()
}));

const { fetchEmailHistory } = await import('../services/email-history.js');

describe('fetchEmailHistory', () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it('includes skipped calendar-invite rows alongside processed/failed', async () => {
		const query = {
			select: vi.fn().mockReturnThis(),
			or: vi.fn().mockReturnThis(),
			order: vi.fn().mockReturnThis(),
			range: vi.fn().mockResolvedValue({ data: [], error: null, count: 0 })
		};
		mockSupabase.from.mockReturnValue(query);

		await fetchEmailHistory();

		expect(query.or).toHaveBeenCalledWith(
			expect.stringContaining('processing_status.in.(processed,failed)')
		);
		expect(query.or).toHaveBeenCalledWith(
			expect.stringContaining('and(processing_status.eq.skipped,processing_outcome.eq.calendar_invite)')
		);
	});
});
