// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import { writable, readable } from 'svelte/store';

const mockPage = writable({
	url: { pathname: '/app/events/evt-1' },
	params: { id: 'evt-1' },
	route: { id: '' },
	status: 200,
	error: null,
	data: {},
	form: null
});

const mockGoto = vi.fn();
vi.mock('$app/navigation', () => ({
	goto: (...args) => mockGoto(...args),
	page: mockPage,
	navigating: readable(null),
	updated: { subscribe: readable(false).subscribe, check: vi.fn() }
}));

vi.mock('$app/stores', () => ({
	goto: (...args) => mockGoto(...args),
	page: mockPage,
	navigating: readable(null),
	updated: { subscribe: readable(false).subscribe, check: vi.fn() }
}));

const mockGetEvent = vi.fn();
const mockUpdateEvent = vi.fn();
const mockUpdateEventStatus = vi.fn();

vi.mock('$lib/services/events.js', () => ({
	getEvent: (...args) => mockGetEvent(...args),
	updateEvent: (...args) => mockUpdateEvent(...args),
 updateEventStatus: (...args) => mockUpdateEventStatus(...args),
 isNewReviewEvent: (event) => event.review_status === 'pending_review' || event.status === 'pending_review'
}));

const mockFetchEventSources = vi.fn();

vi.mock('$lib/services/event-sources.js', () => ({
	fetchEventSources: (...args) => mockFetchEventSources(...args)
}));

const mockGetEmail = vi.fn();

vi.mock('$lib/services/emails.js', () => ({
	getEmail: (...args) => mockGetEmail(...args)
}));

const mockFetchAttachments = vi.fn();
const mockFetchIntegrations = vi.fn();

vi.mock('$lib/services/attachments.js', () => ({
	fetchAttachments: (...args) => mockFetchAttachments(...args)
}));

 vi.mock('$lib/services/integrations.js', () => ({
 	fetchIntegrations: (...args) => mockFetchIntegrations(...args),
 	fetchCalendarRecovery: () => Promise.resolve({ data: null, error: null })
 }));

const mockSyncEventToCalendar = vi.fn();

vi.mock('$lib/api/backend.js', () => ({
	syncEventToCalendar: (...args) => mockSyncEventToCalendar(...args),
	initiateGmailAuth: vi.fn(),
	initiateOutlookAuth: vi.fn(),
	initiateCalendarAuth: vi.fn(),
	undoHistoryEvent: vi.fn().mockResolvedValue({ data: { event_id: 'evt-1', status: 'pending_review' }, error: null })
}));

const { default: EventDetailPage } = await import('../+page.svelte');

const mockEvent = {
	id: 'evt-1',
	title: 'Team Meeting',
	start_datetime: '2024-01-20T14:00:00Z',
	end_datetime: '2024-01-20T15:00:00Z',
	all_day: false,
	location: 'Room 101',
	description: 'Discuss project',
	status: 'pending_review'
};

describe('Event Detail Page', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockGetEvent.mockResolvedValue({
			data: {
				...mockEvent,
				event_sources: [{
					id: 'src-1',
					event_id: 'evt-1',
					email_id: 'email-1',
					emails: { id: 'email-1', subject: 'Meeting', from_email: 'boss@co.com' }
				}]
			},
			error: null
		});
		mockFetchEventSources.mockResolvedValue({
			data: [
				{
					id: 'src-1',
					event_id: 'evt-1',
					email_id: 'email-1',
					emails: { id: 'email-1', subject: 'Meeting', from_email: 'boss@co.com' }
				}
			],
			error: null
		});
		mockGetEmail.mockResolvedValue({
			data: {
				id: 'email-1',
				subject: 'Meeting Invite',
				from_email: 'boss@company.com',
				from_name: 'Boss',
				snippet: 'Please join us...',
				date_sent: '2024-01-15T10:00:00Z'
			},
			error: null
		});
		mockFetchAttachments.mockResolvedValue({ data: [], error: null });
		mockFetchIntegrations.mockResolvedValue({
			data: [
				{ id: 'gmail', provider: 'gmail', status: 'active' },
				{ id: 'calendar', provider: 'google_calendar', status: 'active' }
			],
			error: null
		});
		mockUpdateEvent.mockResolvedValue({ data: mockEvent, error: null });
		mockUpdateEventStatus.mockResolvedValue({
			data: { ...mockEvent, status: 'approved' },
			error: null
		});
		mockSyncEventToCalendar.mockResolvedValue({ data: null, error: null });
	});

	it('shows loading spinner initially', () => {
		mockGetEvent.mockReturnValue(new Promise(() => {}));
		mockFetchEventSources.mockReturnValue(new Promise(() => {}));

		render(EventDetailPage);

		expect(document.querySelector('.loading.loading-spinner')).toBeTruthy();
	});

	it('displays event title in form', async () => {
		render(EventDetailPage);

		await waitFor(() => {
			const titleInput = screen.getByLabelText(/title/i);
			expect(titleInput).toBeInTheDocument();
			expect(titleInput.value).toBe('Team Meeting');
		});
	});

	it('displays event location', async () => {
		render(EventDetailPage);

		await waitFor(() => {
			const locationInput = screen.getByLabelText(/location/i);
			expect(locationInput.value).toBe('Room 101');
		});
	});

	it('shows source email info', async () => {
		render(EventDetailPage);

		await waitFor(() => {
			// The email info appears in multiple locations (desktop/mobile)
			const subjects = screen.getAllByText(/Meeting Invite/i);
			expect(subjects.length).toBeGreaterThan(0);
		});
	});

	it('shows error when event not found', async () => {
		mockGetEvent.mockResolvedValue({
			data: null,
			error: { message: 'Event not found', code: 'PGRST116' }
		});

		render(EventDetailPage);

		await waitFor(() => {
			expect(screen.getByText('Event not found')).toBeInTheDocument();
		});
	});

	it('displays accept and reject buttons for pending events', async () => {
		render(EventDetailPage);

		await waitFor(() => {
			// There are desktop and mobile versions, so use getAllBy
			const acceptButtons = screen.getAllByRole('button', { name: /accept/i });
			const rejectButtons = screen.getAllByRole('button', { name: /reject/i });
			expect(acceptButtons.length).toBeGreaterThan(0);
			expect(rejectButtons.length).toBeGreaterThan(0);
		});
	});

	it('keeps editing and rejection available but disables acceptance when calendar expired', async () => {
		mockFetchIntegrations.mockResolvedValue({
			data: [
				{ id: 'outlook', provider: 'outlook', status: 'active' },
				{ id: 'calendar', provider: 'google_calendar', status: 'expired' }
			],
			error: null
		});

		render(EventDetailPage);

		await waitFor(() => {
			expect(screen.getByRole('button', { name: 'Reconnect Google Calendar' })).toBeEnabled();
		});
		for (const button of screen.getAllByRole('button', { name: /accept/i })) {
			expect(button).toBeDisabled();
		}
		for (const button of screen.getAllByRole('button', { name: /reject/i })) {
			expect(button).toBeEnabled();
		}
		expect(screen.getByLabelText(/title/i)).toBeEnabled();
	});
});
