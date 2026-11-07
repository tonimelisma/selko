// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';

const mockGoto = vi.fn();
vi.mock('$app/navigation', () => ({ goto: (...args) => mockGoto(...args) }));

const mockGetSession = vi.fn();
const mockGetDetails = vi.fn();
const mockApprove = vi.fn();
const mockDeny = vi.fn();
vi.mock('$lib/supabase.js', () => ({
	supabase: {
		auth: {
			getSession: (...a) => mockGetSession(...a),
			oauth: {
				getAuthorizationDetails: (...a) => mockGetDetails(...a),
				approveAuthorization: (...a) => mockApprove(...a),
				denyAuthorization: (...a) => mockDeny(...a)
			}
		}
	}
}));

const { default: ConsentPage } = await import('../+page.svelte');

const signedIn = { data: { session: { user: { email: 'toni@example.com' } } } };
const details = {
	data: {
		authorization_id: 'auth-1',
		redirect_uri: 'https://claude.ai/api/mcp/auth_callback',
		client: { id: 'c1', name: 'Claude' },
		user: { id: 'u1', email: 'toni@example.com' },
		scope: 'openid email'
	},
	error: null
};

function at(search) {
	window.history.replaceState({}, '', `/oauth/consent${search}`);
}

describe('OAuth consent page', () => {
	beforeEach(() => {
		vi.clearAllMocks();
		at('?authorization_id=auth-1');
	});

	it('sends a signed-out user to sign in and back here', async () => {
		mockGetSession.mockResolvedValue({ data: { session: null } });
		render(ConsentPage);
		await waitFor(() =>
			expect(mockGoto).toHaveBeenCalledWith(
				'/login?next=' + encodeURIComponent('/oauth/consent?authorization_id=auth-1')
			)
		);
		expect(mockGetDetails).not.toHaveBeenCalled();
	});

	it('names the app, the account, and what it may do', async () => {
		mockGetSession.mockResolvedValue(signedIn);
		mockGetDetails.mockResolvedValue(details);
		render(ConsentPage);
		expect(await screen.findByRole('heading', { name: 'Connect Claude to Selko' })).toBeInTheDocument();
		expect(screen.getByTestId('consent-account')).toHaveTextContent('toni@example.com');
		expect(screen.getByText(/Accept or reject events and changes/)).toBeInTheDocument();
		expect(screen.getByText(/cannot read your emails/)).toBeInTheDocument();
		// The name is self-chosen at registration; the return host is not.
		expect(screen.getByTestId('consent-return-host')).toHaveTextContent('claude.ai');
		expect(mockGetDetails).toHaveBeenCalledWith('auth-1');
	});

	it('approves on Allow', async () => {
		mockGetSession.mockResolvedValue(signedIn);
		mockGetDetails.mockResolvedValue(details);
		mockApprove.mockResolvedValue({ data: { redirect_url: 'http://localhost/callback?code=x' }, error: null });
		render(ConsentPage);
		await userEvent.click(await screen.findByRole('button', { name: 'Allow' }));
		expect(mockApprove).toHaveBeenCalledWith('auth-1');
		expect(mockDeny).not.toHaveBeenCalled();
		expect(await screen.findByText(/Returning you to Claude/)).toBeInTheDocument();
	});

	it('denies on Cancel', async () => {
		mockGetSession.mockResolvedValue(signedIn);
		mockGetDetails.mockResolvedValue(details);
		mockDeny.mockResolvedValue({ data: { redirect_url: 'http://localhost/callback?error=access_denied' }, error: null });
		render(ConsentPage);
		await userEvent.click(await screen.findByRole('button', { name: 'Cancel' }));
		expect(mockDeny).toHaveBeenCalledWith('auth-1');
		expect(mockApprove).not.toHaveBeenCalled();
	});

	it('keeps the choice open when recording it fails', async () => {
		mockGetSession.mockResolvedValue(signedIn);
		mockGetDetails.mockResolvedValue(details);
		mockApprove.mockResolvedValue({ data: null, error: { message: 'boom' } });
		render(ConsentPage);
		await userEvent.click(await screen.findByRole('button', { name: 'Allow' }));
		expect(await screen.findByText(/could not record your answer/)).toBeInTheDocument();
		expect(screen.getByRole('button', { name: 'Allow' })).not.toBeDisabled();
	});

	it('explains an expired or reused request', async () => {
		mockGetSession.mockResolvedValue(signedIn);
		mockGetDetails.mockResolvedValue({ data: null, error: { message: 'not found' } });
		render(ConsentPage);
		expect(await screen.findByText(/expired or was already used/)).toBeInTheDocument();
		expect(screen.queryByRole('button', { name: 'Allow' })).not.toBeInTheDocument();
	});

	it('explains a link with no authorization request', async () => {
		at('');
		render(ConsentPage);
		expect(await screen.findByText(/missing its authorization request/)).toBeInTheDocument();
		expect(mockGetSession).not.toHaveBeenCalled();
	});
});
