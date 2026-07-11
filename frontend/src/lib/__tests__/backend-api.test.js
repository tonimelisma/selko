// @ts-nocheck
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

// Mock Supabase client
const mockSupabase = {
	auth: {
		getSession: vi.fn()
	}
};

vi.mock('$lib/supabase.js', () => ({
	supabase: mockSupabase
}));

// Mock fetch
const mockFetch = vi.fn();
vi.stubGlobal('fetch', mockFetch);

// Mock import.meta.env
vi.stubGlobal('import', {
	meta: {
		env: {
			VITE_API_URL: 'http://localhost:8000'
		}
	}
});

describe('Backend API Client', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockSupabase.auth.getSession.mockResolvedValue({
			data: { session: { access_token: 'test-token' } }
		});
	});

	afterEach(() => {
		vi.resetModules();
	});

	describe('syncEmails', () => {
		it('calls sync endpoint with correct parameters', async () => {
			mockFetch.mockResolvedValue({
				ok: true,
				json: () => Promise.resolve({ fetched: 10, saved: 8, attachments_downloaded: 3 })
			});

			const { syncEmails } = await import('../api/backend.js');
			const result = await syncEmails({ maxResults: 50, fetchAttachments: true });

			expect(mockFetch).toHaveBeenCalledWith(
				'http://localhost:8000/emails/sync',
				expect.objectContaining({
					method: 'POST',
					headers: expect.objectContaining({
						'Content-Type': 'application/json',
						Authorization: 'Bearer test-token'
					}),
					body: JSON.stringify({ max_results: 50, fetch_attachments: true })
				})
			);
			expect(result.data).toEqual({ fetched: 10, saved: 8, attachments_downloaded: 3 });
			expect(result.error).toBeNull();
		});

		it('returns error on failed response', async () => {
			mockFetch.mockResolvedValue({
				ok: false,
				status: 404,
				json: () => Promise.resolve({ detail: 'No Gmail integration found' })
			});

			const { syncEmails } = await import('../api/backend.js');
			const result = await syncEmails();

			expect(result.data).toBeNull();
			expect(result.error).toEqual({
				message: 'No Gmail integration found',
				status: 404,
				detail: 'No Gmail integration found'
			});
		});

		it('returns error when not authenticated', async () => {
			mockSupabase.auth.getSession.mockResolvedValue({
				data: { session: null }
			});

			const { syncEmails } = await import('../api/backend.js');
			const result = await syncEmails();

			expect(result.data).toBeNull();
			expect(result.error.message).toBe('Not authenticated');
		});
	});

	describe('processEmail', () => {
		it('processes single email', async () => {
			mockFetch.mockResolvedValue({
				ok: true,
				json: () =>
					Promise.resolve({
						num_events: 1,
						num_new: 1,
						num_updated: 0,
						event_ids: ['event-123']
					})
			});

			const { processEmail } = await import('../api/backend.js');
			const result = await processEmail('email-456');

			expect(mockFetch).toHaveBeenCalledWith(
				'http://localhost:8000/emails/email-456/process',
				expect.objectContaining({
					method: 'POST'
				})
			);
			expect(result.data.num_events).toBe(1);
		});
	});

	describe('batchProcessEmails', () => {
		it('batch processes emails', async () => {
			mockFetch.mockResolvedValue({
				ok: true,
				json: () =>
					Promise.resolve({
						num_events: 5,
						num_new: 3,
						num_updated: 2,
						event_ids: ['e1', 'e2', 'e3']
					})
			});

			const { batchProcessEmails } = await import('../api/backend.js');
			const result = await batchProcessEmails({ maxEmails: 10 });

			expect(mockFetch).toHaveBeenCalledWith(
				'http://localhost:8000/emails/batch-process',
				expect.objectContaining({
					method: 'POST',
					body: JSON.stringify({ max_emails: 10 })
				})
			);
			expect(result.data.num_events).toBe(5);
		});
	});

	describe('listCalendars', () => {
		it('lists user calendars', async () => {
			const mockCalendars = [
				{ id: 'primary', name: 'My Calendar', is_primary: true, is_selected: true },
				{ id: 'work', name: 'Work', is_primary: false, is_selected: false }
			];
			mockFetch.mockResolvedValue({
				ok: true,
				json: () => Promise.resolve(mockCalendars)
			});

			const { listCalendars } = await import('../api/backend.js');
			const result = await listCalendars();

			expect(mockFetch).toHaveBeenCalledWith(
				'http://localhost:8000/calendars',
				expect.objectContaining({
					method: 'GET'
				})
			);
			expect(result.data).toEqual(mockCalendars);
		});
	});

	describe('syncEventToCalendar', () => {
		it('syncs event to calendar', async () => {
			mockFetch.mockResolvedValue({
				ok: true,
				json: () =>
					Promise.resolve({
						event_id: 'event-123',
						google_calendar_event_id: 'gcal-456',
						synced_at: '2024-01-01T00:00:00Z',
						status: 'synced'
					})
			});

			const { syncEventToCalendar } = await import('../api/backend.js');
			const result = await syncEventToCalendar('event-123');

			expect(mockFetch).toHaveBeenCalledWith(
				'http://localhost:8000/events/event-123/sync',
				expect.objectContaining({
					method: 'POST'
				})
			);
			expect(result.data.google_calendar_event_id).toBe('gcal-456');
		});

		it('handles sync error', async () => {
			mockFetch.mockResolvedValue({
				ok: false,
				status: 400,
				json: () =>
					Promise.resolve({
						detail: 'Event must be approved before syncing'
					})
			});

			const { syncEventToCalendar } = await import('../api/backend.js');
			const result = await syncEventToCalendar('event-123');

			expect(result.data).toBeNull();
			expect(result.error.detail).toBe('Event must be approved before syncing');
		});
	});

	describe('getGmailAuthUrl', () => {
		it('returns auth URL without redirect_uri', async () => {
			const { getGmailAuthUrl } = await import('../api/backend.js');
			const url = getGmailAuthUrl();

			expect(url).toBe('http://localhost:8000/integrations/gmail/auth');
		});

		it('returns auth URL with redirect_uri', async () => {
			const { getGmailAuthUrl } = await import('../api/backend.js');
			const url = getGmailAuthUrl('http://myapp.com/callback');

			expect(url).toBe(
				'http://localhost:8000/integrations/gmail/auth?redirect_uri=http%3A%2F%2Fmyapp.com%2Fcallback'
			);
		});
	});

	describe('getPhotosAuthUrl', () => {
		it('returns auth URL without redirect_uri', async () => {
			const { getPhotosAuthUrl } = await import('../api/backend.js');
			const url = getPhotosAuthUrl();

			expect(url).toBe('http://localhost:8000/integrations/photos/auth');
		});

		it('returns auth URL with redirect_uri', async () => {
			const { getPhotosAuthUrl } = await import('../api/backend.js');
			const url = getPhotosAuthUrl('http://myapp.com/callback');

			expect(url).toBe(
				'http://localhost:8000/integrations/photos/auth?redirect_uri=http%3A%2F%2Fmyapp.com%2Fcallback'
			);
		});
	});

	describe('initiateGmailAuth', () => {
		it('fetches auth_url with bearer token then navigates', async () => {
			const hrefSetter = vi.fn();
			vi.stubGlobal('window', {
				location: {
					set href(value) {
						hrefSetter(value);
					},
					get href() {
						return '';
					}
				}
			});

			mockFetch.mockResolvedValue({
				ok: true,
				json: () =>
					Promise.resolve({
						auth_url: 'https://accounts.google.com/o/oauth2/auth?client_id=x'
					})
			});

			const { initiateGmailAuth } = await import('../api/backend.js');
			await initiateGmailAuth();

			expect(mockFetch).toHaveBeenCalledWith(
				'http://localhost:8000/integrations/gmail/auth',
				expect.objectContaining({
					headers: expect.objectContaining({
						Authorization: 'Bearer test-token',
						Accept: 'application/json'
					})
				})
			);
			expect(hrefSetter).toHaveBeenCalledWith(
				'https://accounts.google.com/o/oauth2/auth?client_id=x'
			);
		});
	});

	describe('checkHealth', () => {
		it('returns healthy status', async () => {
			mockFetch.mockResolvedValue({
				ok: true,
				json: () => Promise.resolve({ status: 'healthy' })
			});

			const { checkHealth } = await import('../api/backend.js');
			const result = await checkHealth();

			expect(mockFetch).toHaveBeenCalledWith('http://localhost:8000/health');
			expect(result.data).toEqual({ status: 'healthy' });
		});

		it('handles unhealthy status', async () => {
			mockFetch.mockResolvedValue({
				ok: false,
				status: 503,
				json: () => Promise.resolve({ status: 'unhealthy' })
			});

			const { checkHealth } = await import('../api/backend.js');
			const result = await checkHealth();

			expect(result.error.status).toBe(503);
		});

		it('handles network error', async () => {
			mockFetch.mockRejectedValue(new Error('Network error'));

			const { checkHealth } = await import('../api/backend.js');
			const result = await checkHealth();

			expect(result.data).toBeNull();
			expect(result.error.message).toBe('Network error');
		});
	});
});
