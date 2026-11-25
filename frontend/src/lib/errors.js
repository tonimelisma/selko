/**
 * The error every service module returns: a user-facing message plus a
 * machine-readable code and, for API errors, the HTTP status.
 */
export class AppError extends Error {
	/**
	 * @param {string} message - User-friendly error message
	 * @param {string} code - Error code
	 * @param {Error | unknown} [originalError] - The error this one was made from
	 * @param {number} [status] - HTTP status, 0 for a network failure
	 */
	constructor(message, code, originalError = null, status = undefined) {
		super(message);
		this.name = 'AppError';
		this.code = code;
		this.originalError = originalError;
		this.status = status;
	}
}

/**
 * Messages for codes whose server or browser text is not fit to show.
 * @type {Record<string, string>}
 */
const ERROR_MESSAGES = {
	NETWORK_ERROR: 'Unable to connect. Please check your internet connection.',
	TIMEOUT: 'The request timed out. Please try again.',
	UNAUTHORIZED: 'Your session has expired. Please log in again.',
	INVALID_GRANT: 'Your session has expired. Please log in again.',
	UNKNOWN: 'An unexpected error occurred. Please try again.'
};

/**
 * Turn an API error (`{message, status, code}` from `apiFetch`) or a thrown
 * error into an AppError.
 * @param {unknown} error
 * @returns {AppError}
 */
export function toAppError(error) {
	if (error instanceof AppError) {
		return error;
	}
	if (error && typeof error === 'object') {
		const err = /** @type {any} */ (error);
		const status = typeof err.status === 'number' ? err.status : undefined;
		const code = typeof err.code === 'string' && err.code ? err.code : status === 0 ? 'NETWORK_ERROR' : 'UNKNOWN';

		if (code === 'NETWORK_ERROR' || code === 'TIMEOUT') {
			return new AppError(ERROR_MESSAGES[code], code, error, status ?? 0);
		}
		if (typeof err.message === 'string' && err.message.trim()) {
			if (
				err.message.includes('Failed to fetch') ||
				err.message.toLowerCase().includes('network')
			) {
				return new AppError(ERROR_MESSAGES.NETWORK_ERROR, 'NETWORK_ERROR', error, 0);
			}
			if (code === 'UNAUTHORIZED' && status === 401 && err.message === 'Not authenticated') {
				return new AppError(ERROR_MESSAGES.UNAUTHORIZED, code, error, status);
			}
			return new AppError(err.message, code, error, status);
		}
		if (ERROR_MESSAGES[code]) {
			return new AppError(ERROR_MESSAGES[code], code, error, status);
		}
	}
	if (typeof error === 'string' && error.trim()) {
		return new AppError(error, 'UNKNOWN', error);
	}
	return new AppError(ERROR_MESSAGES.UNKNOWN, 'UNKNOWN', error);
}
