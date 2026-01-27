// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { mockIntegrations, mockErrors } from '../../../../tests/fixtures/mock-data.js';

// Mock supabase module
const mockFrom = vi.fn();
vi.mock('$lib/supabase.js', () => ({
	supabase: {
		from: (...args) => mockFrom(...args)
	}
}));

// Import after mocking
const { fetchIntegrations, getIntegration, getIntegrationByProvider, isProviderConnected } =
	await import('../integrations.js');

describe('integrations service', () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	describe('fetchIntegrations', () => {
		it('fetches all integrations for user', async () => {
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				order: vi.fn().mockResolvedValue({
					data: mockIntegrations,
					error: null,
					count: mockIntegrations.length
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			const result = await fetchIntegrations();

			expect(mockFrom).toHaveBeenCalledWith('integrations');
			expect(mockQuery.select).toHaveBeenCalledWith(
				'id, user_id, provider, status, provider_email, scopes, last_sync_at, created_at, updated_at',
				{ count: 'exact' }
			);
			expect(mockQuery.order).toHaveBeenCalledWith('created_at', { ascending: false });
			expect(result.data).toEqual(mockIntegrations);
			expect(result.count).toBe(mockIntegrations.length);
			expect(result.error).toBeNull();
		});

		it('excludes sensitive token fields', async () => {
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				order: vi.fn().mockResolvedValue({
					data: mockIntegrations,
					error: null,
					count: mockIntegrations.length
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			await fetchIntegrations();

			// Should NOT include access_token or refresh_token
			const selectArg = mockQuery.select.mock.calls[0][0];
			expect(selectArg).not.toContain('access_token');
			expect(selectArg).not.toContain('refresh_token');
		});

		it('handles errors gracefully', async () => {
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				order: vi.fn().mockResolvedValue({
					data: null,
					error: mockErrors.permissionDenied,
					count: null
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			const result = await fetchIntegrations();

			expect(result.data).toEqual([]);
			expect(result.error?.code).toBe('42501');
		});

		it('returns empty array when data is null', async () => {
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				order: vi.fn().mockResolvedValue({
					data: null,
					error: null,
					count: 0
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			const result = await fetchIntegrations();

			expect(result.data).toEqual([]);
			expect(result.error).toBeNull();
		});
	});

	describe('getIntegration', () => {
		it('fetches a single integration by ID', async () => {
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				eq: vi.fn().mockReturnThis(),
				single: vi.fn().mockResolvedValue({
					data: mockIntegrations[0],
					error: null
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			const result = await getIntegration(mockIntegrations[0].id);

			expect(mockFrom).toHaveBeenCalledWith('integrations');
			expect(mockQuery.eq).toHaveBeenCalledWith('id', mockIntegrations[0].id);
			expect(mockQuery.single).toHaveBeenCalled();
			expect(result.data).toEqual(mockIntegrations[0]);
			expect(result.error).toBeNull();
		});

		it('handles not found', async () => {
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				eq: vi.fn().mockReturnThis(),
				single: vi.fn().mockResolvedValue({
					data: null,
					error: mockErrors.notFound
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			const result = await getIntegration('non-existent');

			expect(result.data).toBeNull();
			expect(result.error).not.toBeNull();
		});
	});

	describe('getIntegrationByProvider', () => {
		it('fetches integration by provider name', async () => {
			const gmailIntegration = mockIntegrations.find((i) => i.provider === 'gmail');
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				eq: vi.fn().mockReturnThis(),
				single: vi.fn().mockResolvedValue({
					data: gmailIntegration,
					error: null
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			const result = await getIntegrationByProvider('gmail');

			expect(mockFrom).toHaveBeenCalledWith('integrations');
			expect(mockQuery.eq).toHaveBeenCalledWith('provider', 'gmail');
			expect(result.data).toEqual(gmailIntegration);
			expect(result.error).toBeNull();
		});

		it('returns null without error when not found', async () => {
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				eq: vi.fn().mockReturnThis(),
				single: vi.fn().mockResolvedValue({
					data: null,
					error: { code: 'PGRST116', message: 'No rows found' }
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			const result = await getIntegrationByProvider('gmail');

			// PGRST116 (not found) should return null without error
			expect(result.data).toBeNull();
			expect(result.error).toBeNull();
		});

		it('returns error for other errors', async () => {
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				eq: vi.fn().mockReturnThis(),
				single: vi.fn().mockResolvedValue({
					data: null,
					error: mockErrors.permissionDenied
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			const result = await getIntegrationByProvider('gmail');

			expect(result.data).toBeNull();
			expect(result.error).not.toBeNull();
			expect(result.error?.code).toBe('42501');
		});
	});

	describe('isProviderConnected', () => {
		it('returns true for active provider', async () => {
			const activeIntegration = mockIntegrations.find(
				(i) => i.provider === 'gmail' && i.status === 'active'
			);
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				eq: vi.fn().mockReturnThis(),
				single: vi.fn().mockResolvedValue({
					data: activeIntegration,
					error: null
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			const result = await isProviderConnected('gmail');

			expect(result).toBe(true);
		});

		it('returns false for expired provider', async () => {
			const expiredIntegration = mockIntegrations.find(
				(i) => i.provider === 'google_photos' && i.status === 'expired'
			);
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				eq: vi.fn().mockReturnThis(),
				single: vi.fn().mockResolvedValue({
					data: expiredIntegration,
					error: null
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			const result = await isProviderConnected('google_photos');

			expect(result).toBe(false);
		});

		it('returns false when provider not found', async () => {
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				eq: vi.fn().mockReturnThis(),
				single: vi.fn().mockResolvedValue({
					data: null,
					error: { code: 'PGRST116', message: 'No rows found' }
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			const result = await isProviderConnected('gmail');

			expect(result).toBe(false);
		});

		it('returns false on error', async () => {
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				eq: vi.fn().mockReturnThis(),
				single: vi.fn().mockResolvedValue({
					data: null,
					error: mockErrors.permissionDenied
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			const result = await isProviderConnected('gmail');

			expect(result).toBe(false);
		});
	});
});
