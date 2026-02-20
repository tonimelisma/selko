// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';

const mockFetchSenderRules = vi.fn();
const mockCreateSenderRule = vi.fn();
const mockDeleteSenderRule = vi.fn();

vi.mock('$lib/services/sender-rules.js', () => ({
	fetchSenderRules: (...args) => mockFetchSenderRules(...args),
	createSenderRule: (...args) => mockCreateSenderRule(...args),
	deleteSenderRule: (...args) => mockDeleteSenderRule(...args)
}));

const { default: SenderRulesPanel } = await import('../SenderRulesPanel.svelte');

const mockRules = [
	{
		id: 'rule-1',
		user_id: 'user-1',
		sender_email: 'spam@example.com',
		sender_domain: null,
		action: 'ignore',
		created_at: '2024-01-01T00:00:00Z',
		updated_at: '2024-01-01T00:00:00Z'
	},
	{
		id: 'rule-2',
		user_id: 'user-1',
		sender_email: null,
		sender_domain: 'trusted.com',
		action: 'auto_approve',
		created_at: '2024-01-02T00:00:00Z',
		updated_at: '2024-01-02T00:00:00Z'
	}
];

describe('SenderRulesPanel', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockDeleteSenderRule.mockResolvedValue({ error: null });
	});

	it('shows loading state initially', () => {
		mockFetchSenderRules.mockReturnValue(new Promise(() => {}));

		render(SenderRulesPanel);

		expect(document.querySelector('.animate-pulse')).toBeTruthy();
	});

	it('shows empty state when no rules exist', async () => {
		mockFetchSenderRules.mockResolvedValue({ data: [], error: null });

		render(SenderRulesPanel);

		await waitFor(() => {
			expect(screen.getByText(/No automation rules yet/)).toBeInTheDocument();
		});
	});

	it('renders existing rules with correct labels', async () => {
		mockFetchSenderRules.mockResolvedValue({ data: mockRules, error: null });

		render(SenderRulesPanel);

		await waitFor(() => {
			// Check the rule row content (sender addresses shown in the list)
			expect(screen.getByText('spam@example.com')).toBeInTheDocument();
			expect(screen.getByText('trusted.com')).toBeInTheDocument();
			// Action labels appear in both rule rows and the select, so use getAllByText
			const ignoreElements = screen.getAllByText('Ignore');
			expect(ignoreElements.length).toBeGreaterThanOrEqual(2); // rule row + select option
			const autoApproveElements = screen.getAllByText('Auto-approve');
			expect(autoApproveElements.length).toBeGreaterThanOrEqual(2); // rule row + select option
		});
	});

	it('shows add rule form with input and select', async () => {
		mockFetchSenderRules.mockResolvedValue({ data: [], error: null });

		render(SenderRulesPanel);

		await waitFor(() => {
			expect(screen.getByPlaceholderText(/sender@example.com/)).toBeInTheDocument();
			expect(screen.getByRole('combobox', { name: /rule action/i })).toBeInTheDocument();
			expect(screen.getByRole('button', { name: /add rule/i })).toBeInTheDocument();
		});
	});

	it('creates a sender_email rule when input contains @', async () => {
		const user = userEvent.setup();
		mockFetchSenderRules.mockResolvedValue({ data: [], error: null });
		mockCreateSenderRule.mockResolvedValue({
			data: {
				id: 'rule-new',
				user_id: 'user-1',
				sender_email: 'test@example.com',
				sender_domain: null,
				action: 'ignore',
				created_at: '2024-01-03T00:00:00Z',
				updated_at: '2024-01-03T00:00:00Z'
			},
			error: null
		});

		render(SenderRulesPanel);

		await waitFor(() => {
			expect(screen.getByPlaceholderText(/sender@example.com/)).toBeInTheDocument();
		});

		const input = screen.getByPlaceholderText(/sender@example.com/);
		await user.type(input, 'test@example.com');
		await user.click(screen.getByRole('button', { name: /add rule/i }));

		await waitFor(() => {
			expect(mockCreateSenderRule).toHaveBeenCalledWith({
				sender_email: 'test@example.com',
				action: 'ignore'
			});
		});
	});

	it('creates a sender_domain rule when input does not contain @', async () => {
		const user = userEvent.setup();
		mockFetchSenderRules.mockResolvedValue({ data: [], error: null });
		mockCreateSenderRule.mockResolvedValue({
			data: {
				id: 'rule-new',
				user_id: 'user-1',
				sender_email: null,
				sender_domain: 'example.com',
				action: 'auto_approve',
				created_at: '2024-01-03T00:00:00Z',
				updated_at: '2024-01-03T00:00:00Z'
			},
			error: null
		});

		render(SenderRulesPanel);

		await waitFor(() => {
			expect(screen.getByPlaceholderText(/sender@example.com/)).toBeInTheDocument();
		});

		const input = screen.getByPlaceholderText(/sender@example.com/);
		await user.type(input, 'example.com');

		const actionSelect = screen.getByRole('combobox', { name: /rule action/i });
		await user.selectOptions(actionSelect, 'auto_approve');

		await user.click(screen.getByRole('button', { name: /add rule/i }));

		await waitFor(() => {
			expect(mockCreateSenderRule).toHaveBeenCalledWith({
				sender_domain: 'example.com',
				action: 'auto_approve'
			});
		});
	});

	it('shows delete button for each rule', async () => {
		mockFetchSenderRules.mockResolvedValue({ data: mockRules, error: null });

		render(SenderRulesPanel);

		await waitFor(() => {
			const deleteButtons = screen.getAllByRole('button', { name: /delete rule/i });
			expect(deleteButtons.length).toBe(2);
		});
	});

	it('shows confirm modal when delete is clicked', async () => {
		const user = userEvent.setup();
		mockFetchSenderRules.mockResolvedValue({ data: mockRules, error: null });

		render(SenderRulesPanel);

		await waitFor(() => {
			expect(screen.getByText('spam@example.com')).toBeInTheDocument();
		});

		const deleteButtons = screen.getAllByRole('button', { name: /delete rule/i });
		await user.click(deleteButtons[0]);

		await waitFor(() => {
			expect(screen.getByText('Delete rule')).toBeInTheDocument();
			// Modal description references the sender
			expect(screen.getByText(/Are you sure you want to delete the rule for spam@example.com/)).toBeInTheDocument();
		});
	});

	it('deletes rule after confirmation', async () => {
		const user = userEvent.setup();
		mockFetchSenderRules.mockResolvedValue({ data: [...mockRules], error: null });

		render(SenderRulesPanel);

		await waitFor(() => {
			expect(screen.getByText('spam@example.com')).toBeInTheDocument();
		});

		const deleteButtons = screen.getAllByRole('button', { name: /delete rule/i });
		await user.click(deleteButtons[0]);

		await waitFor(() => {
			expect(screen.getByText('Delete rule')).toBeInTheDocument();
		});

		// Find the confirm button inside the modal-action div
		const modalAction = document.querySelector('.modal-action');
		const confirmBtn = /** @type {HTMLElement} */ (modalAction?.querySelector('.btn-error'));
		await user.click(confirmBtn);

		await waitFor(() => {
			expect(mockDeleteSenderRule).toHaveBeenCalledWith('rule-1');
		});
	});

	it('shows error when fetch fails', async () => {
		mockFetchSenderRules.mockResolvedValue({
			data: [],
			error: { message: 'Network error', code: 'NETWORK_ERROR' }
		});

		render(SenderRulesPanel);

		await waitFor(() => {
			expect(screen.getByText('Network error')).toBeInTheDocument();
		});
	});

	it('disables add button when input is empty', async () => {
		mockFetchSenderRules.mockResolvedValue({ data: [], error: null });

		render(SenderRulesPanel);

		await waitFor(() => {
			const addButton = screen.getByRole('button', { name: /add rule/i });
			expect(addButton).toBeDisabled();
		});
	});
});
