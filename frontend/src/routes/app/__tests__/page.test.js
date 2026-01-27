// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import { writable } from 'svelte/store';

// Create controllable stores
const mockUser = writable(null);
const mockLoading = writable(true);

// Mock SvelteKit navigation
const mockGoto = vi.fn();
vi.mock('$app/navigation', () => ({
	goto: (...args) => mockGoto(...args)
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
const { default: AppPage } = await import('../+page.svelte');

describe('App Page', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockUser.set(null);
		mockLoading.set(true);
		mockSignOut.mockResolvedValue({ error: null });
	});

	it('shows loading spinner when loading', () => {
		mockLoading.set(true);
		mockUser.set(null);

		render(AppPage);

		// DaisyUI loading spinner uses these classes
		expect(document.querySelector('.loading.loading-spinner')).toBeTruthy();
	});

	it('displays user email when authenticated', async () => {
		mockLoading.set(false);
		mockUser.set({ id: '123', email: 'test@example.com' });

		render(AppPage);

		await waitFor(() => {
			expect(screen.getByText(/hello, test@example.com/i)).toBeInTheDocument();
		});
	});

	it('displays welcome message for authenticated user', async () => {
		mockLoading.set(false);
		mockUser.set({ id: '123', email: 'user@selko.local' });

		render(AppPage);

		await waitFor(() => {
			expect(screen.getByText(/welcome to selko/i)).toBeInTheDocument();
		});
	});

	it('redirects to login when not authenticated and not loading', async () => {
		mockLoading.set(false);
		mockUser.set(null);

		render(AppPage);

		await waitFor(() => {
			expect(mockGoto).toHaveBeenCalledWith('/login');
		});
	});

	it('does not redirect while loading', async () => {
		mockLoading.set(true);
		mockUser.set(null);

		render(AppPage);

		// Wait a bit to make sure no redirect happens
		await new Promise((resolve) => setTimeout(resolve, 100));

		expect(mockGoto).not.toHaveBeenCalled();
	});

	it('has a logout button', async () => {
		mockLoading.set(false);
		mockUser.set({ id: '123', email: 'test@example.com' });

		render(AppPage);

		await waitFor(() => {
			expect(screen.getByRole('button', { name: /logout/i })).toBeInTheDocument();
		});
	});

	it('calls signOut when logout button is clicked', async () => {
		const user = userEvent.setup();
		mockLoading.set(false);
		mockUser.set({ id: '123', email: 'test@example.com' });

		render(AppPage);

		await waitFor(() => {
			expect(screen.getByRole('button', { name: /logout/i })).toBeInTheDocument();
		});

		await user.click(screen.getByRole('button', { name: /logout/i }));

		expect(mockSignOut).toHaveBeenCalled();
	});

	it('redirects to login after logout', async () => {
		const user = userEvent.setup();
		mockLoading.set(false);
		mockUser.set({ id: '123', email: 'test@example.com' });

		render(AppPage);

		await waitFor(() => {
			expect(screen.getByRole('button', { name: /logout/i })).toBeInTheDocument();
		});

		await user.click(screen.getByRole('button', { name: /logout/i }));

		expect(mockGoto).toHaveBeenCalledWith('/login');
	});

	it('displays the Selko brand name', async () => {
		mockLoading.set(false);
		mockUser.set({ id: '123', email: 'test@example.com' });

		render(AppPage);

		await waitFor(() => {
			expect(screen.getByText('Selko')).toBeInTheDocument();
		});
	});
});
