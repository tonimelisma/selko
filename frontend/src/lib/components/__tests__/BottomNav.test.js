// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import { writable } from 'svelte/store';

const mockPage = writable({
	url: { pathname: '/app' },
	params: {},
	route: { id: '' },
	status: 200,
	error: null,
	data: {},
	form: null
});

vi.mock('$app/stores', () => ({
	page: mockPage
}));

const { default: BottomNav } = await import('../BottomNav.svelte');

describe('BottomNav', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockPage.set({
			url: { pathname: '/app' },
			params: {},
			route: { id: '' },
			status: 200,
			error: null,
			data: {},
			form: null
		});
	});

	it('renders three navigation tabs', () => {
		render(BottomNav);
		expect(screen.getByText('Review')).toBeInTheDocument();
		expect(screen.getByText('History')).toBeInTheDocument();
		expect(screen.getByText('Settings')).toBeInTheDocument();
	});

	it('has correct link hrefs', () => {
		render(BottomNav);

		const links = document.querySelectorAll('.btm-nav a');
		expect(links[0]).toHaveAttribute('href', '/app');
		expect(links[1]).toHaveAttribute('href', '/app/history');
		expect(links[2]).toHaveAttribute('href', '/app/settings');
	});

	it('marks Review as active when on /app', () => {
		mockPage.set({
			url: { pathname: '/app' },
			params: {},
			route: { id: '' },
			status: 200,
			error: null,
			data: {},
			form: null
		});

		render(BottomNav);

		const reviewLink = screen.getByText('Review').closest('a');
		expect(reviewLink.className).toContain('active');
	});
});
