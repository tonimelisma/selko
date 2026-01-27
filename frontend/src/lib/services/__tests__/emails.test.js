import { describe, it, expect, vi, beforeEach } from 'vitest';
import { mockEmails, mockErrors } from '../../../../tests/fixtures/mock-data.js';

// Mock supabase module
const mockFrom = vi.fn();
vi.mock('$lib/supabase.js', () => ({
	supabase: {
		from: (...args) => mockFrom(...args)
	}
}));

// Import after mocking
const { fetchEmails, getEmail, updateEmailReadStatus } = await import('../emails.js');

/**
 * Create a chainable mock query builder that resolves with the given response
 * @param {object} response - The response to resolve with
 * @returns {object} Mock query builder
 */
function createChainableMock(response) {
	const eqCalls = [];
	const mock = {
		select: vi.fn().mockReturnThis(),
		order: vi.fn().mockReturnThis(),
		range: vi.fn().mockReturnThis(),
		eq: vi.fn((...args) => {
			eqCalls.push(args);
			return mock;
		}),
		_eqCalls: eqCalls,
		// Make it thenable so await works
		then: (resolve) => resolve(response)
	};
	return mock;
}

describe('emails service', () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	describe('fetchEmails', () => {
		it('fetches emails with default options', async () => {
			const mockQuery = createChainableMock({
				data: mockEmails,
				error: null,
				count: mockEmails.length
			});

			mockFrom.mockReturnValue(mockQuery);

			const result = await fetchEmails();

			expect(mockFrom).toHaveBeenCalledWith('emails');
			expect(mockQuery.select).toHaveBeenCalledWith('*', { count: 'exact' });
			expect(mockQuery.order).toHaveBeenCalledWith('date_sent', { ascending: false });
			expect(mockQuery.range).toHaveBeenCalledWith(0, 49); // default limit 50
			// Default excludes spam and trash
			expect(mockQuery._eqCalls).toContainEqual(['is_spam', false]);
			expect(mockQuery._eqCalls).toContainEqual(['is_trash', false]);
			expect(result.data).toEqual(mockEmails);
			expect(result.count).toBe(mockEmails.length);
			expect(result.error).toBeNull();
		});

		it('applies pagination options', async () => {
			const mockQuery = createChainableMock({
				data: [mockEmails[0]],
				error: null,
				count: 1
			});

			mockFrom.mockReturnValue(mockQuery);

			await fetchEmails({ limit: 10, offset: 20 });

			expect(mockQuery.range).toHaveBeenCalledWith(20, 29);
		});

		it('excludes promotions when specified', async () => {
			const mockQuery = createChainableMock({
				data: [],
				error: null,
				count: 0
			});

			mockFrom.mockReturnValue(mockQuery);

			await fetchEmails({ excludePromotions: true });

			expect(mockQuery._eqCalls).toContainEqual(['is_promotions', false]);
		});

		it('filters for unread only when specified', async () => {
			const mockQuery = createChainableMock({
				data: [],
				error: null,
				count: 0
			});

			mockFrom.mockReturnValue(mockQuery);

			await fetchEmails({ unreadOnly: true });

			expect(mockQuery._eqCalls).toContainEqual(['is_unread', true]);
		});

		it('handles errors gracefully', async () => {
			const mockQuery = createChainableMock({
				data: null,
				error: mockErrors.permissionDenied,
				count: null
			});

			mockFrom.mockReturnValue(mockQuery);

			const result = await fetchEmails();

			expect(result.data).toEqual([]);
			expect(result.count).toBeNull();
			expect(result.error).not.toBeNull();
			expect(result.error?.code).toBe('42501');
		});

		it('returns empty array when data is null', async () => {
			const mockQuery = createChainableMock({
				data: null,
				error: null,
				count: 0
			});

			mockFrom.mockReturnValue(mockQuery);

			const result = await fetchEmails();

			expect(result.data).toEqual([]);
			expect(result.error).toBeNull();
		});
	});

	describe('getEmail', () => {
		it('fetches a single email by ID', async () => {
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				eq: vi.fn().mockReturnThis(),
				single: vi.fn().mockResolvedValue({
					data: mockEmails[0],
					error: null
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			const result = await getEmail(mockEmails[0].id);

			expect(mockFrom).toHaveBeenCalledWith('emails');
			expect(mockQuery.select).toHaveBeenCalledWith('*');
			expect(mockQuery.eq).toHaveBeenCalledWith('id', mockEmails[0].id);
			expect(mockQuery.single).toHaveBeenCalled();
			expect(result.data).toEqual(mockEmails[0]);
			expect(result.error).toBeNull();
		});

		it('handles not found error', async () => {
			const mockQuery = {
				select: vi.fn().mockReturnThis(),
				eq: vi.fn().mockReturnThis(),
				single: vi.fn().mockResolvedValue({
					data: null,
					error: mockErrors.notFound
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			const result = await getEmail('non-existent-id');

			expect(result.data).toBeNull();
			expect(result.error).not.toBeNull();
		});
	});

	describe('updateEmailReadStatus', () => {
		it('marks email as read', async () => {
			const updatedEmail = { ...mockEmails[0], is_unread: false };
			const mockQuery = {
				update: vi.fn().mockReturnThis(),
				eq: vi.fn().mockReturnThis(),
				select: vi.fn().mockReturnThis(),
				single: vi.fn().mockResolvedValue({
					data: updatedEmail,
					error: null
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			const result = await updateEmailReadStatus(mockEmails[0].id, false);

			expect(mockFrom).toHaveBeenCalledWith('emails');
			expect(mockQuery.update).toHaveBeenCalledWith({ is_unread: false });
			expect(mockQuery.eq).toHaveBeenCalledWith('id', mockEmails[0].id);
			expect(result.data).toEqual(updatedEmail);
			expect(result.error).toBeNull();
		});

		it('marks email as unread', async () => {
			const updatedEmail = { ...mockEmails[1], is_unread: true };
			const mockQuery = {
				update: vi.fn().mockReturnThis(),
				eq: vi.fn().mockReturnThis(),
				select: vi.fn().mockReturnThis(),
				single: vi.fn().mockResolvedValue({
					data: updatedEmail,
					error: null
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			const result = await updateEmailReadStatus(mockEmails[1].id, true);

			expect(mockQuery.update).toHaveBeenCalledWith({ is_unread: true });
			expect(result.data).toEqual(updatedEmail);
		});

		it('handles permission denied error', async () => {
			const mockQuery = {
				update: vi.fn().mockReturnThis(),
				eq: vi.fn().mockReturnThis(),
				select: vi.fn().mockReturnThis(),
				single: vi.fn().mockResolvedValue({
					data: null,
					error: mockErrors.permissionDenied
				})
			};

			mockFrom.mockReturnValue(mockQuery);

			const result = await updateEmailReadStatus('some-id', false);

			expect(result.data).toBeNull();
			expect(result.error?.code).toBe('42501');
		});
	});
});
