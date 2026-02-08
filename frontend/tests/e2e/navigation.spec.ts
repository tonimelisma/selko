import { test, expect } from './fixtures/auth';

test.describe('Navigation', () => {
  test('desktop navbar shows Review, History, Settings links', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 800 });
    await page.goto('/app');
    await expect(page.getByRole('link', { name: 'Review' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'History' })).toBeVisible();
    await expect(page.getByRole('link', { name: 'Settings' })).toBeVisible();
  });

  test('mobile shows bottom navigation', async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 812 });
    await page.goto('/app');
    await expect(page.getByText('Review')).toBeVisible();
    await expect(page.getByText('History')).toBeVisible();
    await expect(page.getByText('Settings')).toBeVisible();
  });

  test('unauthenticated user is redirected to login', async ({ browser }) => {
    const context = await browser.newContext();
    const page = await context.newPage();
    await page.goto('/app');
    await page.waitForURL('/login');
    await expect(page).toHaveURL('/login');
    await context.close();
  });

  test('can navigate to History page', async ({ page }) => {
    await page.goto('/app/history');
    await expect(page.getByText('Activity History').or(page.getByText('No Activity'))).toBeVisible();
  });

  test('can navigate to Settings page', async ({ page }) => {
    await page.goto('/app/settings');
    await expect(page.getByText('Settings')).toBeVisible();
  });
});
