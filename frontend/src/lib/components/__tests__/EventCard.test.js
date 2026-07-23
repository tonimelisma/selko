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
	status: 'pending_review',
	importance: 'action_required'
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

	it('shows the date alongside "All Day" for all-day events', () => {
		const allDayEvent = { ...mockEvent, all_day: true };
		render(EventCard, { props: { event: allDayEvent } });
		expect(screen.getByText(/Jan 20.*All Day/)).toBeInTheDocument();
	});

	it('shows just "All Day" when an all-day event has no start_datetime', () => {
		const allDayEvent = {
			...mockEvent,
			all_day: true,
			start_datetime: null,
			end_datetime: null
		};
		render(EventCard, { props: { event: allDayEvent } });
		expect(screen.getByText('All Day')).toBeInTheDocument();
	});

	it('shows a date range for a multi-day all-day event', () => {
		// Worked example from the spec: a 3-day closure, Aug 12-14 local (America/Los_Angeles)
		const multiDayEvent = {
			...mockEvent,
			all_day: true,
			start_datetime: '2026-08-12T07:00:00Z',
			end_datetime: '2026-08-15T06:59:59Z'
		};
		render(EventCard, { props: { event: multiDayEvent } });
		expect(screen.getByText(/Aug 12.*–.*Aug 14.*All Day/)).toBeInTheDocument();
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

	it('renders long descriptions in the DOM for line-clamp', () => {
		const longEvent = {
			...mockEvent,
			description: 'A'.repeat(200)
		};
		render(EventCard, { props: { event: longEvent } });
		// Full text stays in the DOM; CSS line-clamp-3 handles visual truncation
		expect(screen.getByText('A'.repeat(200))).toBeInTheDocument();
	});

	it('does not show Show more when description fits without overflow', () => {
		render(EventCard, { props: { event: mockEvent } });
		expect(screen.queryByRole('button', { name: /show more/i })).not.toBeInTheDocument();
	});

	it('shows Show more when description overflows and toggles expansion', async () => {
		const user = userEvent.setup();
		const longDescription =
			'Line one of a long calendar description.\n' +
			'Line two continues with more detail.\n' +
			'Line three adds still more context.\n' +
			'Line four should force overflow beyond three lines.';
		const longEvent = { ...mockEvent, description: longDescription };

		const scrollDesc = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollHeight');
		const clientDesc = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientHeight');
		Object.defineProperty(HTMLElement.prototype, 'scrollHeight', {
			configurable: true,
			get() {
				return this.classList?.contains('line-clamp-3') ? 120 : 40;
			}
		});
		Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
			configurable: true,
			get() {
				return 40;
			}
		});

		try {
			render(EventCard, { props: { event: longEvent } });

			const showMore = await screen.findByRole('button', { name: /show more/i });
			expect(showMore).toHaveAttribute('aria-expanded', 'false');
			expect(
				screen.getByText((_, node) => node?.textContent === longDescription)
			).toBeInTheDocument();

			await user.click(showMore);
			const showLess = screen.getByRole('button', { name: /show less/i });
			expect(showLess).toHaveAttribute('aria-expanded', 'true');
			expect(
				screen.getByText((_, node) => node?.textContent === longDescription)
			).toBeInTheDocument();

			await user.click(showLess);
			expect(screen.getByRole('button', { name: /show more/i })).toHaveAttribute(
				'aria-expanded',
				'false'
			);
		} finally {
			if (scrollDesc) Object.defineProperty(HTMLElement.prototype, 'scrollHeight', scrollDesc);
			else delete HTMLElement.prototype.scrollHeight;
			if (clientDesc) Object.defineProperty(HTMLElement.prototype, 'clientHeight', clientDesc);
			else delete HTMLElement.prototype.clientHeight;
		}
	});

	it('stops propagation when toggling description expansion', async () => {
		const user = userEvent.setup();
		const longEvent = {
			...mockEvent,
			description: 'A'.repeat(200)
		};
		const parentClick = vi.fn();

		const scrollDesc = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'scrollHeight');
		const clientDesc = Object.getOwnPropertyDescriptor(HTMLElement.prototype, 'clientHeight');
		Object.defineProperty(HTMLElement.prototype, 'scrollHeight', {
			configurable: true,
			get() {
				return this.classList?.contains('line-clamp-3') ? 120 : 40;
			}
		});
		Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
			configurable: true,
			get() {
				return 40;
			}
		});

		try {
			const { container } = render(EventCard, { props: { event: longEvent } });
			const card = container.querySelector('.warm-card-row');
			card?.addEventListener('click', parentClick);

			const showMore = await screen.findByRole('button', { name: /show more/i });
			await user.click(showMore);

			expect(parentClick).not.toHaveBeenCalled();
			expect(screen.getByRole('button', { name: /show less/i })).toBeInTheDocument();
		} finally {
			if (scrollDesc) Object.defineProperty(HTMLElement.prototype, 'scrollHeight', scrollDesc);
			else delete HTMLElement.prototype.scrollHeight;
			if (clientDesc) Object.defineProperty(HTMLElement.prototype, 'clientHeight', clientDesc);
			else delete HTMLElement.prototype.clientHeight;
		}
	});

	it('does not show FYI badge for action_required events', () => {
		render(EventCard, { props: { event: mockEvent } });
		expect(screen.queryByText('FYI')).not.toBeInTheDocument();
	});

	it('shows FYI badge for fyi events', () => {
		const fyiEvent = { ...mockEvent, importance: 'fyi' };
		render(EventCard, { props: { event: fyiEvent } });
		expect(screen.getByText('FYI')).toBeInTheDocument();
	});

	it('shows email icon by default', () => {
		render(EventCard, { props: { event: mockEvent } });
		const emailIcon = document.querySelector('svg[aria-label="From email"]');
		expect(emailIcon).toBeInTheDocument();
	});

	it('shows photo icon for google_photos source', () => {
		const photoEvent = {
			...mockEvent,
			event_sources: [{ source_origin: 'google_photos' }]
		};
		render(EventCard, { props: { event: photoEvent } });
		const photoIcon = document.querySelector('svg[aria-label="From photo"]');
		expect(photoIcon).toBeInTheDocument();
	});

	it('shows spinner inside action buttons while processing', () => {
		render(EventCard, { props: { event: mockEvent, isProcessing: true } });
		expect(document.querySelector('.loading.loading-spinner')).toBeTruthy();
		expect(screen.getByRole('button', { name: /accept event/i })).toBeDisabled();
		expect(screen.getByRole('button', { name: /reject event/i })).toBeDisabled();
	});
});
