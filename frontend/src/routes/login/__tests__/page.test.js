// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';

// Mock SvelteKit navigation
const mockGoto = vi.fn();
vi.mock('$app/navigation', () => ({
	goto: (...args) => mockGoto(...args)
}));

// Mock the auth module: signIn(email, password) → {user, error}
const mockSignInWithPassword = vi.fn();
vi.mock('$lib/auth.js', () => ({
	signIn: (email, password) => mockSignInWithPassword({ email, password })
}));

// Import after mocking
const { default: LoginPage } = await import('../+page.svelte');

describe('Login Page', () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it('renders the login form', () => {
		render(LoginPage);

		expect(screen.getByRole('heading', { name: /selko/i })).toBeInTheDocument();
		expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
		expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
		expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument();
	});

	// Validates: SEL-519
	it('has a link to the registration page', () => {
		render(LoginPage);

		const registerLink = screen.getByRole('link', { name: /sign up/i });
		expect(registerLink).toBeInTheDocument();
		expect(registerLink).toHaveAttribute('href', '/register');
	});

	// Validates: SEL-519
	it('links to the privacy policy', () => {
		render(LoginPage);

		const privacyLink = screen.getByRole('link', { name: /privacy policy/i });
		expect(privacyLink).toHaveAttribute('href', '/privacy');
	});

	it('submits credentials to the auth module on form submission', async () => {
		const user = userEvent.setup();
		mockSignInWithPassword.mockResolvedValue({
			data: { user: { id: '123', email: 'test@example.com' } },
			error: null
		});

		render(LoginPage);

		await user.type(screen.getByLabelText(/email/i), 'test@example.com');
		await user.type(screen.getByLabelText(/password/i), 'password123');
		await user.click(screen.getByRole('button', { name: /sign in/i }));

		expect(mockSignInWithPassword).toHaveBeenCalledWith({
			email: 'test@example.com',
			password: 'password123'
		});
	});

	it('redirects to /app on successful login', async () => {
		const user = userEvent.setup();
		mockSignInWithPassword.mockResolvedValue({
			data: { user: { id: '123', email: 'test@example.com' } },
			error: null
		});

		render(LoginPage);

		await user.type(screen.getByLabelText(/email/i), 'test@example.com');
		await user.type(screen.getByLabelText(/password/i), 'password123');
		await user.click(screen.getByRole('button', { name: /sign in/i }));

		expect(mockGoto).toHaveBeenCalledWith('/app');
	});

	// Validates: SEL-517
	it('returns to the page that sent the user to sign in', async () => {
		const user = userEvent.setup();
		window.history.replaceState({}, '', '/login?next=' + encodeURIComponent('/app/events/e1?tab=source'));
		mockSignInWithPassword.mockResolvedValue({ data: { user: { id: '123' } }, error: null });

		render(LoginPage);
		await user.type(screen.getByLabelText(/email/i), 'test@example.com');
		await user.type(screen.getByLabelText(/password/i), 'password123');
		await user.click(screen.getByRole('button', { name: /sign in/i }));

		expect(mockGoto).toHaveBeenCalledWith('/app/events/e1?tab=source');
		window.history.replaceState({}, '', '/');
	});

	// Validates: SEL-517
	it('ignores a next parameter that points off-site', async () => {
		const user = userEvent.setup();
		window.history.replaceState({}, '', '/login?next=' + encodeURIComponent('https://evil.example'));
		mockSignInWithPassword.mockResolvedValue({ data: { user: { id: '123' } }, error: null });

		render(LoginPage);
		await user.type(screen.getByLabelText(/email/i), 'test@example.com');
		await user.type(screen.getByLabelText(/password/i), 'password123');
		await user.click(screen.getByRole('button', { name: /sign in/i }));

		expect(mockGoto).toHaveBeenCalledWith('/app');
		window.history.replaceState({}, '', '/');
	});

	// Validates: SEL-515
	it('displays error message on login failure', async () => {
		const user = userEvent.setup();
		mockSignInWithPassword.mockResolvedValue({
			data: null,
			error: { message: 'Invalid login credentials' }
		});

		render(LoginPage);

		await user.type(screen.getByLabelText(/email/i), 'test@example.com');
		await user.type(screen.getByLabelText(/password/i), 'wrongpassword');
		await user.click(screen.getByRole('button', { name: /sign in/i }));

		expect(await screen.findByText('Invalid login credentials')).toBeInTheDocument();
	});

	// Validates: SEL-515
	it('does not redirect on login failure', async () => {
		const user = userEvent.setup();
		mockSignInWithPassword.mockResolvedValue({
			data: null,
			error: { message: 'Invalid login credentials' }
		});

		render(LoginPage);

		await user.type(screen.getByLabelText(/email/i), 'test@example.com');
		await user.type(screen.getByLabelText(/password/i), 'wrongpassword');
		await user.click(screen.getByRole('button', { name: /sign in/i }));

		// Wait for error to appear to ensure async operation completed
		await screen.findByText('Invalid login credentials');

		expect(mockGoto).not.toHaveBeenCalled();
	});

	it('disables submit button while loading', async () => {
		const user = userEvent.setup();
		// Create a promise we can control
		let resolveLogin;
		mockSignInWithPassword.mockReturnValue(
			new Promise((resolve) => {
				resolveLogin = resolve;
			})
		);

		render(LoginPage);

		await user.type(screen.getByLabelText(/email/i), 'test@example.com');
		await user.type(screen.getByLabelText(/password/i), 'password123');

		const submitButton = screen.getByRole('button', { name: /sign in/i });
		await user.click(submitButton);

		// Button should be disabled while loading
		expect(submitButton).toBeDisabled();

		// Resolve the login
		resolveLogin({ data: { user: { id: '123' } }, error: null });
	});

	it('requires email field', () => {
		render(LoginPage);

		const emailInput = screen.getByLabelText(/email/i);
		expect(emailInput).toHaveAttribute('required');
	});

	it('requires password field', () => {
		render(LoginPage);

		const passwordInput = screen.getByLabelText(/password/i);
		expect(passwordInput).toHaveAttribute('required');
	});
});
