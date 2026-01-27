/**
 * Service layer index - re-exports all Supabase service functions
 *
 * These services handle direct Supabase queries. For server-side operations
 * (sync, LLM processing, OAuth), use the backend API client instead.
 *
 * @example
 * import { fetchEmails, fetchPendingEvents } from '$lib/services';
 * import { syncEmails, processEmail } from '$lib/api/backend';
 */

// Email operations
export {
	fetchEmails,
	getEmail,
	updateEmailReadStatus
} from './emails.js';

// Event operations
export {
	fetchPendingEvents,
	fetchEvents,
	getEvent,
	updateEventStatus,
	updateEvent
} from './events.js';

// Event source operations (undo/redo)
export {
	fetchEventSources,
	undoSourceContribution,
	redoSourceContribution,
	getActiveSourceCount
} from './event-sources.js';

// Integration operations
export {
	fetchIntegrations,
	getIntegration,
	getIntegrationByProvider,
	isProviderConnected
} from './integrations.js';

// Attachment operations
export {
	fetchAttachments,
	getAttachment,
	downloadAttachment,
	getAttachmentUrl
} from './attachments.js';

// Sender rule operations
export {
	fetchSenderRules,
	createSenderRule,
	deleteSenderRule,
	findMatchingRule
} from './sender-rules.js';

// Calendar settings operations
export {
	getCalendarSettings,
	updateCalendarSettings
} from './calendar-settings.js';

// Job operations (read-only)
export {
	fetchJobs,
	getJob,
	getPendingJobCounts,
	hasProcessingJobs
} from './jobs.js';
