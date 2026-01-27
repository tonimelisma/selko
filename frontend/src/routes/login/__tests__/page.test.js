import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';

// Mock SvelteKit navigation
const mockGoto = vi.fn();
vi.mock('$app/navigation', () => ({
	goto: (...args) => mockGoto(...args)
}));

// Mock Supabase
const mockSignInWithPassword = vi.fn();
vi.mock('$lib/supabase.js', () => ({
	supabase: {
		auth: {
			signInWithPassword: (...args) => mockSignInWithPassword(...args)
		}
	}
}));

// Import after mocking
const { default: LoginPage } = await import('../+page.svelte');

describe('Login Page', () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it('renders the login form', () => {
		render(LoginPage);

		expect(screen.getByRole('heading', { name: /login to selko/i })).toBeInTheDocument();
		expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
		expect(screen.getByLabelText(/password/i)).toBeInTheDocument();
		expect(screen.getByRole('button', { name: /login/i })).toBeInTheDocument();
	});

	it('has a link to the registration page', () => {
		render(LoginPage);

		const registerLink = screen.getByRole('link', { name: /register/i });
		expect(registerLink).toBeInTheDocument();
		expect(registerLink).toHaveAttribute('href', '/register');
	});

	it('submits credentials to Supabase on form submission', async () => {
		const user = userEvent.setup();
		mockSignInWithPassword.mockResolvedValue({
			data: { user: { id: '123', email: 'test@example.com' } },
			error: null
		});

		render(LoginPage);

		await user.type(screen.getByLabelText(/email/i), 'test@example.com');
		await user.type(screen.getByLabelText(/password/i), 'password123');
		await user.click(screen.getByRole('button', { name: /login/i }));

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
		await user.click(screen.getByRole('button', { name: /login/i }));

		expect(mockGoto).toHaveBeenCalledWith('/app');
	});

	it('displays error message on login failure', async () => {
		const user = userEvent.setup();
		mockSignInWithPassword.mockResolvedValue({
			data: null,
			error: { message: 'Invalid login credentials' }
		});

		render(LoginPage);

		await user.type(screen.getByLabelText(/email/i), 'test@example.com');
		await user.type(screen.getByLabelText(/password/i), 'wrongpassword');
		await user.click(screen.getByRole('button', { name: /login/i }));

		expect(await screen.findByText('Invalid login credentials')).toBeInTheDocument();
	});

	it('does not redirect on login failure', async () => {
		const user = userEvent.setup();
		mockSignInWithPassword.mockResolvedValue({
			data: null,
			error: { message: 'Invalid login credentials' }
		});

		render(LoginPage);

		await user.type(screen.getByLabelText(/email/i), 'test@example.com');
		await user.type(screen.getByLabelText(/password/i), 'wrongpassword');
		await user.click(screen.getByRole('button', { name: /login/i }));

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

		const submitButton = screen.getByRole('button', { name: /login/i });
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
