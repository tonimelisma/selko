// @ts-nocheck
import { describe, it, expect, vi, afterEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import DispositionedCard from '../DispositionedCard.svelte';

describe('DispositionedCard', () => {
	afterEach(() => {
		vi.useRealTimers();
		vi.restoreAllMocks();
	});

	it('keeps feedback out of the page live region', () => {
		render(DispositionedCard, { event: { id: 'event-1' }, kind: 'accept' });

		expect(screen.queryByRole('status')).not.toBeInTheDocument();
		expect(screen.getByText('Accepted')).toBeInTheDocument();
	});

	it('cleans up reduced-motion subscriptions', () => {
		const addEventListener = vi.fn();
		const removeEventListener = vi.fn();
		window.matchMedia = vi.fn().mockReturnValue({
			matches: true,
			media: '(prefers-reduced-motion: reduce)',
			addEventListener,
			removeEventListener
		});

		const { unmount } = render(DispositionedCard, { event: { id: 'event-1' } });
		expect(addEventListener).toHaveBeenCalledWith('change', expect.any(Function));
		unmount();
		expect(removeEventListener).toHaveBeenCalledWith('change', expect.any(Function));
	});

	it('focuses the next card after a disposition', async () => {
		vi.useFakeTimers();
		render(DispositionedCard, { event: { id: 'event-1' }, kind: 'reject' });
		const next = document.createElement('div');
		next.dataset.eventId = 'event-2';
		const button = document.createElement('button');
		next.append(button);
		document.body.append(next);

		await vi.advanceTimersByTimeAsync(200);
		expect(button).toHaveFocus();
	});
});
