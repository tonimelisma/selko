// @ts-nocheck
import { describe, it, expect } from 'vitest';
import { render, screen } from '@testing-library/svelte';

const { default: EmptyState } = await import('../EmptyState.svelte');

describe('EmptyState', () => {
	it('renders heading and description', () => {
		render(EmptyState, {
			props: {
				heading: 'No items',
				description: 'There are no items to display.'
			}
		});

		expect(screen.getByText('No items')).toBeInTheDocument();
		expect(screen.getByText('There are no items to display.')).toBeInTheDocument();
	});

	it('renders heading in h3 element', () => {
		render(EmptyState, {
			props: {
				heading: 'Test Heading',
				description: 'Test description'
			}
		});

		const heading = screen.getByText('Test Heading');
		expect(heading.tagName).toBe('H3');
	});

	it('centers content', () => {
		render(EmptyState, {
			props: {
				heading: 'Centered',
				description: 'Content'
			}
		});

		const container = screen.getByText('Centered').closest('div');
		expect(container.className).toContain('text-center');
		expect(container.className).toContain('items-center');
	});
});
