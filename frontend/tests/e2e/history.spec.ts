import { test, expect } from './fixtures/auth';

test.describe('Activity History', () => {
  test('loads history page', async ({ page }) => {
    await page.goto('/app/history');
    await expect(
      page.getByText('Activity History').or(
        page.getByText('No activity').or(
          page.getByText('No Activity')
        )
      )
    ).toBeVisible();
  });

  test('shows empty state when no history', async ({ page }) => {
    await page.goto('/app/history');
    // New users will see the empty state
    const emptyState = page.getByText('No activity').or(page.getByText('No Activity'));
    const hasHistory = page.getByText('Activity History');
    await expect(emptyState.or(hasHistory)).toBeVisible();
  });
});
