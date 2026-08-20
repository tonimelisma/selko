// @ts-nocheck
import { describe, expect, it, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';
import ChangeCard from '../ChangeCard.svelte';

const baseEvent = {
	id: 'evt-change',
	title: 'Changed event',
	start_datetime: '2027-01-20T14:00:00Z',
	review_status: 'active'
};

describe('ChangeCard', () => {
	it('shows field-level proposal details when an active proposal exists', () => {
		render(ChangeCard, {
			props: {
				proposal: {
					id: 'proposal-1',
					kind: 'material_update',
					status: 'pending',
					change_set: {
						changes: [{ field: 'location', before: 'Old place', after: 'New place' }]
					}
				},
				event: {
					...baseEvent,
				}
			}
		});

		expect(screen.getByText('Old place')).toHaveClass('line-through');
		expect(screen.getByText('New place')).toBeInTheDocument();
		expect(screen.queryByRole('alert')).not.toBeInTheDocument();
	});

	it('fails closed when an active event has no proposal', async () => {
		const user = userEvent.setup();
		const onapprove = vi.fn();
		const onreject = vi.fn();
		render(ChangeCard, {
			props: {
				event: {
					...baseEvent,
					 event_change_proposals: []
				},
				onapprove,
				onreject
			}
		});

		expect(screen.getByRole('alert')).toHaveTextContent('Change details are unavailable');
		const accept = screen.getByRole('button', { name: /accept changed event/i });
		const reject = screen.getByRole('button', { name: /reject changed event/i });
		expect(accept).toBeDisabled();
		expect(reject).toBeDisabled();
		await user.click(accept);
		await user.click(reject);
		expect(onapprove).not.toHaveBeenCalled();
		expect(onreject).not.toHaveBeenCalled();
	});
});
