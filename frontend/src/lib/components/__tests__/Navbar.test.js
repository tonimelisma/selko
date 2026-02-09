// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { writable } from 'svelte/store';

// Mock $app/stores with writable so we can change pathname
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

const { default: Navbar } = await import('../Navbar.svelte');

describe('Navbar', () => {
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

	it('renders the Selko brand name', () => {
		render(Navbar, { props: { onLogout: vi.fn() } });
		expect(screen.getByText('Selko')).toBeInTheDocument();
	});

	it('renders navigation links', () => {
		render(Navbar, { props: { onLogout: vi.fn() } });
		expect(screen.getByText('Review')).toBeInTheDocument();
		expect(screen.getByText('History')).toBeInTheDocument();
		expect(screen.getByText('Settings')).toBeInTheDocument();
	});

	it('renders logout button', () => {
		render(Navbar, { props: { onLogout: vi.fn() } });
		expect(screen.getByRole('button', { name: /log out/i })).toBeInTheDocument();
	});

	it('calls onLogout when logout button is clicked', async () => {
		const user = userEvent.setup();
		const mockLogout = vi.fn();
		render(Navbar, { props: { onLogout: mockLogout } });

		await user.click(screen.getByRole('button', { name: /log out/i }));
		expect(mockLogout).toHaveBeenCalled();
	});

	it('has correct link hrefs', () => {
		render(Navbar, { props: { onLogout: vi.fn() } });

		const reviewLink = screen.getByText('Review').closest('a');
		expect(reviewLink).toHaveAttribute('href', '/app');

		const historyLink = screen.getByText('History').closest('a');
		expect(historyLink).toHaveAttribute('href', '/app/history');

		const settingsLink = screen.getByText('Settings').closest('a');
		expect(settingsLink).toHaveAttribute('href', '/app/settings');
	});
});
