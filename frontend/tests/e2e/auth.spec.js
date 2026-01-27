import { test, expect } from '@playwright/test';

test.describe('Authentication Flow', () => {
	test.beforeEach(async ({ page }) => {
		// Clear any existing session storage/local storage
		await page.goto('/');
		await page.evaluate(() => {
			localStorage.clear();
			sessionStorage.clear();
		});
	});

	test('unauthenticated users are redirected to login', async ({ page }) => {
		// Try to access the app page directly
		await page.goto('/app');

		// Should be redirected to login
		await expect(page).toHaveURL(/.*\/login/);
	});

	test('login page renders correctly', async ({ page }) => {
		await page.goto('/login');

		// Check for essential elements
		await expect(page.getByRole('heading', { name: /login to selko/i })).toBeVisible();
		await expect(page.getByLabel(/email/i)).toBeVisible();
		await expect(page.getByLabel(/password/i)).toBeVisible();
		await expect(page.getByRole('button', { name: /login/i })).toBeVisible();
		await expect(page.getByRole('link', { name: /register/i })).toBeVisible();
	});

	test('shows error for invalid credentials', async ({ page }) => {
		await page.goto('/login');

		// Fill in invalid credentials
		await page.getByLabel(/email/i).fill('invalid@example.com');
		await page.getByLabel(/password/i).fill('wrongpassword');
		await page.getByRole('button', { name: /login/i }).click();

		// Should show an error message
		await expect(page.getByRole('alert')).toBeVisible({ timeout: 10000 });
	});

	test('successful login redirects to app', async ({ page }) => {
		// This test requires a test user to exist in the database
		// The test user should be created before running E2E tests:
		// uv run python -m cli.cli_user create --email test@selko.local --password testpass123 --auto-confirm

		await page.goto('/login');

		// Fill in valid test credentials
		await page.getByLabel(/email/i).fill('test@selko.local');
		await page.getByLabel(/password/i).fill('testpass123');
		await page.getByRole('button', { name: /login/i }).click();

		// Should redirect to the app page
		await expect(page).toHaveURL(/.*\/app/, { timeout: 10000 });

		// Should display user greeting
		await expect(page.getByText(/hello.*test@selko.local/i)).toBeVisible({ timeout: 5000 });
	});

	test('logout returns to login page', async ({ page }) => {
		// First, login
		await page.goto('/login');
		await page.getByLabel(/email/i).fill('test@selko.local');
		await page.getByLabel(/password/i).fill('testpass123');
		await page.getByRole('button', { name: /login/i }).click();

		// Wait for app page
		await expect(page).toHaveURL(/.*\/app/, { timeout: 10000 });

		// Click logout
		await page.getByRole('button', { name: /logout/i }).click();

		// Should redirect to login
		await expect(page).toHaveURL(/.*\/login/, { timeout: 5000 });
	});

	test('register link navigates to registration page', async ({ page }) => {
		await page.goto('/login');

		await page.getByRole('link', { name: /register/i }).click();

		await expect(page).toHaveURL(/.*\/register/);
	});
});
