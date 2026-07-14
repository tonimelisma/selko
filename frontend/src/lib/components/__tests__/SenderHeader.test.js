// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';

const { default: SenderHeader } = await import('../SenderHeader.svelte');

/** Opens the sender actions panel via its expander button. */
async function openMenu(user) {
	await user.click(screen.getByRole('button', { name: /actions for/i }));
}

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

	it('shows the menu expander for non-photo sources', () => {
		render(SenderHeader, {
			props: { sender: 'John Doe', senderEmail: 'john@example.com', eventCount: 1 }
		});

		expect(screen.getByRole('button', { name: /actions for/i })).toBeInTheDocument();
	});

	it('hides the menu expander for photo source with single event', () => {
		render(SenderHeader, {
			props: { sender: 'Google Photos', senderEmail: '', eventCount: 1, isPhotoSource: true }
		});

		expect(screen.queryByRole('button', { name: /actions for/i })).not.toBeInTheDocument();
	});

	it('shows the menu expander for photo source with multiple events', () => {
		render(SenderHeader, {
			props: { sender: 'Google Photos', senderEmail: '', eventCount: 3, isPhotoSource: true }
		});

		expect(screen.getByRole('button', { name: /actions for/i })).toBeInTheDocument();
	});

	it('keeps the actions panel closed by default (regression)', () => {
		render(SenderHeader, {
			props: { sender: 'John Doe', senderEmail: 'john@example.com', eventCount: 3 }
		});

		expect(screen.queryByText('Approve all')).not.toBeInTheDocument();
		expect(screen.queryByText('Ignore sender')).not.toBeInTheDocument();
		expect(screen.getByRole('button', { name: /actions for/i })).toHaveAttribute(
			'aria-expanded',
			'false'
		);
	});

	it('shows approve all and reject all only when eventCount > 1', async () => {
		const user = userEvent.setup();
		render(SenderHeader, {
			props: { sender: 'John Doe', senderEmail: 'john@example.com', eventCount: 2 }
		});

		await openMenu(user);
		expect(screen.getByText('Approve all')).toBeInTheDocument();
		expect(screen.getByText('Reject all')).toBeInTheDocument();
	});

	it('hides approve all and reject all when eventCount is 1', async () => {
		const user = userEvent.setup();
		render(SenderHeader, {
			props: { sender: 'John Doe', senderEmail: 'john@example.com', eventCount: 1 }
		});

		await openMenu(user);
		expect(screen.queryByText('Approve all')).not.toBeInTheDocument();
		expect(screen.queryByText('Reject all')).not.toBeInTheDocument();
	});

	it('shows ignore sender and auto-approve sender in the open panel', async () => {
		const user = userEvent.setup();
		render(SenderHeader, {
			props: { sender: 'John Doe', senderEmail: 'john@example.com', eventCount: 1 }
		});

		await openMenu(user);
		expect(screen.getByText('Ignore sender')).toBeInTheDocument();
		expect(screen.getByText('Auto-approve sender')).toBeInTheDocument();
	});

	it('calls onignoreSender and closes the panel when ignore sender is clicked', async () => {
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

		await openMenu(user);
		await user.click(screen.getByText('Ignore sender'));
		expect(mockIgnore).toHaveBeenCalled();
		expect(screen.queryByText('Ignore sender')).not.toBeInTheDocument();
	});

	it('calls onautoApproveSender once per click (one-shot button, not a toggle)', async () => {
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

		await openMenu(user);
		await user.click(screen.getByText('Auto-approve sender'));
		expect(mockAutoApprove).toHaveBeenCalledTimes(1);
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

		await openMenu(user);
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

		await openMenu(user);
		await user.click(screen.getByText('Reject all'));
		expect(mockRejectAll).toHaveBeenCalled();
	});
});
