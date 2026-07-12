/**
 * Format a change-set field value for display.
 * Datetimes must look like ISO (`YYYY-MM-DDTHH:MM...`); plain text with a "T"
 * (e.g. "TechCorp HQ") must not be parsed as a date.
 *
 * @param {any} value
 * @param {string} [noneLabel='None']
 * @returns {string}
 */
export function formatChangeValue(value, noneLabel = 'None') {
	if (value === null || value === undefined || value === '') return noneLabel;
	if (typeof value === 'boolean') return value ? 'Yes' : 'No';
	if (typeof value === 'string' && /^\d{4}-\d{2}-\d{2}T/.test(value)) {
		const date = new Date(value);
		if (!Number.isNaN(date.getTime())) {
			return date.toLocaleString(undefined, {
				month: 'short',
				day: 'numeric',
				hour: 'numeric',
				minute: '2-digit'
			});
		}
	}
	return String(value);
}
