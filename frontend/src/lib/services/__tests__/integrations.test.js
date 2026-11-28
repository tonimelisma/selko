// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { mockIntegrations } from '../../../../tests/fixtures/mock-data.js';

const mockApiFetch = vi.fn();
vi.mock('$lib/api/client.js', () => ({
	apiFetch: (...args) => mockApiFetch(...args)
}));

const { fetchIntegrations, disconnectIntegrations, fetchCalendarRecovery } = await import(
	'../integrations.js'
);

describe('integrations service', () => {
	beforeEach(() => {
		mockApiFetch.mockReset();
	});

	describe('fetchIntegrations', () => {
		it('fetches the user’s integrations from GET /integrations', async () => {
			mockApiFetch.mockResolvedValue({ data: mockIntegrations, error: null, status: 200 });

			const result = await fetchIntegrations();

			expect(mockApiFetch).toHaveBeenCalledWith('/integrations');
			expect(result.data).toEqual(mockIntegrations);
			expect(result.count).toBe(mockIntegrations.length);
			expect(result.error).toBeNull();
		});

		it('handles errors gracefully', async () => {
			mockApiFetch.mockResolvedValue({ data: null, error: { message: 'Unable to connect', status: 0, code: 'NETWORK_ERROR' }, status: 0 });

			const result = await fetchIntegrations();

			expect(result.data).toEqual([]);
			expect(result.count).toBeNull();
			expect(result.error.code).toBe('NETWORK_ERROR');
		});

		it('returns an empty list when the body is empty', async () => {
			mockApiFetch.mockResolvedValue({ data: null, error: null, status: 200 });

			const result = await fetchIntegrations();

			expect(result.data).toEqual([]);
			expect(result.count).toBe(0);
		});
	});

	describe('disconnectIntegrations', () => {
		// Validates: SEL-548
		it('deletes the given ids in one request', async () => {
			mockApiFetch.mockResolvedValue({ data: { deleted: 2 }, error: null, status: 200 });

			const result = await disconnectIntegrations(['gmail-1', 'gcal-1']);

			expect(mockApiFetch).toHaveBeenCalledWith('/integrations/disconnect', {
				method: 'POST',
				body: { integration_ids: ['gmail-1', 'gcal-1'] }
			});
			expect(result).toEqual({ data: true, error: null });
		});

		it('returns the API error', async () => {
			mockApiFetch.mockResolvedValue({ data: null, error: { message: 'Integration not found', status: 404 }, status: 404 });

			const result = await disconnectIntegrations(['other-user']);

			expect(result.data).toBeNull();
			expect(result.error.status).toBe(404);
		});
	});

	describe('fetchCalendarRecovery', () => {
		it('unwraps the latest Google Calendar recovery', async () => {
			const recovery = { id: 'r1', provider: 'google_calendar', status: 'processing' };
			mockApiFetch.mockResolvedValue({ data: { recovery }, error: null, status: 200 });

			const result = await fetchCalendarRecovery();

			expect(mockApiFetch).toHaveBeenCalledWith('/integrations/recovery', {
				query: { provider: 'google_calendar' }
			});
			expect(result).toEqual({ data: recovery, error: null });
		});

		it('returns null without an error when there is no recovery', async () => {
			mockApiFetch.mockResolvedValue({ data: { recovery: null }, error: null, status: 200 });

			expect(await fetchCalendarRecovery()).toEqual({ data: null, error: null });
		});
	});
});
