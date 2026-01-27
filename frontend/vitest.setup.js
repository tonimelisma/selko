import '@testing-library/jest-dom/vitest';
import { vi } from 'vitest';

// Mock SvelteKit modules
export const goto = vi.fn();
export const invalidate = vi.fn();
export const invalidateAll = vi.fn();
export const preloadData = vi.fn();
export const preloadCode = vi.fn();
export const beforeNavigate = vi.fn();
export const afterNavigate = vi.fn();
export const onNavigate = vi.fn();
export const disableScrollHandling = vi.fn();

// Mock $app/stores
import { readable, writable } from 'svelte/store';

export const page = readable({
	url: new URL('http://localhost'),
	params: {},
	route: { id: '' },
	status: 200,
	error: null,
	data: {},
	form: null
});

export const navigating = readable(null);
export const updated = {
	subscribe: readable(false).subscribe,
	check: vi.fn()
};

// Reset all mocks before each test
beforeEach(() => {
	vi.clearAllMocks();
});
