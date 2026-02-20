// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';

const { default: SenderHeader } = await import('../SenderHeader.svelte');

describe('SenderHeader', () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it('renders sender name and event count', () => {
		render(SenderHeader, {
			props: { sender: 'John Doe', senderEmail: 'john@example.com', eventCount: 3 }
		});

		expect(screen.getByText('John Doe')).toBeInTheDocument();
		expect(screen.getByText('3 events')).toBeInTheDocument();
	});

	it('renders singular event text for single event', () => {
		render(SenderHeader, {
			props: { sender: 'John Doe', senderEmail: 'john@example.com', eventCount: 1 }
		});

		expect(screen.getByText('1 event')).toBeInTheDocument();
	});

	it('always shows the dropdown menu button', () => {
		render(SenderHeader, {
			props: { sender: 'John Doe', senderEmail: 'john@example.com', eventCount: 1 }
		});

		expect(screen.getByRole('button', { name: /actions for/i })).toBeInTheDocument();
	});

	it('shows approve all and reject all only when eventCount > 1', () => {
		render(SenderHeader, {
			props: { sender: 'John Doe', senderEmail: 'john@example.com', eventCount: 2 }
		});

		expect(screen.getByText('Approve all')).toBeInTheDocument();
		expect(screen.getByText('Reject all')).toBeInTheDocument();
	});

	it('hides approve all and reject all when eventCount is 1', () => {
		render(SenderHeader, {
			props: { sender: 'John Doe', senderEmail: 'john@example.com', eventCount: 1 }
		});

		expect(screen.queryByText('Approve all')).not.toBeInTheDocument();
		expect(screen.queryByText('Reject all')).not.toBeInTheDocument();
	});

	it('always shows ignore sender and auto-approve sender buttons', () => {
		render(SenderHeader, {
			props: { sender: 'John Doe', senderEmail: 'john@example.com', eventCount: 1 }
		});

		expect(screen.getByText('Ignore sender')).toBeInTheDocument();
		expect(screen.getByText('Auto-approve sender')).toBeInTheDocument();
	});

	it('calls onignoreSender when ignore sender is clicked', async () => {
		const user = userEvent.setup();
		const mockIgnore = vi.fn();
		render(SenderHeader, {
			props: {
				sender: 'John Doe',
				senderEmail: 'john@example.com',
				eventCount: 1,
				onignoreSender: mockIgnore
			}
		});

		await user.click(screen.getByText('Ignore sender'));
		expect(mockIgnore).toHaveBeenCalled();
	});

	it('calls onautoApproveSender when auto-approve sender is clicked', async () => {
		const user = userEvent.setup();
		const mockAutoApprove = vi.fn();
		render(SenderHeader, {
			props: {
				sender: 'John Doe',
				senderEmail: 'john@example.com',
				eventCount: 1,
				onautoApproveSender: mockAutoApprove
			}
		});

		await user.click(screen.getByText('Auto-approve sender'));
		expect(mockAutoApprove).toHaveBeenCalled();
	});

	it('calls onapproveAll when approve all is clicked', async () => {
		const user = userEvent.setup();
		const mockApproveAll = vi.fn();
		render(SenderHeader, {
			props: {
				sender: 'John Doe',
				senderEmail: 'john@example.com',
				eventCount: 3,
				onapproveAll: mockApproveAll
			}
		});

		await user.click(screen.getByText('Approve all'));
		expect(mockApproveAll).toHaveBeenCalled();
	});

	it('calls onrejectAll when reject all is clicked', async () => {
		const user = userEvent.setup();
		const mockRejectAll = vi.fn();
		render(SenderHeader, {
			props: {
				sender: 'John Doe',
				senderEmail: 'john@example.com',
				eventCount: 3,
				onrejectAll: mockRejectAll
			}
		});

		await user.click(screen.getByText('Reject all'));
		expect(mockRejectAll).toHaveBeenCalled();
	});
});
