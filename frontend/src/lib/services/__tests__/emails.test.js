// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { mockEmails } from '../../../../tests/fixtures/mock-data.js';

const mockApiFetch = vi.fn();
vi.mock('$lib/api/client.js', () => ({
	apiFetch: (...args) => mockApiFetch(...args)
}));

const { getEmail } = await import('../emails.js');

describe('emails service', () => {
	beforeEach(() => {
		mockApiFetch.mockReset();
	});

	describe('getEmail', () => {
		it('fetches one email summary by id', async () => {
			mockApiFetch.mockResolvedValue({ data: mockEmails[0], error: null, status: 200 });

			const result = await getEmail('email-1');

			expect(mockApiFetch).toHaveBeenCalledWith('/emails/email-1');
			expect(result.data).toEqual(mockEmails[0]);
			expect(result.error).toBeNull();
		});

		it('reports a missing email', async () => {
			mockApiFetch.mockResolvedValue({ data: null, error: { message: 'Email not found', status: 404 }, status: 404 });

			const result = await getEmail('nonexistent');

			expect(result.data).toBeNull();
			expect(result.error.message).toBe('Email not found');
			expect(result.error.status).toBe(404);
		});

		it('encodes the id into the path', async () => {
			mockApiFetch.mockResolvedValue({ data: null, error: null, status: 200 });

			await getEmail('a/b');

			expect(mockApiFetch).toHaveBeenCalledWith('/emails/a%2Fb');
		});
	});
});
