// @ts-nocheck
import { describe, it, expect, vi } from 'vitest';
import { render, screen } from '@testing-library/svelte';

const { default: ConnectionRecovery } = await import('../ConnectionRecovery.svelte');

describe('ConnectionRecovery', () => {
	it('ignores parked Google Photos integrations', () => {
		render(ConnectionRecovery, {
			props: {
				integrations: [
					{ id: '1', provider: 'gmail', status: 'active' },
					{ id: '2', provider: 'google_calendar', status: 'active' },
					{ id: '3', provider: 'google_photos', status: 'expired' }
				],
				onauthorize: vi.fn()
			}
		});

		expect(screen.queryByText('Connection needs attention')).not.toBeInTheDocument();
		expect(screen.queryByRole('button', { name: /reconnect/i })).not.toBeInTheDocument();
	});
});
