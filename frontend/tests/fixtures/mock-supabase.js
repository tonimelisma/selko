// @ts-nocheck
import { vi } from 'vitest';

/**
 * Create a mock Supabase query builder
 * @param {object} [options]
 * @param {any} [options.data] - Data to return
 * @param {any} [options.error] - Error to return
 * @param {number} [options.count] - Count to return
 * @returns {object} Mock query builder
 */
export function createMockQueryBuilder({ data = null, error = null, count = null } = {}) {
	const builder = {
		select: vi.fn().mockReturnThis(),
		insert: vi.fn().mockReturnThis(),
		update: vi.fn().mockReturnThis(),
		delete: vi.fn().mockReturnThis(),
		eq: vi.fn().mockReturnThis(),
		neq: vi.fn().mockReturnThis(),
		gt: vi.fn().mockReturnThis(),
		gte: vi.fn().mockReturnThis(),
		lt: vi.fn().mockReturnThis(),
		lte: vi.fn().mockReturnThis(),
		in: vi.fn().mockReturnThis(),
		is: vi.fn().mockReturnThis(),
		or: vi.fn().mockReturnThis(),
		and: vi.fn().mockReturnThis(),
		order: vi.fn().mockReturnThis(),
		limit: vi.fn().mockReturnThis(),
		range: vi.fn().mockReturnThis(),
		single: vi.fn().mockResolvedValue({ data, error }),
		maybeSingle: vi.fn().mockResolvedValue({ data, error }),
		then: (resolve) => resolve({ data, error, count })
	};

	// Make it thenable for async operations
	builder[Symbol.toStringTag] = 'Promise';

	return builder;
}

/**
 * Create a mock Supabase client
 * @param {object} [options]
 * @param {object} [options.authUser] - Mock authenticated user
 * @param {object} [options.queryResponse] - Default query response
 * @returns {object} Mock Supabase client
 */
export function createMockSupabaseClient({ authUser = null, queryResponse = {} } = {}) {
	const defaultQueryBuilder = createMockQueryBuilder(queryResponse);

	return {
		from: vi.fn().mockReturnValue(defaultQueryBuilder),
		auth: {
			getSession: vi.fn().mockResolvedValue({
				data: {
					session: authUser
						? {
								user: authUser,
								access_token: 'mock-access-token',
								refresh_token: 'mock-refresh-token'
							}
						: null
				},
				error: null
			}),
			signInWithPassword: vi.fn().mockResolvedValue({
				data: authUser ? { user: authUser, session: { access_token: 'mock-token' } } : null,
				error: authUser ? null : { message: 'Invalid credentials' }
			}),
			signOut: vi.fn().mockResolvedValue({ error: null }),
			onAuthStateChange: vi.fn().mockReturnValue({
				data: { subscription: { unsubscribe: vi.fn() } }
			})
		},
		storage: {
			from: vi.fn().mockReturnValue({
				download: vi.fn().mockResolvedValue({ data: null, error: null }),
				upload: vi.fn().mockResolvedValue({ data: { path: 'mock-path' }, error: null }),
				getPublicUrl: vi.fn().mockReturnValue({ data: { publicUrl: 'https://example.com/mock' } })
			})
		}
	};
}

/**
 * Setup Supabase mock for a test module
 * Call this to replace the real supabase import with a mock
 * @param {object} mockClient - Mock Supabase client
 */
export function setupSupabaseMock(mockClient) {
	vi.doMock('$lib/supabase.js', () => ({
		supabase: mockClient
	}));
}
