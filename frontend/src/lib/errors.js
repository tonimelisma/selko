/**
 * Custom error class for Supabase errors
 */
export class SupabaseError extends Error {
	/**
	 * @param {string} message - User-friendly error message
	 * @param {string} code - Error code
	 * @param {Error | unknown} [originalError] - Original error from Supabase
	 */
	constructor(message, code, originalError = null) {
		super(message);
		this.name = 'SupabaseError';
		this.code = code;
		this.originalError = originalError;
	}
}

/**
 * Error code mappings for Postgres/Supabase errors
 * @type {Record<string, string>}
 */
const ERROR_MESSAGES = {
	// Postgres error codes
	'23505': 'A record with this information already exists.',
	'23503': 'This record cannot be modified because it is referenced by other data.',
	'23502': 'Required information is missing.',
	'42501': 'You do not have permission to perform this action.',
	'42P01': 'The requested resource does not exist.',
	'22P02': 'Invalid data format provided.',
	'28000': 'Authentication failed.',
	'28P01': 'Invalid password.',
	'3D000': 'Database does not exist.',
	'57014': 'The operation was cancelled.',
	'40001': 'Transaction conflict. Please try again.',
	'40P01': 'Deadlock detected. Please try again.',

	// Supabase Auth error codes
	invalid_credentials: 'Invalid email or password.',
	user_not_found: 'User not found.',
	email_not_confirmed: 'Please confirm your email address.',
	user_already_exists: 'An account with this email already exists.',
	weak_password: 'Password is too weak. Please use a stronger password.',
	invalid_email: 'Please enter a valid email address.',
	session_expired: 'Your session has expired. Please log in again.',
	refresh_token_not_found: 'Session expired. Please log in again.',
	invalid_grant: 'Invalid or expired credentials.',

	// Network/general errors
	NETWORK_ERROR: 'Unable to connect. Please check your internet connection.',
	TIMEOUT: 'The request timed out. Please try again.',
	UNKNOWN: 'An unexpected error occurred. Please try again.'
};

/**
 * Parse a Supabase error and return a user-friendly SupabaseError
 * @param {Error | unknown} error - The error from Supabase
 * @returns {SupabaseError}
 */
export function parseSupabaseError(error) {
	if (error instanceof SupabaseError) {
		return error;
	}

	// Handle Supabase PostgREST errors
	if (error && typeof error === 'object') {
		const err = /** @type {any} */ (error);

		// Check for Postgres error code
		if (err.code && ERROR_MESSAGES[err.code]) {
			return new SupabaseError(ERROR_MESSAGES[err.code], err.code, error);
		}

		// Check for Supabase Auth error
		if (err.error_description) {
			const code = err.error || 'auth_error';
			const message = ERROR_MESSAGES[code] || err.error_description;
			return new SupabaseError(message, code, error);
		}

		// Check for message in error object
		if (err.message) {
			// Check if message contains a known error code
			for (const [code, message] of Object.entries(ERROR_MESSAGES)) {
				if (err.message.toLowerCase().includes(code.toLowerCase())) {
					return new SupabaseError(message, code, error);
				}
			}

			// Check for network errors
			if (
				err.message.includes('fetch') ||
				err.message.includes('network') ||
				err.message.includes('Failed to fetch')
			) {
				return new SupabaseError(ERROR_MESSAGES.NETWORK_ERROR, 'NETWORK_ERROR', error);
			}

			return new SupabaseError(err.message, 'UNKNOWN', error);
		}
	}

	// Default unknown error
	return new SupabaseError(ERROR_MESSAGES.UNKNOWN, 'UNKNOWN', error);
}
