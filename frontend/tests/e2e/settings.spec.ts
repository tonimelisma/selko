import { test, expect } from './fixtures/auth';

test.describe('Settings', () => {
  test('loads settings page', async ({ page }) => {
    await page.goto('/app/settings');
    await expect(page.getByText('Settings')).toBeVisible();
  });

  test('shows connected accounts section', async ({ page }) => {
    await page.goto('/app/settings');
    await expect(page.getByText('Connected Accounts').or(page.getByText('Gmail').or(page.getByText('Google')))).toBeVisible();
  });

  test('shows account section', async ({ page }) => {
    await page.goto('/app/settings');
    await expect(page.getByText('Account')).toBeVisible();
  });
});
