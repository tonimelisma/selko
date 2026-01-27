import { describe, it, expect } from 'vitest';
import { SupabaseError, parseSupabaseError } from '../errors.js';

describe('SupabaseError', () => {
	it('creates an error with message, code, and original error', () => {
		const originalError = new Error('Original');
		const error = new SupabaseError('User message', 'TEST_CODE', originalError);

		expect(error.message).toBe('User message');
		expect(error.code).toBe('TEST_CODE');
		expect(error.originalError).toBe(originalError);
		expect(error.name).toBe('SupabaseError');
		expect(error instanceof Error).toBe(true);
	});

	it('works without original error', () => {
		const error = new SupabaseError('Message', 'CODE');

		expect(error.message).toBe('Message');
		expect(error.code).toBe('CODE');
		expect(error.originalError).toBe(null);
	});
});

describe('parseSupabaseError', () => {
	it('returns existing SupabaseError unchanged', () => {
		const original = new SupabaseError('Test', 'CODE');
		const result = parseSupabaseError(original);

		expect(result).toBe(original);
	});

	describe('Postgres error codes', () => {
		it('maps unique violation (23505)', () => {
			const error = { code: '23505', message: 'duplicate key' };
			const result = parseSupabaseError(error);

			expect(result.code).toBe('23505');
			expect(result.message).toBe('A record with this information already exists.');
		});

		it('maps foreign key violation (23503)', () => {
			const error = { code: '23503', message: 'foreign key violation' };
			const result = parseSupabaseError(error);

			expect(result.code).toBe('23503');
			expect(result.message).toBe(
				'This record cannot be modified because it is referenced by other data.'
			);
		});

		it('maps not null violation (23502)', () => {
			const error = { code: '23502', message: 'null value' };
			const result = parseSupabaseError(error);

			expect(result.code).toBe('23502');
			expect(result.message).toBe('Required information is missing.');
		});

		it('maps permission denied (42501)', () => {
			const error = { code: '42501', message: 'permission denied' };
			const result = parseSupabaseError(error);

			expect(result.code).toBe('42501');
			expect(result.message).toBe('You do not have permission to perform this action.');
		});

		it('maps invalid data format (22P02)', () => {
			const error = { code: '22P02', message: 'invalid input syntax' };
			const result = parseSupabaseError(error);

			expect(result.code).toBe('22P02');
			expect(result.message).toBe('Invalid data format provided.');
		});
	});

	describe('Auth error codes', () => {
		it('maps invalid_credentials', () => {
			const error = {
				error: 'invalid_credentials',
				error_description: 'Invalid login credentials'
			};
			const result = parseSupabaseError(error);

			expect(result.code).toBe('invalid_credentials');
			expect(result.message).toBe('Invalid email or password.');
		});

		it('maps user_not_found', () => {
			const error = {
				error: 'user_not_found',
				error_description: 'User not found'
			};
			const result = parseSupabaseError(error);

			expect(result.code).toBe('user_not_found');
			expect(result.message).toBe('User not found.');
		});

		it('maps email_not_confirmed', () => {
			const error = {
				error: 'email_not_confirmed',
				error_description: 'Email not confirmed'
			};
			const result = parseSupabaseError(error);

			expect(result.code).toBe('email_not_confirmed');
			expect(result.message).toBe('Please confirm your email address.');
		});

		it('maps session_expired', () => {
			const error = {
				error: 'session_expired',
				error_description: 'Session expired'
			};
			const result = parseSupabaseError(error);

			expect(result.code).toBe('session_expired');
			expect(result.message).toBe('Your session has expired. Please log in again.');
		});

		it('falls back to error_description for unknown auth errors', () => {
			const error = {
				error: 'custom_error',
				error_description: 'Custom error message'
			};
			const result = parseSupabaseError(error);

			expect(result.code).toBe('custom_error');
			expect(result.message).toBe('Custom error message');
		});
	});

	describe('Network errors', () => {
		it('detects Failed to fetch', () => {
			const error = new Error('Failed to fetch');
			const result = parseSupabaseError(error);

			expect(result.code).toBe('NETWORK_ERROR');
			expect(result.message).toBe('Unable to connect. Please check your internet connection.');
		});

		it('detects network error in message', () => {
			const error = { message: 'network error occurred' };
			const result = parseSupabaseError(error);

			expect(result.code).toBe('NETWORK_ERROR');
		});

		it('detects fetch error in message', () => {
			const error = { message: 'fetch failed' };
			const result = parseSupabaseError(error);

			expect(result.code).toBe('NETWORK_ERROR');
		});
	});

	describe('Unknown errors', () => {
		it('handles error with unknown message', () => {
			const error = { message: 'Something weird happened' };
			const result = parseSupabaseError(error);

			expect(result.code).toBe('UNKNOWN');
			expect(result.message).toBe('Something weird happened');
		});

		it('handles error without message', () => {
			const error = { foo: 'bar' };
			const result = parseSupabaseError(error);

			expect(result.code).toBe('UNKNOWN');
			expect(result.message).toBe('An unexpected error occurred. Please try again.');
		});

		it('handles null error', () => {
			const result = parseSupabaseError(null);

			expect(result.code).toBe('UNKNOWN');
			expect(result.message).toBe('An unexpected error occurred. Please try again.');
		});

		it('handles undefined error', () => {
			const result = parseSupabaseError(undefined);

			expect(result.code).toBe('UNKNOWN');
			expect(result.message).toBe('An unexpected error occurred. Please try again.');
		});

		it('handles string error', () => {
			const result = parseSupabaseError('string error');

			expect(result.code).toBe('UNKNOWN');
		});
	});

	it('preserves original error in all cases', () => {
		const original = { code: '23505', message: 'test' };
		const result = parseSupabaseError(original);

		expect(result.originalError).toBe(original);
	});
});
