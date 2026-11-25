// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';

const mockApiFetch = vi.fn();
vi.mock('$lib/api/client.js', () => ({
	apiFetch: (...args) => mockApiFetch(...args)
}));

const mockReprocess = vi.fn();
vi.mock('$lib/api/backend.js', () => ({
	reprocessEmail: (...args) => mockReprocess(...args)
}));

const { fetchEmailHistory, fetchEmailProcessingState, queueEmailReprocess } = await import(
	'../services/email-history.js'
);

describe('email history service', () => {
	beforeEach(() => {
		mockApiFetch.mockReset();
		mockReprocess.mockReset();
	});

	it('reads a page of GET /emails/history and maps {items, total}', async () => {
		const rows = [
			{ id: 'e1', processing_status: 'processed', event_sources: [] },
			{ id: 'e2', processing_status: 'skipped', processing_outcome: 'calendar_invite', event_sources: [] }
		];
		mockApiFetch.mockResolvedValue({ data: { items: rows, total: 7 }, error: null, status: 200 });

		const result = await fetchEmailHistory({ limit: 2, offset: 4 });

		expect(mockApiFetch).toHaveBeenCalledWith('/emails/history', { query: { limit: 2, offset: 4 } });
		expect(result).toEqual({ data: rows, count: 7, error: null });
	});

	it('uses the default page and clamps it', async () => {
		mockApiFetch.mockResolvedValue({ data: { items: [], total: 0 }, error: null, status: 200 });

		await fetchEmailHistory();
		await fetchEmailHistory({ limit: 10_000 });

		expect(mockApiFetch.mock.calls[0][1]).toEqual({ query: { limit: 20, offset: 0 } });
		expect(mockApiFetch.mock.calls[1][1]).toEqual({ query: { limit: 500, offset: 0 } });
	});

	it('returns an empty page on failure', async () => {
		mockApiFetch.mockResolvedValue({ data: null, error: { message: 'boom', status: 500 }, status: 500 });

		const result = await fetchEmailHistory();

		expect(result.data).toEqual([]);
		expect(result.count).toBeNull();
		expect(result.error.message).toBe('boom');
	});

	it('polls one email’s processing state', async () => {
		const state = { id: 'e1', processing_status: 'pending' };
		mockApiFetch.mockResolvedValue({ data: state, error: null, status: 200 });

		const result = await fetchEmailProcessingState('e1');

		expect(mockApiFetch).toHaveBeenCalledWith('/emails/e1/processing-state');
		expect(result).toEqual({ data: state, error: null });
	});

	it('queues a reprocess through the backend client', async () => {
		mockReprocess.mockResolvedValue({ data: { email_id: 'e1', processing_status: 'pending' }, error: null });

		await queueEmailReprocess('e1');

		expect(mockReprocess).toHaveBeenCalledWith('e1');
	});
});
