import { describe, it, expect } from 'vitest';
import { AppError, toAppError } from '../errors.js';

describe('AppError', () => {
	it('carries message, code, original error and status', () => {
		const original = { message: 'x' };
		const error = new AppError('Friendly', 'CODE', original, 409);
		expect(error).toBeInstanceOf(Error);
		expect(error.name).toBe('AppError');
		expect(error.message).toBe('Friendly');
		expect(error.code).toBe('CODE');
		expect(error.originalError).toBe(original);
		expect(error.status).toBe(409);
	});
});

describe('toAppError', () => {
	it('returns an AppError unchanged', () => {
		const error = new AppError('m', 'C');
		expect(toAppError(error)).toBe(error);
	});

	// Validates: SEL-580
	it('keeps an API error’s message, code and status', () => {
		const error = toAppError({ message: 'Event not found', status: 404, code: 'EVENT_NOT_FOUND' });
		expect(error.message).toBe('Event not found');
		expect(error.code).toBe('EVENT_NOT_FOUND');
		expect(error.status).toBe(404);
	});

	it('keeps the duplicate-rule message the API sends', () => {
		const error = toAppError({ message: 'A record with this information already exists.', status: 409 });
		expect(error.message).toBe('A record with this information already exists.');
		expect(error.code).toBe('UNKNOWN');
	});

	// Validates: SEL-580
	it('turns network failures into a connection message', () => {
		expect(toAppError({ message: 'Failed to fetch', status: 0, code: 'NETWORK_ERROR' }).message).toBe(
			'Unable to connect. Please check your internet connection.'
		);
		expect(toAppError(new TypeError('Failed to fetch')).code).toBe('NETWORK_ERROR');
	});

	// Validates: SEL-580
	it('turns a timeout into a retry message', () => {
		const error = toAppError({ message: 'Request timed out. Please try again.', status: 0, code: 'TIMEOUT' });
		expect(error.code).toBe('TIMEOUT');
		expect(error.message).toBe('The request timed out. Please try again.');
	});

	// Validates: SEL-580
	it('explains a missing session', () => {
		const error = toAppError({ message: 'Not authenticated', status: 401, code: 'UNAUTHORIZED' });
		expect(error.message).toBe('Your session has expired. Please log in again.');
	});

	it('wraps a thrown error', () => {
		const error = toAppError(new Error('Something specific'));
		expect(error.message).toBe('Something specific');
		expect(error.code).toBe('UNKNOWN');
	});

	it('handles null, undefined and strings', () => {
		expect(toAppError(null).message).toBe('An unexpected error occurred. Please try again.');
		expect(toAppError(undefined).code).toBe('UNKNOWN');
		expect(toAppError('plain').message).toBe('plain');
	});

	it('preserves the original error', () => {
		const original = { message: 'x', status: 500 };
		expect(toAppError(original).originalError).toBe(original);
	});
});
