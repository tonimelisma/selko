// @ts-nocheck
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';

const { default: StatusBadge } = await import('../StatusBadge.svelte');

describe('StatusBadge', () => {
	it('renders pending_review event status', () => {
		render(StatusBadge, { props: { status: 'pending_review', type: 'event' } });
		expect(screen.getByText('Pending')).toBeInTheDocument();
	});

	it('renders approved event status', () => {
		render(StatusBadge, { props: { status: 'approved', type: 'event' } });
		expect(screen.getByText('Approved')).toBeInTheDocument();
	});

	it('renders pending_change as a localized status', () => {
		render(StatusBadge, { props: { status: 'pending_change', type: 'event' } });
		expect(screen.getByRole('status')).toHaveClass('semantic-status-neutral');
		expect(screen.getByText('Pending change')).toBeInTheDocument();
		expect(screen.queryByText('pending_change')).not.toBeInTheDocument();
	});

	it('renders synced event status as a successful status indicator', () => {
		render(StatusBadge, { props: { status: 'synced', type: 'event' } });
		expect(screen.getByRole('status')).toHaveClass('semantic-status-success');
		expect(screen.getByText('Synced')).toBeInTheDocument();
	});

	it('renders sync_failed event status with error badge', () => {
		render(StatusBadge, { props: { status: 'sync_failed', type: 'event' } });
		expect(screen.getByRole('status')).toHaveClass('semantic-status-error');
		expect(screen.getByText('Failed')).toBeInTheDocument();
	});

	it('renders rejected event status with ghost badge', () => {
		render(StatusBadge, { props: { status: 'rejected', type: 'event' } });
		expect(screen.getByRole('status')).toHaveClass('semantic-status-error');
		expect(screen.getByText('Rejected')).toBeInTheDocument();
	});

	it('renders active integration status', () => {
		render(StatusBadge, { props: { status: 'active', type: 'integration' } });
		expect(screen.getByRole('status')).toHaveClass('semantic-status-success');
		expect(screen.getByText('Connected')).toBeInTheDocument();
	});

	it('renders expired integration status', () => {
		render(StatusBadge, { props: { status: 'expired', type: 'integration' } });
		expect(screen.getByRole('status')).toHaveClass('semantic-status-error');
		expect(screen.getByText('Expired')).toBeInTheDocument();
	});

	it('renders not_connected integration status', () => {
		render(StatusBadge, { props: { status: 'not_connected', type: 'integration' } });
		expect(screen.getByRole('status')).toHaveClass('semantic-status-neutral');
		expect(screen.getByText('Not Connected')).toBeInTheDocument();
	});

	it('defaults to event type', () => {
		render(StatusBadge, { props: { status: 'synced' } });
		expect(screen.getByText('Synced')).toBeInTheDocument();
	});
});
