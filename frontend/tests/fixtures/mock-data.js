// @ts-nocheck
/**
 * Mock data for testing
 */

/** @type {import('../../src/lib/types.js').Email[]} */
export const mockEmails = [
	{
		id: '550e8400-e29b-41d4-a716-446655440001',
		user_id: '550e8400-e29b-41d4-a716-446655440000',
		integration_id: '550e8400-e29b-41d4-a716-446655440010',
		provider_message_id: 'msg_123456',
		thread_id: 'thread_123456',
		subject: 'School Event - Parent Teacher Conference',
		from_email: 'school@example.com',
		from_name: 'Lincoln Elementary School',
		to_emails: ['parent@example.com'],
		date_sent: '2024-01-15T10:30:00Z',
		snippet: 'Dear Parent, We are pleased to invite you to our upcoming...',
		provider_labels: ['INBOX', 'UNREAD', 'CATEGORY_PERSONAL'],
		is_spam: false,
		is_trash: false,
		is_promotions: false,
		is_social: false,
		is_updates: false,
		is_forums: false,
		is_primary: true,
		is_important: false,
		is_starred: false,
		is_unread: true,
		has_attachments: false,
		processing_status: 'pending',
		created_at: '2024-01-15T10:31:00Z'
	},
	{
		id: '550e8400-e29b-41d4-a716-446655440002',
		user_id: '550e8400-e29b-41d4-a716-446655440000',
		integration_id: '550e8400-e29b-41d4-a716-446655440010',
		provider_message_id: 'msg_123457',
		thread_id: 'thread_123457',
		subject: 'Your order has shipped',
		from_email: 'noreply@store.com',
		from_name: 'Online Store',
		to_emails: ['user@example.com'],
		date_sent: '2024-01-14T15:00:00Z',
		snippet: 'Your order #12345 has been shipped and is on its way...',
		provider_labels: ['INBOX', 'CATEGORY_UPDATES'],
		is_spam: false,
		is_trash: false,
		is_promotions: false,
		is_social: false,
		is_updates: true,
		is_forums: false,
		is_primary: false,
		is_important: false,
		is_starred: false,
		is_unread: false,
		has_attachments: true,
		processing_status: 'completed',
		created_at: '2024-01-14T15:01:00Z'
	},
	{
		id: '550e8400-e29b-41d4-a716-446655440003',
		user_id: '550e8400-e29b-41d4-a716-446655440000',
		integration_id: '550e8400-e29b-41d4-a716-446655440010',
		provider_message_id: 'msg_123458',
		thread_id: 'thread_123458',
		subject: '50% off sale this weekend!',
		from_email: 'promo@marketing.com',
		from_name: 'Marketing Company',
		to_emails: ['user@example.com'],
		date_sent: '2024-01-13T08:00:00Z',
		snippet: 'Dont miss our biggest sale of the year...',
		provider_labels: ['INBOX', 'CATEGORY_PROMOTIONS'],
		is_spam: false,
		is_trash: false,
		is_promotions: true,
		is_social: false,
		is_updates: false,
		is_forums: false,
		is_primary: false,
		is_important: false,
		is_starred: false,
		is_unread: true,
		has_attachments: false,
		processing_status: null,
		created_at: '2024-01-13T08:01:00Z'
	}
];

/** @type {import('../../src/lib/types.js').CalendarEvent[]} */
export const mockEvents = [
	{
		id: '550e8400-e29b-41d4-a716-446655440101',
		user_id: '550e8400-e29b-41d4-a716-446655440000',
		title: 'Parent Teacher Conference',
		start_datetime: '2024-01-20T14:00:00Z',
		end_datetime: '2024-01-20T15:00:00Z',
		all_day: false,
		location: 'Lincoln Elementary School, Room 101',
		description: 'Meeting with Mrs. Johnson to discuss progress',
		source_attribution: 'This event was automatically created from an email from Lincoln Elementary School on Jan 15th.',
		status: 'pending_review',
		google_calendar_event_id: null,
		synced_at: null,
		created_at: '2024-01-15T10:35:00Z',
		updated_at: '2024-01-15T10:35:00Z'
	},
	{
		id: '550e8400-e29b-41d4-a716-446655440102',
		user_id: '550e8400-e29b-41d4-a716-446655440000',
		title: 'Dentist Appointment',
		start_datetime: '2024-01-22T09:00:00Z',
		end_datetime: '2024-01-22T10:00:00Z',
		all_day: false,
		location: 'Downtown Dental Clinic',
		description: 'Regular checkup',
		source_attribution: null,
		status: 'approved',
		google_calendar_event_id: 'gcal_event_123',
		synced_at: '2024-01-15T12:00:00Z',
		created_at: '2024-01-14T08:00:00Z',
		updated_at: '2024-01-15T12:00:00Z'
	},
	{
		id: '550e8400-e29b-41d4-a716-446655440103',
		user_id: '550e8400-e29b-41d4-a716-446655440000',
		title: 'Spring Break',
		start_datetime: '2024-03-15T00:00:00Z',
		end_datetime: '2024-03-22T00:00:00Z',
		all_day: true,
		location: null,
		description: 'School spring break',
		source_attribution: 'This event was automatically created from an email from Lincoln Elementary School.',
		status: 'pending_review',
		google_calendar_event_id: null,
		synced_at: null,
		created_at: '2024-01-10T09:00:00Z',
		updated_at: '2024-01-10T09:00:00Z'
	}
];

/** @type {import('../../src/lib/types.js').Integration[]} */
export const mockIntegrations = [
	{
		id: '550e8400-e29b-41d4-a716-446655440010',
		user_id: '550e8400-e29b-41d4-a716-446655440000',
		provider: 'gmail',
		status: 'active',
		provider_email: 'user@gmail.com',
		scopes: ['https://www.googleapis.com/auth/gmail.readonly'],
		last_sync_at: '2024-01-15T10:30:00Z',
		created_at: '2024-01-01T00:00:00Z',
		updated_at: '2024-01-15T10:30:00Z'
	},
	{
		id: '550e8400-e29b-41d4-a716-446655440011',
		user_id: '550e8400-e29b-41d4-a716-446655440000',
		provider: 'google_calendar',
		status: 'active',
		provider_email: 'user@gmail.com',
		scopes: ['https://www.googleapis.com/auth/calendar'],
		last_sync_at: '2024-01-15T12:00:00Z',
		created_at: '2024-01-01T00:00:00Z',
		updated_at: '2024-01-15T12:00:00Z'
	},
	{
		id: '550e8400-e29b-41d4-a716-446655440012',
		user_id: '550e8400-e29b-41d4-a716-446655440000',
		provider: 'google_photos',
		status: 'expired',
		provider_email: 'user@gmail.com',
		scopes: ['https://www.googleapis.com/auth/photoslibrary.readonly'],
		last_sync_at: '2024-01-10T08:00:00Z',
		created_at: '2024-01-01T00:00:00Z',
		updated_at: '2024-01-10T08:00:00Z'
	}
];

/** Mock user for auth tests */
export const mockUser = {
	id: '550e8400-e29b-41d4-a716-446655440000',
	email: 'test@example.com',
	created_at: '2024-01-01T00:00:00Z',
	updated_at: '2024-01-01T00:00:00Z'
};

/** Mock Supabase errors for testing error handling */
export const mockErrors = {
	notFound: {
		code: 'PGRST116',
		message: 'JSON object requested, multiple (or no) rows returned',
		details: null,
		hint: null
	},
	uniqueViolation: {
		code: '23505',
		message: 'duplicate key value violates unique constraint',
		details: 'Key already exists',
		hint: null
	},
	permissionDenied: {
		code: '42501',
		message: 'permission denied for table emails',
		details: null,
		hint: null
	},
	networkError: new Error('Failed to fetch'),
	invalidCredentials: {
		error: 'invalid_credentials',
		error_description: 'Invalid login credentials'
	}
};
