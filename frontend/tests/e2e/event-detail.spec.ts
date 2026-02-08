import { test, expect } from './fixtures/auth';

test.describe('Event Detail', () => {
  test('shows error for non-existent event', async ({ page }) => {
    await page.goto('/app/events/00000000-0000-0000-0000-000000000000');
    // Should show some error or redirect
    await expect(
      page.getByText('not found').or(
        page.getByText('Error').or(
          page.getByText('Review') // redirected back
        )
      )
    ).toBeVisible();
  });
});
