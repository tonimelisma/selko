/**
 * Format an event's date/time for display in the review list and cards.
 *
 * @param {{ all_day?: boolean, start_datetime?: string | null, end_datetime?: string | null }} event
 * @param {(key: string) => string} t - Translation function, e.g. svelte-i18n's `$_`.
 * @returns {string}
 */
export function formatEventDateTime(event, t) {
	if (event.all_day) {
		if (!event.start_datetime) return t('events.allDay');
		const start = new Date(event.start_datetime);
		/** @type {Intl.DateTimeFormatOptions} */
		const opts = { weekday: 'short', month: 'short', day: 'numeric' };
		let label = start.toLocaleDateString(undefined, opts);
		if (event.end_datetime) {
			// end is stored as the last moment of the final day; subtract a minute
			// so an exclusive-style end doesn't spill into the next day
			const end = new Date(new Date(event.end_datetime).getTime() - 60000);
			if (end.toDateString() !== start.toDateString() && end > start) {
				label += ` – ${end.toLocaleDateString(undefined, opts)}`;
			}
		}
		return `${label}, ${t('events.allDay')}`;
	}

	if (!event.start_datetime) return '';
	try {
		const start = new Date(event.start_datetime);
		const dateStr = start.toLocaleDateString(undefined, {
			weekday: 'short',
			month: 'short',
			day: 'numeric'
		});
		const timeStr = start.toLocaleTimeString(undefined, {
			hour: 'numeric',
			minute: '2-digit'
		});
		let result = `${dateStr}, ${timeStr}`;
		if (event.end_datetime) {
			const end = new Date(event.end_datetime);
			const endTimeStr = end.toLocaleTimeString(undefined, {
				hour: 'numeric',
				minute: '2-digit'
			});
			result += ` - ${endTimeStr}`;
		}
		return result;
	} catch {
		return event.start_datetime;
	}
}
