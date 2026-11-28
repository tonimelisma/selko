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
const mockUnavailable = writable(false);
const mockRetryAuth = vi.fn();
vi.mock('$lib/stores.js', () => ({
	user: mockUser,
	loading: mockLoading,
	authUnavailable: mockUnavailable,
	retryAuth: (...args) => mockRetryAuth(...args)
}));

// Mock auth and live updates
const mockSignOut = vi.fn();
vi.mock('$lib/auth.js', () => ({
	signOut: (...args) => mockSignOut(...args)
}));
const mockLive = {
	start: vi.fn(),
	stop: vi.fn().mockResolvedValue(undefined),
	catchUp: vi.fn()
};
vi.mock('$lib/live-updates.js', () => ({
	start: (...args) => mockLive.start(...args),
	stop: (...args) => mockLive.stop(...args),
	catchUp: (...args) => mockLive.catchUp(...args)
}));

// Import after mocking
const { default: AppLayout } = await import('../+layout.svelte');

describe('App Layout', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		mockUser.set(null);
		mockLoading.set(true);
		mockUnavailable.set(false);
		mockSignOut.mockResolvedValue(undefined);
		mockLive.stop.mockResolvedValue(undefined);
	});

	it('shows loading spinner when loading', () => {
		mockLoading.set(true);
		mockUser.set(null);

		render(AppLayout);

		expect(document.querySelector('.loading.loading-spinner')).toBeTruthy();
	});

	// Validates: SEL-516
	it('redirects to login when not authenticated', async () => {
		mockLoading.set(false);
		mockUser.set(null);

		render(AppLayout);

		await waitFor(() => {
			expect(mockGoto).toHaveBeenCalledWith('/login');
		});
	});

	// Validates: SEL-516
	it('keeps the deep link the user opened when sending them to sign in', async () => {
		window.history.replaceState({}, '', '/app/events/e1?tab=source');
		mockLoading.set(false);
		mockUser.set(null);

		render(AppLayout);

		await waitFor(() => {
			expect(mockGoto).toHaveBeenCalledWith('/login?next=%2Fapp%2Fevents%2Fe1%3Ftab%3Dsource');
		});
		window.history.replaceState({}, '', '/');
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

		// Both nav layouts (desktop sidebar + mobile header) render the brand.
		await waitFor(() => {
			expect(screen.getAllByText('Selko').length).toBeGreaterThan(0);
		});
	});

	it('renders navigation links when authenticated', async () => {
		mockLoading.set(false);
		mockUser.set({ id: '123', email: 'test@example.com' });

		render(AppLayout);

		await waitFor(() => {
			expect(screen.getAllByText('Review').length).toBeGreaterThan(0);
			expect(screen.getAllByText('History').length).toBeGreaterThan(0);
			expect(screen.getAllByText('Settings').length).toBeGreaterThan(0);
		});
		await waitFor(() => expect(mockLive.start).toHaveBeenCalledWith('123'));
	});

	it('shows "Can\'t reach Selko" with a retry instead of the login page', async () => {
		const userEvents = (await import('@testing-library/user-event')).default.setup();
		mockLoading.set(false);
		mockUnavailable.set(true);
		mockUser.set(null);

		render(AppLayout);

		await waitFor(() => {
			expect(screen.getByText("Can't reach Selko")).toBeInTheDocument();
		});
		expect(mockGoto).not.toHaveBeenCalled();
		await userEvents.click(screen.getByRole('button', { name: /retry/i }));
		expect(mockRetryAuth).toHaveBeenCalledTimes(1);
	});

	it('logs out through the auth module and stops live updates', async () => {
		const userEvents = (await import('@testing-library/user-event')).default.setup();
		mockLoading.set(false);
		mockUser.set({ id: '123', email: 'test@example.com' });

		render(AppLayout);

		const button = await screen.findByRole('button', { name: /log out/i });
		await userEvents.click(button);

		await waitFor(() => expect(mockSignOut).toHaveBeenCalledTimes(1));
		expect(mockLive.stop).toHaveBeenCalled();
		expect(mockGoto).toHaveBeenCalledWith('/login');
	});

	it('renders logout in the desktop sidebar and a sticky mobile header', async () => {
		mockLoading.set(false);
		mockUser.set({ id: '123', email: 'test@example.com' });

		render(AppLayout);

		await waitFor(() => {
			expect(screen.getByRole('button', { name: /log out/i })).toBeInTheDocument();
		});
		expect(document.querySelector('header.sticky')).toBeTruthy();
	});
});
