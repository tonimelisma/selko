import { test, expect } from '@playwright/test';
import type { Browser, BrowserContext, Page } from '@playwright/test';

/** Relative path from frontend/ to docs/screenshots/ at project root. */
const SCREENSHOT_DIR = '../docs/screenshots';
const SCREENSHOT_USER = 'screenshots@selko.local';
const SCREENSHOT_PASS = 'screenshotpass123';

const VIEWPORTS = [
  { name: 'desktop', width: 1280, height: 800 },
  { name: 'mobile', width: 390, height: 844 },
] as const;

/**
 * Wait for the login form to be fully rendered and hydrated.
 *
 * The root layout hides all children while svelte-i18n loads its locale JSON.
 * Under parallel workers the async import can take 10+ seconds. After the form
 * appears we add a stability delay so SvelteKit hydration completes and JS
 * event handlers (like the form's onsubmit) are attached.
 */
async function waitForLoginForm(page: Page): Promise<void> {
  await page.getByLabel('Email').waitFor({ state: 'visible', timeout: 30000 });
  await page.waitForTimeout(1000);
}

/**
 * Create a new browser context at the given viewport, log in as the
 * screenshot user, and return the context + page (already at /app).
 */
async function createAuthContext(
  browser: Browser,
  viewport: { width: number; height: number }
): Promise<{ context: BrowserContext; page: Page }> {
  const context = await browser.newContext({ viewport, storageState: undefined });
  const page = await context.newPage();

  await page.goto('/login');
  await waitForLoginForm(page);
  await page.getByLabel('Email').fill(SCREENSHOT_USER);
  await page.getByLabel('Password').fill(SCREENSHOT_PASS);
  await page.getByRole('button', { name: 'Sign in' }).click();
  await page.waitForURL('/app', { timeout: 15000 });

  return { context, page };
}

test.describe('Screenshot capture', () => {
  // i18n lazy-loading + SvelteKit hydration can be slow under parallel workers
  test.setTimeout(60000);

  for (const vp of VIEWPORTS) {
    test.describe(`${vp.name} (${vp.width}x${vp.height})`, () => {

      test('login page', async ({ browser }) => {
        const context = await browser.newContext({
          viewport: { width: vp.width, height: vp.height },
          storageState: undefined,
        });
        const page = await context.newPage();
        await page.goto('/login');
        await waitForLoginForm(page);
        await page.screenshot({
          path: `${SCREENSHOT_DIR}/web-login-${vp.name}.png`,
          fullPage: false,
        });
        await context.close();
      });

      test('register page', async ({ browser }) => {
        const context = await browser.newContext({
          viewport: { width: vp.width, height: vp.height },
          storageState: undefined,
        });
        const page = await context.newPage();
        await page.goto('/register');
        await page.getByLabel('Email').waitFor({ state: 'visible', timeout: 30000 });
        await page.waitForTimeout(500);
        await page.screenshot({
          path: `${SCREENSHOT_DIR}/web-register-${vp.name}.png`,
          fullPage: false,
        });
        await context.close();
      });

      test('review queue', async ({ browser }) => {
        const { context, page } = await createAuthContext(browser, {
          width: vp.width,
          height: vp.height,
        });
        // Already at /app after login
        await page.waitForLoadState('networkidle');
        // Allow time for data to render after network settles
        await page.waitForTimeout(1000);
        await page.screenshot({
          path: `${SCREENSHOT_DIR}/web-review-queue-${vp.name}.png`,
          fullPage: false,
        });
        await context.close();
      });

      test('event detail', async ({ browser }) => {
        const { context, page } = await createAuthContext(browser, {
          width: vp.width,
          height: vp.height,
        });
        await page.waitForLoadState('networkidle');
        await page.waitForTimeout(1000);

        // Click the first event card link to navigate to event detail
        const firstEventLink = page.locator('a[href*="/app/events/"]').first();
        await firstEventLink.click();
        await page.waitForLoadState('networkidle');
        // Wait for form content to be visible (indicates data loaded)
        await page.waitForSelector('#event-title', { timeout: 10000 });
        await page.waitForTimeout(500);
        await page.screenshot({
          path: `${SCREENSHOT_DIR}/web-event-detail-${vp.name}.png`,
          fullPage: false,
        });
        await context.close();
      });

      test('history', async ({ browser }) => {
        const { context, page } = await createAuthContext(browser, {
          width: vp.width,
          height: vp.height,
        });
        await page.goto('/app/history');
        await page.waitForLoadState('networkidle');
        await page.waitForTimeout(1000);
        await page.screenshot({
          path: `${SCREENSHOT_DIR}/web-history-${vp.name}.png`,
          fullPage: false,
        });
        await context.close();
      });

      test('settings', async ({ browser }) => {
        const { context, page } = await createAuthContext(browser, {
          width: vp.width,
          height: vp.height,
        });
        await page.goto('/app/settings');
        await page.waitForLoadState('networkidle');
        await page.waitForTimeout(1000);
        await page.screenshot({
          path: `${SCREENSHOT_DIR}/web-settings-${vp.name}.png`,
          fullPage: false,
        });
        await context.close();
      });

    });
  }
});
