import { test as setup, expect } from '@playwright/test';

const authFile = 'tests/e2e/.auth/user.json';

setup('authenticate', async ({ page }) => {
  await page.goto('/login');

  await page.getByLabel('Email').fill('test@selko.local');
  await page.getByLabel('Password').fill('testpass123');
  await page.getByRole('button', { name: 'Login' }).click();

  // Wait for redirect to /app
  await page.waitForURL('/app');

  // Save auth state
  await page.context().storageState({ path: authFile });
});
