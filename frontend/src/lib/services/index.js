/**
 * Service layer index - re-exports the data service functions.
 *
 * Every service calls Selko's API through `$lib/api/client.js` and returns
 * `{data, error[, count]}`. Server-side operations (sync, LLM processing,
 * OAuth) live in the backend API client.
 *
 * @example
 * import { fetchPendingEventsWithSources } from '$lib/services';
 * import { syncEmails, processEmail } from '$lib/api/backend';
 */

// Email operations
export { getEmail } from './emails.js';

export { fetchEmailHistory, fetchEmailProcessingState, queueEmailReprocess } from './email-history.js';

// Event operations
export {
	fetchPendingEventsWithSources,
	fetchActivityEvents,
	getEvent,
	updateEventStatus,
	updateEvent
} from './events.js';

// Integration operations
export {
	fetchIntegrations,
	disconnectIntegrations,
	fetchCalendarRecovery
} from './integrations.js';

// Attachment operations
export { fetchAttachments, fetchAttachmentContent, downloadAttachment } from './attachments.js';

// Sender rule operations
export {
	fetchSenderRules,
	createSenderRule,
	deleteSenderRule,
	ignoreSenderRetroactive
} from './sender-rules.js';

// Calendar settings operations
export { getCalendarSettings, updateCalendarSettings } from './calendar-settings.js';
