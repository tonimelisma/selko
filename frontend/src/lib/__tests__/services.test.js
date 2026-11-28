// @ts-nocheck
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest';

const mockApiFetch = vi.fn();
vi.mock('$lib/api/client.js', () => ({
	apiFetch: (...args) => mockApiFetch(...args)
}));

const ok = (data, status = 200) => ({ data, error: null, status });
const fail = (message, status, code) => ({ data: null, error: { message, status, code }, status });

beforeEach(() => {
	mockApiFetch.mockReset();
});

describe('Attachment Service', () => {
	describe('fetchAttachments', () => {
		it('fetches attachments for an email', async () => {
			const rows = [{ id: 'a1', email_id: 'email-1', filename: 'ticket.pdf', ingestion_status: 'stored' }];
			mockApiFetch.mockResolvedValue(ok(rows));

			const { fetchAttachments } = await import('../services/attachments.js');
			const result = await fetchAttachments('email-1');

			expect(mockApiFetch).toHaveBeenCalledWith('/emails/email-1/attachments');
			expect(result).toEqual({ data: rows, error: null });
		});

		it('returns an empty array on error', async () => {
			mockApiFetch.mockResolvedValue(fail('Email not found', 404));

			const { fetchAttachments } = await import('../services/attachments.js');
			const result = await fetchAttachments('email-1');

			expect(result.data).toEqual([]);
			expect(result.error.status).toBe(404);
		});
	});

	describe('downloadAttachment', () => {
		/** @type {any} */
		let clicked;
		beforeEach(() => {
			clicked = null;
			URL.createObjectURL = vi.fn(() => 'blob:selko/1');
			URL.revokeObjectURL = vi.fn();
			vi.spyOn(HTMLAnchorElement.prototype, 'click').mockImplementation(function () {
				clicked = { href: this.href, download: this.download };
			});
		});
		afterEach(() => {
			vi.restoreAllMocks();
		});

		// Validates: SEL-537
		it('fetches the bytes with the Bearer client and saves them under the filename', async () => {
			const blob = new Blob(['%PDF']);
			mockApiFetch.mockResolvedValue(ok(blob));

			const { downloadAttachment } = await import('../services/attachments.js');
			const result = await downloadAttachment({ id: 'a1', filename: 'ticket.pdf' });

			expect(mockApiFetch).toHaveBeenCalledWith('/attachments/a1/content', expect.objectContaining({ responseType: 'blob' }));
			expect(URL.createObjectURL).toHaveBeenCalledWith(blob);
			expect(clicked).toEqual({ href: 'blob:selko/1', download: 'ticket.pdf' });
			expect(result.error).toBeNull();
		});

		it('reports a file that is not stored without saving anything', async () => {
			mockApiFetch.mockResolvedValue(fail('Attachment is not stored', 404));

			const { downloadAttachment } = await import('../services/attachments.js');
			const result = await downloadAttachment({ id: 'a1', filename: 'ticket.pdf' });

			expect(result.error.message).toBe('Attachment is not stored');
			expect(clicked).toBeNull();
		});

		// Validates: SEL-537
		it('only offers stored files for download', async () => {
			const { isDownloadable } = await import('../services/attachments.js');
			expect(isDownloadable({ ingestion_status: 'stored' })).toBe(true);
			expect(isDownloadable({ ingestion_status: 'pending' })).toBe(false);
			expect(isDownloadable({ ingestion_status: 'unsupported' })).toBe(false);
		});
	});
});

describe('Calendar Settings Service', () => {
	describe('getCalendarSettings', () => {
		it('unwraps the settings row', async () => {
			const settings = { user_id: 'u1', target_calendar_id: 'primary', all_day_display_mode: 'all_day' };
			mockApiFetch.mockResolvedValue(ok({ settings }));

			const { getCalendarSettings } = await import('../services/calendar-settings.js');
			const result = await getCalendarSettings();

			expect(mockApiFetch).toHaveBeenCalledWith('/settings/calendar');
			expect(result).toEqual({ data: settings, error: null });
		});

		it('returns null if no settings exist', async () => {
			mockApiFetch.mockResolvedValue(ok({ settings: null }));

			const { getCalendarSettings } = await import('../services/calendar-settings.js');
			expect(await getCalendarSettings()).toEqual({ data: null, error: null });
		});
	});

	describe('updateCalendarSettings', () => {
		// Validates: SEL-550
		it('PATCHes only the given fields, without user_id or updated_at', async () => {
			const saved = { user_id: 'u1', target_calendar_id: 'outlook:abc' };
			mockApiFetch.mockResolvedValue(ok({ settings: saved }));

			const { updateCalendarSettings } = await import('../services/calendar-settings.js');
			const result = await updateCalendarSettings({ target_calendar_id: 'outlook:abc', default_invitees: undefined });

			expect(mockApiFetch).toHaveBeenCalledWith('/settings/calendar', {
				method: 'PATCH',
				body: { target_calendar_id: 'outlook:abc' }
			});
			expect(result.data).toEqual(saved);
		});

		it('returns the validation error', async () => {
			mockApiFetch.mockResolvedValue(fail('A custom all-day time needs a start before its end', 422));

			const { updateCalendarSettings } = await import('../services/calendar-settings.js');
			const result = await updateCalendarSettings({ all_day_display_mode: 'custom' });

			expect(result.data).toBeNull();
			expect(result.error.message).toBe('A custom all-day time needs a start before its end');
		});
	});
});

describe('Sender Rules Service', () => {
	describe('fetchSenderRules', () => {
		it('fetches all sender rules', async () => {
			const rules = [{ id: 'r1', sender_domain: 'example.com', sender_email: null, action: 'ignore' }];
			mockApiFetch.mockResolvedValue(ok(rules));

			const { fetchSenderRules } = await import('../services/sender-rules.js');
			const result = await fetchSenderRules();

			expect(mockApiFetch).toHaveBeenCalledWith('/sender-rules');
			expect(result).toEqual({ data: rules, error: null });
		});
	});

	describe('createSenderRule', () => {
		it('creates a rule with domain (the server takes the user from the token)', async () => {
			const rule = { id: 'r1', sender_domain: 'example.com', action: 'auto_approve' };
			mockApiFetch.mockResolvedValue(ok(rule, 201));

			const { createSenderRule } = await import('../services/sender-rules.js');
			const result = await createSenderRule({ sender_domain: 'example.com', action: 'auto_approve' });

			expect(mockApiFetch).toHaveBeenCalledWith('/sender-rules', {
				method: 'POST',
				body: { sender_domain: 'example.com', action: 'auto_approve' }
			});
			expect(result.data).toEqual(rule);
		});

		it('creates a rule with email', async () => {
			mockApiFetch.mockResolvedValue(ok({ id: 'r2' }, 201));

			const { createSenderRule } = await import('../services/sender-rules.js');
			await createSenderRule({ sender_email: 'Boss@Example.com', action: 'ignore' });

			expect(mockApiFetch.mock.calls[0][1].body).toEqual({ sender_email: 'Boss@Example.com', action: 'ignore' });
		});

		it('fails without domain or email, before calling the API', async () => {
			const { createSenderRule } = await import('../services/sender-rules.js');
			const result = await createSenderRule({ action: 'ignore' });

			expect(mockApiFetch).not.toHaveBeenCalled();
			expect(result.error.message).toContain('sender_domain or sender_email');
		});

		it('shows the duplicate-rule message', async () => {
			mockApiFetch.mockResolvedValue(fail('A record with this information already exists.', 409));

			const { createSenderRule } = await import('../services/sender-rules.js');
			const result = await createSenderRule({ sender_email: 'a@b.com', action: 'ignore' });

			expect(result.error.message).toBe('A record with this information already exists.');
		});
	});

	describe('ignoreSenderRetroactive', () => {
		it('posts the sender and returns the counts', async () => {
			mockApiFetch.mockResolvedValue(ok({ rejected_new: 2, discarded_changes: 1 }));

			const { ignoreSenderRetroactive } = await import('../services/sender-rules.js');
			const result = await ignoreSenderRetroactive('spam@example.com');

			expect(mockApiFetch).toHaveBeenCalledWith('/sender-rules/ignore-sender', {
				method: 'POST',
				body: { sender_email: 'spam@example.com' }
			});
			expect(result.data).toEqual({ rejected_new: 2, discarded_changes: 1 });
		});
	});

	describe('deleteSenderRule', () => {
		it('deletes a rule', async () => {
			mockApiFetch.mockResolvedValue(ok(null, 204));

			const { deleteSenderRule } = await import('../services/sender-rules.js');
			const result = await deleteSenderRule('rule-1');

			expect(mockApiFetch).toHaveBeenCalledWith('/sender-rules/rule-1', { method: 'DELETE' });
			expect(result.error).toBeNull();
		});
	});
});

describe('Email Folders Service', () => {
	// Validates: SEL-551
	it('lists folders through GET /integrations/{provider}/folders', async () => {
		const folders = [{ id: 'f1', provider: 'gmail', name: 'Receipts', is_system: false }];
		mockApiFetch.mockResolvedValue(ok(folders));

		const { fetchEmailFolders } = await import('../services/email-folders.js');
		const result = await fetchEmailFolders('gmail');

		expect(mockApiFetch).toHaveBeenCalledWith('/integrations/gmail/folders', { method: 'GET' });
		expect(result).toEqual({ data: folders, error: null });
	});
});
