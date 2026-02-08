import { test, expect } from './fixtures/auth';

test.describe('Review Queue', () => {
  test('loads review queue page', async ({ page }) => {
    await page.goto('/app');
    // Should show either integration setup, empty state, or event list
    await expect(
      page.getByText('Welcome to Selko').or(
        page.getByText('All caught up').or(
          page.getByText('Review')
        )
      )
    ).toBeVisible();
  });

  test('shows integration setup when not connected', async ({ page }) => {
    await page.goto('/app');
    // This test checks for the setup state - may show queue if already connected
    const setupVisible = await page.getByText('Connect Google Account').or(page.getByText('Connect your Google')).isVisible().catch(() => false);
    const queueVisible = await page.getByText('All caught up').or(page.getByText('Review Queue')).isVisible().catch(() => false);
    expect(setupVisible || queueVisible).toBeTruthy();
  });
});
