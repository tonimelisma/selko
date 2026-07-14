// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, within } from '@testing-library/svelte';
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

// Mock the user store so importing Navbar never constructs the real
// Supabase client (stores.js -> supabase.js needs env vars absent in CI).
const mockUser = writable({ email: 'tester@example.com' });
vi.mock('$lib/stores.js', () => ({
	user: mockUser
}));

const { default: Navbar } = await import('../Navbar.svelte');

/**
 * The Navbar renders BOTH layouts (desktop sidebar + mobile header) and hides
 * one via CSS breakpoints, so queries must be scoped to a container.
 */
function getSidebar() {
	const aside = document.querySelector('aside');
	expect(aside).toBeTruthy();
	return within(aside);
}

function getMobileHeader() {
	const header = document.querySelector('header');
	expect(header).toBeTruthy();
	return within(header);
}

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

	it('renders the Selko brand name in both layouts', () => {
		render(Navbar, { props: { onLogout: vi.fn() } });
		// Sidebar shows "Selko" twice (brand + footer caption).
		expect(getSidebar().getAllByText('Selko').length).toBeGreaterThan(0);
		expect(getMobileHeader().getByText('Selko')).toBeInTheDocument();
	});

	it('renders navigation links in both layouts', () => {
		render(Navbar, { props: { onLogout: vi.fn() } });
		for (const scope of [getSidebar(), getMobileHeader()]) {
			expect(scope.getByText('Review')).toBeInTheDocument();
			expect(scope.getByText('History')).toBeInTheDocument();
			expect(scope.getByText('Settings')).toBeInTheDocument();
		}
	});

	it('renders a logout button in the desktop sidebar', () => {
		render(Navbar, { props: { onLogout: vi.fn() } });
		expect(getSidebar().getByRole('button', { name: /log out/i })).toBeInTheDocument();
	});

	it('has no logout button in the mobile header (logout lives in Settings)', () => {
		render(Navbar, { props: { onLogout: vi.fn() } });
		expect(getMobileHeader().queryByRole('button', { name: /log out/i })).toBeNull();
	});

	it('calls onLogout when the sidebar logout button is clicked', async () => {
		const user = userEvent.setup();
		const mockLogout = vi.fn();
		render(Navbar, { props: { onLogout: mockLogout } });

		await user.click(getSidebar().getByRole('button', { name: /log out/i }));
		expect(mockLogout).toHaveBeenCalled();
	});

	it('shows the signed-in email in the sidebar footer', () => {
		render(Navbar, { props: { onLogout: vi.fn() } });
		expect(getSidebar().getByText('tester@example.com')).toBeInTheDocument();
	});

	it('keeps the mobile header sticky so it stays on screen while scrolling', () => {
		render(Navbar, { props: { onLogout: vi.fn() } });
		const header = document.querySelector('header');
		expect(header.className).toContain('sticky');
		expect(header.className).toContain('top-0');
	});

	it('hides layouts with CSS breakpoints, not JS', () => {
		render(Navbar, { props: { onLogout: vi.fn() } });
		// Desktop sidebar hidden below lg; mobile header hidden at lg and up.
		expect(document.querySelector('aside').className).toContain('lg:flex');
		expect(document.querySelector('aside').className).toContain('hidden');
		expect(document.querySelector('header').className).toContain('lg:hidden');
	});

	it('marks the current route with aria-current in both layouts', () => {
		render(Navbar, { props: { onLogout: vi.fn() } });
		const currentLinks = document.querySelectorAll('a[aria-current="page"]');
		expect(currentLinks.length).toBe(2);
		for (const link of currentLinks) {
			expect(link.getAttribute('href')).toBe('/app');
		}
	});
});
