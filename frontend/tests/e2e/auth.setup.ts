import { test as setup, expect } from '@playwright/test';

const authFile = 'tests/e2e/.auth/user.json';

setup('authenticate', async ({ page }) => {
  await page.goto('/login');
  await page.getByLabel('Email').waitFor({ state: 'visible', timeout: 15000 });
  await page.waitForTimeout(500);

  await page.getByLabel('Email').fill('test@selko.local');
  await page.getByLabel('Password').fill('testpass123');
  await page.getByRole('button', { name: 'Sign in' }).click();

  // Wait for redirect to /app
  await page.waitForURL('/app');

  // Save auth state
  await page.context().storageState({ path: authFile });
});
