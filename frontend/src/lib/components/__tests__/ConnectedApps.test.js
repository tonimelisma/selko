// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';

const mockListGrants = vi.fn();
const mockRevokeGrant = vi.fn();
vi.mock('$lib/supabase.js', () => ({
	supabase: {
		auth: {
			oauth: {
				listGrants: (...a) => mockListGrants(...a),
				revokeGrant: (...a) => mockRevokeGrant(...a)
			}
		}
	}
}));

const { default: ConnectedApps } = await import('../ConnectedApps.svelte');

const claude = { client: { id: 'c1', name: 'Claude' }, scopes: ['openid'], granted_at: '2026-11-01T10:00:00Z' };

describe('ConnectedApps', () => {
	beforeEach(() => vi.clearAllMocks());

	it('is hidden when no app is connected', async () => {
		mockListGrants.mockResolvedValue({ data: [], error: null });
		render(ConnectedApps);
		await waitFor(() => expect(mockListGrants).toHaveBeenCalled());
		expect(screen.queryByTestId('connected-apps')).not.toBeInTheDocument();
	});

	it('is hidden when the OAuth server is unavailable', async () => {
		mockListGrants.mockResolvedValue({ data: null, error: { message: 'disabled' } });
		render(ConnectedApps);
		await waitFor(() => expect(mockListGrants).toHaveBeenCalled());
		expect(screen.queryByTestId('connected-apps')).not.toBeInTheDocument();
	});

	it('lists a connected app and disconnects it', async () => {
		mockListGrants.mockResolvedValue({ data: [claude], error: null });
		mockRevokeGrant.mockResolvedValue({ data: {}, error: null });
		render(ConnectedApps);
		expect(await screen.findByText('Claude')).toBeInTheDocument();
		await userEvent.click(screen.getByRole('button', { name: 'Disconnect Claude' }));
		expect(mockRevokeGrant).toHaveBeenCalledWith({ clientId: 'c1' });
		await waitFor(() => expect(screen.queryByText('Claude')).not.toBeInTheDocument());
	});

	it('keeps the app listed and says so when disconnecting fails', async () => {
		mockListGrants.mockResolvedValue({ data: [claude], error: null });
		mockRevokeGrant.mockResolvedValue({ data: null, error: { message: 'boom' } });
		render(ConnectedApps);
		await userEvent.click(await screen.findByRole('button', { name: 'Disconnect Claude' }));
		expect(await screen.findByText(/could not disconnect/)).toBeInTheDocument();
		expect(screen.getByText('Claude')).toBeInTheDocument();
	});
});
