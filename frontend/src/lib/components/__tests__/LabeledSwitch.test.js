// @ts-nocheck
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import LabeledSwitch from '../LabeledSwitch.svelte';

describe('LabeledSwitch', () => {
	it('communicates state with text, position, check, and switch semantics', async () => {
		const user = userEvent.setup();
		const onchange = vi.fn();
		render(LabeledSwitch, { props: { checked: true, onchange } });

		expect(screen.getByText('Included')).toBeInTheDocument();
		const control = screen.getByRole('switch', { name: 'Exclude' });
		expect(control).toHaveAttribute('aria-checked', 'true');
		expect(screen.getByText('✓')).toBeInTheDocument();
		await user.tab();
		expect(control).toHaveFocus();
		await user.keyboard('{Enter}');
		expect(onchange).toHaveBeenCalledWith(false);
	});

	it('does not activate while disabled', async () => {
		const user = userEvent.setup();
		const onchange = vi.fn();
		render(LabeledSwitch, { props: { disabled: true, onchange } });
		await user.click(screen.getByRole('switch'));
		expect(onchange).not.toHaveBeenCalled();
	});
});
