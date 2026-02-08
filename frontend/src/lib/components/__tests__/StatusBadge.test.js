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

	it('renders synced event status with success badge', () => {
		render(StatusBadge, { props: { status: 'synced', type: 'event' } });
		const badge = screen.getByText('Synced');
		expect(badge).toBeInTheDocument();
		expect(badge.className).toContain('badge-success');
	});

	it('renders sync_failed event status with error badge', () => {
		render(StatusBadge, { props: { status: 'sync_failed', type: 'event' } });
		const badge = screen.getByText('Failed');
		expect(badge).toBeInTheDocument();
		expect(badge.className).toContain('badge-error');
	});

	it('renders rejected event status with ghost badge', () => {
		render(StatusBadge, { props: { status: 'rejected', type: 'event' } });
		const badge = screen.getByText('Rejected');
		expect(badge).toBeInTheDocument();
		expect(badge.className).toContain('badge-ghost');
	});

	it('renders active integration status', () => {
		render(StatusBadge, { props: { status: 'active', type: 'integration' } });
		const badge = screen.getByText('Authorized');
		expect(badge).toBeInTheDocument();
		expect(badge.className).toContain('badge-success');
	});

	it('renders expired integration status', () => {
		render(StatusBadge, { props: { status: 'expired', type: 'integration' } });
		const badge = screen.getByText('Expired');
		expect(badge).toBeInTheDocument();
		expect(badge.className).toContain('badge-error');
	});

	it('renders not_connected integration status', () => {
		render(StatusBadge, { props: { status: 'not_connected', type: 'integration' } });
		const badge = screen.getByText('Not Connected');
		expect(badge).toBeInTheDocument();
		expect(badge.className).toContain('badge-ghost');
	});

	it('defaults to event type', () => {
		render(StatusBadge, { props: { status: 'synced' } });
		expect(screen.getByText('Synced')).toBeInTheDocument();
	});
});
