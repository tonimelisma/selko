// @ts-nocheck
import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen } from '@testing-library/svelte';
import userEvent from '@testing-library/user-event';

const mockSignUp = vi.fn();
vi.mock('$lib/auth.js', () => ({
	signUp: (...args) => mockSignUp(...args)
}));

const { default: RegisterPage } = await import('../+page.svelte');

/** @param {ReturnType<typeof userEvent.setup>} user */
async function fill(user, email, password, confirm = password) {
	await user.type(screen.getByLabelText('Email'), email);
	await user.type(screen.getByLabelText('Password'), password);
	await user.type(screen.getByLabelText('Confirm password'), confirm);
	await user.click(screen.getByRole('button', { name: /sign up/i }));
}

describe('Register Page', () => {
	beforeEach(() => {
		vi.clearAllMocks();
	});

	it('renders the sign-up form with a link to sign in', () => {
		render(RegisterPage);

		expect(screen.getByLabelText('Email')).toBeInTheDocument();
		expect(screen.getByLabelText('Password')).toBeInTheDocument();
		expect(screen.getByLabelText('Confirm password')).toBeInTheDocument();
		expect(screen.getByRole('link', { name: /log in/i })).toHaveAttribute('href', '/login');
	});

	// Validates: SEL-518
	it('creates the account and sends the user to sign in', async () => {
		const user = userEvent.setup();
		mockSignUp.mockResolvedValue({
			data: { user: { id: 'u1', email: 'new@example.com' }, confirmation_required: false },
			error: null
		});

		render(RegisterPage);
		await fill(user, 'new@example.com', 'secret12');

		expect(mockSignUp).toHaveBeenCalledWith('new@example.com', 'secret12');
		expect(await screen.findByText('Your account is ready. Sign in to continue.')).toBeInTheDocument();
		expect(screen.getByRole('link', { name: /sign in/i })).toHaveAttribute('href', '/login');
	});

	// Validates: SEL-518
	it('asks the user to check their email when confirmation is required', async () => {
		const user = userEvent.setup();
		mockSignUp.mockResolvedValue({ data: { user: { id: 'u1' }, confirmation_required: true }, error: null });

		render(RegisterPage);
		await fill(user, 'new@example.com', 'secret12');

		expect(await screen.findByText('Check your email to confirm your account.')).toBeInTheDocument();
	});

	it('shows the server’s error, e.g. an existing account', async () => {
		const user = userEvent.setup();
		mockSignUp.mockResolvedValue({
			data: null,
			error: { message: 'User already registered', status: 409, code: 'USER_ALREADY_EXISTS' }
		});

		render(RegisterPage);
		await fill(user, 'taken@example.com', 'secret12');

		expect(await screen.findByText('User already registered')).toBeInTheDocument();
	});

	// Validates: SEL-518
	it('checks that the passwords match before calling the server', async () => {
		const user = userEvent.setup();
		render(RegisterPage);
		await fill(user, 'new@example.com', 'secret12', 'different');

		expect(mockSignUp).not.toHaveBeenCalled();
		expect(screen.getByText('Passwords do not match')).toBeInTheDocument();
	});

	// Validates: SEL-518
	it('checks the minimum length before calling the server', async () => {
		const user = userEvent.setup();
		render(RegisterPage);
		await fill(user, 'new@example.com', 'abc');

		expect(mockSignUp).not.toHaveBeenCalled();
		expect(screen.getByText('Password must be at least 6 characters')).toBeInTheDocument();
	});
});
