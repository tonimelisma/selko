// @ts-nocheck
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';

const { default: LoadingSpinner } = await import('../LoadingSpinner.svelte');

describe('LoadingSpinner', () => {
	it('renders spinner with default large size', () => {
		render(LoadingSpinner);

		const spinner = document.querySelector('.loading-spinner');
		expect(spinner).toBeTruthy();
		expect(spinner.className).toContain('loading-lg');
	});

	it('renders with custom size', () => {
		render(LoadingSpinner, {
			props: { size: 'sm' }
		});

		const spinner = document.querySelector('.loading-spinner');
		expect(spinner).toBeTruthy();
		expect(spinner.className).toContain('loading-sm');
	});

	it('includes sr-only text for accessibility', () => {
		render(LoadingSpinner);

		expect(screen.getByText('Loading...')).toBeInTheDocument();
		expect(screen.getByText('Loading...')).toHaveClass('sr-only');
	});

	it('hides spinner from assistive technology', () => {
		render(LoadingSpinner);

		const spinner = document.querySelector('.loading-spinner');
		expect(spinner).toHaveAttribute('aria-hidden', 'true');
	});

	it('centers content with flex container', () => {
		render(LoadingSpinner);

		const container = document.querySelector('.loading-spinner')?.closest('div');
		expect(container.className).toContain('flex');
		expect(container.className).toContain('justify-center');
		expect(container.className).toContain('items-center');
	});
});
