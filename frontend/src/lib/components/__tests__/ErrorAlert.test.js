// @ts-nocheck
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';

const { default: ErrorAlert } = await import('../ErrorAlert.svelte');

describe('ErrorAlert', () => {
	it('renders error message', () => {
		render(ErrorAlert, {
			props: { message: 'Something went wrong' }
		});

		expect(screen.getByText('Something went wrong')).toBeInTheDocument();
	});

	it('has alert role and aria-live for accessibility', () => {
		render(ErrorAlert, {
			props: { message: 'Error occurred' }
		});

		const alert = screen.getByRole('alert');
		expect(alert).toBeInTheDocument();
		expect(alert).toHaveAttribute('aria-live', 'polite');
	});

	it('renders retry button when onretry is provided', () => {
		const onretry = vi.fn();
		render(ErrorAlert, {
			props: { message: 'Failed to load', onretry }
		});

		expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument();
	});

	it('calls onretry when retry button is clicked', async () => {
		const user = userEvent.setup();
		const onretry = vi.fn();
		render(ErrorAlert, {
			props: { message: 'Failed to load', onretry }
		});

		await user.click(screen.getByRole('button', { name: 'Retry' }));
		expect(onretry).toHaveBeenCalledOnce();
	});

	it('does not render retry button when onretry is not provided', () => {
		render(ErrorAlert, {
			props: { message: 'Error occurred' }
		});

		expect(screen.queryByRole('button', { name: 'Retry' })).not.toBeInTheDocument();
	});

	it('renders action button when onaction and actionLabel are provided', () => {
		const onaction = vi.fn();
		render(ErrorAlert, {
			props: { message: 'Not found', onaction, actionLabel: 'Go Back' }
		});

		expect(screen.getByRole('button', { name: 'Go Back' })).toBeInTheDocument();
	});

	it('calls onaction when action button is clicked', async () => {
		const user = userEvent.setup();
		const onaction = vi.fn();
		render(ErrorAlert, {
			props: { message: 'Not found', onaction, actionLabel: 'Go Back' }
		});

		await user.click(screen.getByRole('button', { name: 'Go Back' }));
		expect(onaction).toHaveBeenCalledOnce();
	});

	it('does not render when message is empty', () => {
		render(ErrorAlert, {
			props: { message: '' }
		});

		expect(screen.queryByRole('alert')).not.toBeInTheDocument();
	});
});
