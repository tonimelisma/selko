// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mock Supabase client
const mockSupabase = {
	from: vi.fn(),
	storage: {
		from: vi.fn()
	},
	auth: {
		getUser: vi.fn(),
		getSession: vi.fn()
	}
};

// Mock the supabase import
vi.mock('$lib/supabase.js', () => ({
	supabase: mockSupabase
}));

// Helper to create chainable query mock
function createQueryMock(data = [], error = null, count = null) {
	const queryMock = {
		select: vi.fn().mockReturnThis(),
		insert: vi.fn().mockReturnThis(),
		update: vi.fn().mockReturnThis(),
		delete: vi.fn().mockReturnThis(),
		eq: vi.fn().mockReturnThis(),
		in: vi.fn().mockReturnThis(),
		or: vi.fn().mockReturnThis(),
		gte: vi.fn().mockReturnThis(),
		lte: vi.fn().mockReturnThis(),
		order: vi.fn().mockReturnThis(),
		range: vi.fn().mockReturnThis(),
		limit: vi.fn().mockReturnThis(),
		single: vi.fn().mockResolvedValue({ data, error }),
		maybeSingle: vi.fn().mockResolvedValue({ data, error }),
		execute: vi.fn().mockResolvedValue({ data, error, count })
	};
	// Make chain return promise at the end
	queryMock.then = (resolve) => resolve({ data, error, count });
	return queryMock;
}

describe('Attachment Service', () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	describe('fetchAttachments', () => {
		it('fetches attachments for an email', async () => {
			const mockAttachments = [
				{ id: '1', filename: 'doc.pdf', mime_type: 'application/pdf' },
				{ id: '2', filename: 'image.png', mime_type: 'image/png' }
			];
			const query = createQueryMock(mockAttachments);
			mockSupabase.from.mockReturnValue(query);

			const { fetchAttachments } = await import('../services/attachments.js');
			const result = await fetchAttachments('email-123');

			expect(mockSupabase.from).toHaveBeenCalledWith('attachments');
			expect(query.select).toHaveBeenCalledWith('*');
			expect(query.eq).toHaveBeenCalledWith('email_id', 'email-123');
			expect(query.order).toHaveBeenCalledWith('filename', { ascending: true });
			expect(result.data).toEqual(mockAttachments);
			expect(result.error).toBeNull();
		});

		it('returns empty array on error', async () => {
			const query = createQueryMock([], { code: '42501', message: 'permission denied' });
			mockSupabase.from.mockReturnValue(query);

			const { fetchAttachments } = await import('../services/attachments.js');
			const result = await fetchAttachments('email-123');

			expect(result.data).toEqual([]);
			expect(result.error).not.toBeNull();
		});
	});

	describe('downloadAttachment', () => {
		it('downloads attachment from storage', async () => {
			const mockBlob = new Blob(['test content'], { type: 'text/plain' });
			const storageMock = {
				download: vi.fn().mockResolvedValue({ data: mockBlob, error: null })
			};
			mockSupabase.storage.from.mockReturnValue(storageMock);

			const { downloadAttachment } = await import('../services/attachments.js');
			const result = await downloadAttachment('user-123/file.pdf');

			expect(mockSupabase.storage.from).toHaveBeenCalledWith('attachments');
			expect(storageMock.download).toHaveBeenCalledWith('user-123/file.pdf');
			expect(result.data).toBe(mockBlob);
			expect(result.error).toBeNull();
		});
	});

	describe('getAttachmentUrl', () => {
		it('creates signed URL with default expiry', async () => {
			const storageMock = {
				createSignedUrl: vi.fn().mockResolvedValue({
					data: { signedUrl: 'https://example.com/signed-url' },
					error: null
				})
			};
			mockSupabase.storage.from.mockReturnValue(storageMock);

			const { getAttachmentUrl } = await import('../services/attachments.js');
			const result = await getAttachmentUrl('user-123/file.pdf');

			expect(storageMock.createSignedUrl).toHaveBeenCalledWith('user-123/file.pdf', 3600);
			expect(result.data).toBe('https://example.com/signed-url');
		});

		it('creates signed URL with custom expiry', async () => {
			const storageMock = {
				createSignedUrl: vi.fn().mockResolvedValue({
					data: { signedUrl: 'https://example.com/signed-url' },
					error: null
				})
			};
			mockSupabase.storage.from.mockReturnValue(storageMock);

			const { getAttachmentUrl } = await import('../services/attachments.js');
			await getAttachmentUrl('user-123/file.pdf', 7200);

			expect(storageMock.createSignedUrl).toHaveBeenCalledWith('user-123/file.pdf', 7200);
		});
	});
});

describe('Calendar Settings Service', () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	describe('getCalendarSettings', () => {
		it('fetches calendar settings', async () => {
			const mockSettings = {
				user_id: 'user-123',
				target_calendar_id: 'cal-456',
				default_invitees: 'spouse@example.com'
			};
			const query = createQueryMock(mockSettings);
			mockSupabase.from.mockReturnValue(query);

			const { getCalendarSettings } = await import('../services/calendar-settings.js');
			const result = await getCalendarSettings();

			expect(mockSupabase.from).toHaveBeenCalledWith('user_calendar_settings');
			expect(query.select).toHaveBeenCalledWith('*');
			expect(query.maybeSingle).toHaveBeenCalled();
			expect(result.data).toEqual(mockSettings);
		});

		it('returns null if no settings exist', async () => {
			const query = createQueryMock(null);
			mockSupabase.from.mockReturnValue(query);

			const { getCalendarSettings } = await import('../services/calendar-settings.js');
			const result = await getCalendarSettings();

			expect(result.data).toBeNull();
			expect(result.error).toBeNull();
		});
	});

	describe('updateCalendarSettings', () => {
		it('upserts calendar settings', async () => {
			mockSupabase.auth.getUser.mockResolvedValue({
				data: { user: { id: 'user-123' } }
			});

			const mockSettings = {
				user_id: 'user-123',
				target_calendar_id: 'cal-456',
				default_invitees: 'spouse@example.com'
			};
			// Add upsert to the query mock
			const query = createQueryMock(mockSettings);
			query.upsert = vi.fn().mockReturnThis();
			mockSupabase.from.mockReturnValue(query);

			const { updateCalendarSettings } = await import('../services/calendar-settings.js');
			const result = await updateCalendarSettings({
				target_calendar_id: 'cal-456',
				default_invitees: 'spouse@example.com'
			});

			expect(query.upsert).toHaveBeenCalled();
			expect(query.select).toHaveBeenCalled();
			expect(query.single).toHaveBeenCalled();
		});

		it('fails if not authenticated', async () => {
			mockSupabase.auth.getUser.mockResolvedValue({ data: { user: null } });

			const { updateCalendarSettings } = await import('../services/calendar-settings.js');
			const result = await updateCalendarSettings({ target_calendar_id: 'cal-456' });

			expect(result.data).toBeNull();
			expect(result.error).not.toBeNull();
		});
	});
});

describe('Sender Rules Service', () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	describe('fetchSenderRules', () => {
		it('fetches all sender rules', async () => {
			const mockRules = [
				{ id: '1', sender_domain: 'example.com', action: 'auto_approve' },
				{ id: '2', sender_email: 'noreply@test.com', action: 'ignore' }
			];
			const query = createQueryMock(mockRules);
			mockSupabase.from.mockReturnValue(query);

			const { fetchSenderRules } = await import('../services/sender-rules.js');
			const result = await fetchSenderRules();

			expect(mockSupabase.from).toHaveBeenCalledWith('sender_rules');
			expect(query.order).toHaveBeenCalledWith('created_at', { ascending: false });
			expect(result.data).toEqual(mockRules);
		});
	});

	describe('createSenderRule', () => {
		it('creates a rule with domain', async () => {
			const mockRule = { id: '1', sender_domain: 'example.com', action: 'auto_approve' };
			const query = createQueryMock(mockRule);
			mockSupabase.from.mockReturnValue(query);

			const { createSenderRule } = await import('../services/sender-rules.js');
			const result = await createSenderRule({
				sender_domain: 'example.com',
				action: 'auto_approve'
			});

			expect(query.insert).toHaveBeenCalled();
			expect(result.data).toEqual(mockRule);
		});

		it('creates a rule with email', async () => {
			const mockRule = { id: '1', sender_email: 'noreply@test.com', action: 'ignore' };
			const query = createQueryMock(mockRule);
			mockSupabase.from.mockReturnValue(query);

			const { createSenderRule } = await import('../services/sender-rules.js');
			const result = await createSenderRule({
				sender_email: 'noreply@test.com',
				action: 'ignore'
			});

			expect(query.insert).toHaveBeenCalled();
			expect(result.data).toEqual(mockRule);
		});

		it('fails without domain or email', async () => {
			const { createSenderRule } = await import('../services/sender-rules.js');
			const result = await createSenderRule({ action: 'auto_approve' });

			expect(result.data).toBeNull();
			expect(result.error).not.toBeNull();
			expect(result.error.message).toContain('sender_domain or sender_email');
		});
	});

	describe('deleteSenderRule', () => {
		it('deletes a rule', async () => {
			const query = createQueryMock(null);
			mockSupabase.from.mockReturnValue(query);

			const { deleteSenderRule } = await import('../services/sender-rules.js');
			const result = await deleteSenderRule('rule-123');

			expect(mockSupabase.from).toHaveBeenCalledWith('sender_rules');
			expect(query.delete).toHaveBeenCalled();
			expect(query.eq).toHaveBeenCalledWith('id', 'rule-123');
			expect(result.error).toBeNull();
		});
	});
});

describe('Event Sources Service', () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	describe('fetchEventSources', () => {
		it('fetches sources with joined email data', async () => {
			const mockSources = [
				{
					id: '1',
					event_id: 'event-123',
					email_id: 'email-456',
					source_type: 'new_invitation',
					is_undone: false,
					emails: { id: 'email-456', subject: 'Meeting invite' }
				}
			];
			const query = createQueryMock(mockSources);
			mockSupabase.from.mockReturnValue(query);

			const { fetchEventSources } = await import('../services/event-sources.js');
			const result = await fetchEventSources('event-123');

			expect(mockSupabase.from).toHaveBeenCalledWith('event_sources');
			expect(query.eq).toHaveBeenCalledWith('event_id', 'event-123');
			expect(query.order).toHaveBeenCalledWith('created_at', { ascending: true });
			expect(result.data).toEqual(mockSources);
		});
	});

	describe('undoSourceContribution', () => {
		it('marks source as undone', async () => {
			const mockSource = { id: '1', is_undone: true };
			const query = createQueryMock(mockSource);
			mockSupabase.from.mockReturnValue(query);

			const { undoSourceContribution } = await import('../services/event-sources.js');
			const result = await undoSourceContribution('source-123');

			expect(query.update).toHaveBeenCalledWith({ is_undone: true });
			expect(query.eq).toHaveBeenCalledWith('id', 'source-123');
			expect(result.data.is_undone).toBe(true);
		});
	});

	describe('redoSourceContribution', () => {
		it('marks source as not undone', async () => {
			const mockSource = { id: '1', is_undone: false };
			const query = createQueryMock(mockSource);
			mockSupabase.from.mockReturnValue(query);

			const { redoSourceContribution } = await import('../services/event-sources.js');
			const result = await redoSourceContribution('source-123');

			expect(query.update).toHaveBeenCalledWith({ is_undone: false });
			expect(result.data.is_undone).toBe(false);
		});
	});

	describe('getActiveSourceCount', () => {
		it('returns count of active sources', async () => {
			const query = {
				select: vi.fn().mockReturnThis(),
				eq: vi.fn().mockReturnThis()
			};
			// Mock the promise resolution
			const mockResult = { count: 3, error: null };
			query.eq.mockImplementation(() => Promise.resolve(mockResult));
			mockSupabase.from.mockReturnValue(query);

			const { getActiveSourceCount } = await import('../services/event-sources.js');
			const result = await getActiveSourceCount('event-123');

			expect(mockSupabase.from).toHaveBeenCalledWith('event_sources');
			expect(query.select).toHaveBeenCalledWith('id', { count: 'exact', head: true });
		});
	});
});

describe('Jobs Service', () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	describe('fetchJobs', () => {
		it('fetches jobs with pagination', async () => {
			const mockJobs = [
				{ id: '1', job_type: 'email_fetch', status: 'completed' },
				{ id: '2', job_type: 'email_process', status: 'pending' }
			];
			const query = createQueryMock(mockJobs, null, 10);
			mockSupabase.from.mockReturnValue(query);

			const { fetchJobs } = await import('../services/jobs.js');
			const result = await fetchJobs({ limit: 20, offset: 0 });

			expect(mockSupabase.from).toHaveBeenCalledWith('jobs');
			expect(query.order).toHaveBeenCalledWith('created_at', { ascending: false });
			expect(query.range).toHaveBeenCalledWith(0, 19);
			expect(result.data).toEqual(mockJobs);
		});

		it('filters by status', async () => {
			const query = createQueryMock([]);
			mockSupabase.from.mockReturnValue(query);

			const { fetchJobs } = await import('../services/jobs.js');
			await fetchJobs({ statuses: ['pending', 'processing'] });

			expect(query.in).toHaveBeenCalledWith('status', ['pending', 'processing']);
		});

		it('filters by job type', async () => {
			const query = createQueryMock([]);
			mockSupabase.from.mockReturnValue(query);

			const { fetchJobs } = await import('../services/jobs.js');
			await fetchJobs({ types: ['email_fetch'] });

			expect(query.in).toHaveBeenCalledWith('job_type', ['email_fetch']);
		});
	});

	describe('getPendingJobCounts', () => {
		it('returns counts grouped by type', async () => {
			const mockJobs = [
				{ job_type: 'email_fetch' },
				{ job_type: 'email_fetch' },
				{ job_type: 'email_process' }
			];
			const query = createQueryMock(mockJobs);
			mockSupabase.from.mockReturnValue(query);

			const { getPendingJobCounts } = await import('../services/jobs.js');
			const result = await getPendingJobCounts();

			expect(query.eq).toHaveBeenCalledWith('status', 'pending');
			expect(result.data).toEqual({
				email_fetch: 2,
				email_process: 1
			});
		});
	});
});
