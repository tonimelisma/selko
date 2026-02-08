// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import { writable, readable } from 'svelte/store';

// Create controllable stores
const mockUser = writable(null);
const mockLoading = writable(true);

// Mock SvelteKit navigation and stores together
// (vitest resolves both $app/navigation and $app/stores to the same module)
const mockGoto = vi.fn();
const mockPage = writable({
	url: { pathname: '/app' },
	params: {},
	route: { id: '' },
	status: 200,
	error: null,
	data: {},
	form: null
});

vi.mock('$app/navigation', () => ({
	goto: (...args) => mockGoto(...args),
	// Also export $app/stores exports since they resolve to the same file
	page: mockPage,
	navigating: readable(null),
	updated: {
		subscribe: readable(false).subscribe,
		check: vi.fn()
	}
}));

vi.mock('$app/stores', () => ({
	goto: (...args) => mockGoto(...args),
	page: mockPage,
	navigating: readable(null),
	updated: {
		subscribe: readable(false).subscribe,
		check: vi.fn()
	}
}));

// Mock stores
vi.mock('$lib/stores.js', () => ({
	user: mockUser,
	loading: mockLoading
}));

// Mock Supabase
const mockSignOut = vi.fn();
vi.mock('$lib/supabase.js', () => ({
	supabase: {
		auth: {
			signOut: (...args) => mockSignOut(...args)
		}
	}
}));

// Import after mocking
const { default: AppLayout } = await import('../+layout.svelte');

describe('App Layout', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockUser.set(null);
		mockLoading.set(true);
		mockSignOut.mockResolvedValue({ error: null });
	});

	it('shows loading spinner when loading', () => {
		mockLoading.set(true);
		mockUser.set(null);

		render(AppLayout);

		expect(document.querySelector('.loading.loading-spinner')).toBeTruthy();
	});

	it('redirects to login when not authenticated', async () => {
		mockLoading.set(false);
		mockUser.set(null);

		render(AppLayout);

		await waitFor(() => {
			expect(mockGoto).toHaveBeenCalledWith('/login');
		});
	});

	it('does not redirect while loading', async () => {
		mockLoading.set(true);
		mockUser.set(null);

		render(AppLayout);

		await new Promise((resolve) => setTimeout(resolve, 100));
		expect(mockGoto).not.toHaveBeenCalled();
	});

	it('renders navbar when authenticated', async () => {
		mockLoading.set(false);
		mockUser.set({ id: '123', email: 'test@example.com' });

		render(AppLayout);

		await waitFor(() => {
			expect(screen.getByText('Selko')).toBeInTheDocument();
		});
	});

	it('renders navigation links when authenticated', async () => {
		mockLoading.set(false);
		mockUser.set({ id: '123', email: 'test@example.com' });

		render(AppLayout);

		await waitFor(() => {
			// Both Navbar and BottomNav render these links
			expect(screen.getAllByText('Review').length).toBeGreaterThanOrEqual(1);
			expect(screen.getAllByText('History').length).toBeGreaterThanOrEqual(1);
			expect(screen.getAllByText('Settings').length).toBeGreaterThanOrEqual(1);
		});
	});
});
