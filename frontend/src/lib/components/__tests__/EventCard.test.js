// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';

const { default: EventCard } = await import('../EventCard.svelte');

const mockEvent = {
	id: 'evt-1',
	title: 'Team Meeting',
	start_datetime: '2024-01-20T14:00:00Z',
	end_datetime: '2024-01-20T15:00:00Z',
	all_day: false,
	location: 'Room 101',
	description: 'Discuss project updates and next steps for the quarterly review.',
	status: 'pending_review'
};

describe('EventCard', () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it('renders event title', () => {
		render(EventCard, { props: { event: mockEvent } });
		expect(screen.getByText('Team Meeting')).toBeInTheDocument();
	});

	it('renders event location', () => {
		render(EventCard, { props: { event: mockEvent } });
		expect(screen.getByText('Room 101')).toBeInTheDocument();
	});

	it('renders event description', () => {
		render(EventCard, { props: { event: mockEvent } });
		expect(
			screen.getByText(/Discuss project updates/)
		).toBeInTheDocument();
	});

	it('shows "All Day" for all-day events', () => {
		const allDayEvent = { ...mockEvent, all_day: true };
		render(EventCard, { props: { event: allDayEvent } });
		expect(screen.getByText('All Day')).toBeInTheDocument();
	});

	it('has accept and reject buttons', () => {
		render(EventCard, { props: { event: mockEvent } });
		expect(screen.getByRole('button', { name: /accept event/i })).toBeInTheDocument();
		expect(screen.getByRole('button', { name: /reject event/i })).toBeInTheDocument();
	});

	it('calls onapprove when accept button is clicked', async () => {
		const user = userEvent.setup();
		const mockApprove = vi.fn();
		render(EventCard, {
			props: { event: mockEvent, onapprove: mockApprove }
		});

		await user.click(screen.getByRole('button', { name: /accept event/i }));
		expect(mockApprove).toHaveBeenCalledWith(mockEvent);
	});

	it('calls onreject when reject button is clicked', async () => {
		const user = userEvent.setup();
		const mockReject = vi.fn();
		render(EventCard, {
			props: { event: mockEvent, onreject: mockReject }
		});

		await user.click(screen.getByRole('button', { name: /reject event/i }));
		expect(mockReject).toHaveBeenCalledWith(mockEvent);
	});

	it('renders long descriptions with CSS truncation', () => {
		const longEvent = {
			...mockEvent,
			description: 'A'.repeat(200)
		};
		render(EventCard, { props: { event: longEvent } });
		// Description is rendered in full; CSS line-clamp-2 handles visual truncation
		expect(screen.getByText('A'.repeat(200))).toBeInTheDocument();
	});
});
