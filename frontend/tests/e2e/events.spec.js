import { test, expect } from '@playwright/test';

test.describe('Events Review', () => {
	// Login before each test
	test.beforeEach(async ({ page }) => {
		// Navigate to login
		await page.goto('/login');

		// Login with test credentials
		await page.getByLabel(/email/i).fill('test@selko.local');
		await page.getByLabel(/password/i).fill('testpass123');
		await page.getByRole('button', { name: /login/i }).click();

		// Wait for redirect to app
		await expect(page).toHaveURL(/.*\/app/, { timeout: 10000 });
	});

	test('app page is accessible after login', async ({ page }) => {
		// Verify we're on the app page and user is displayed
		await expect(page.getByText(/hello.*test@selko.local/i)).toBeVisible();
		await expect(page.getByText('Welcome to Selko')).toBeVisible();
	});

	test('Selko branding is visible', async ({ page }) => {
		// Check for brand name in navbar
		await expect(page.getByText('Selko').first()).toBeVisible();
	});

	// Note: The following tests are placeholders for when the events UI is implemented
	// Currently the app page just shows a welcome message

	test.describe('pending events (future implementation)', () => {
		test.skip('displays pending events when available', async ({ page }) => {
			// This test will be implemented when the events review UI is built
			// It should:
			// 1. Navigate to events section
			// 2. Display list of pending events
			// 3. Show event details (title, date, location)
		});

		test.skip('can approve a pending event', async ({ page }) => {
			// This test will be implemented when the events review UI is built
			// It should:
			// 1. Find a pending event
			// 2. Click approve button
			// 3. Verify event status changes to approved
		});

		test.skip('can reject a pending event', async ({ page }) => {
			// This test will be implemented when the events review UI is built
			// It should:
			// 1. Find a pending event
			// 2. Click reject button
			// 3. Verify event is removed from pending list
		});

		test.skip('can edit event before approving', async ({ page }) => {
			// This test will be implemented when the events review UI is built
			// It should:
			// 1. Find a pending event
			// 2. Click edit button
			// 3. Modify event details
			// 4. Save changes
			// 5. Verify changes are reflected
		});
	});
});
