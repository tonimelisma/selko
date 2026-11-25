import { test, expect } from '@playwright/test';
import type { Browser, BrowserContext, Page } from '@playwright/test';

/**
 * Wait for the page to load and its data to render. Not 'networkidle': the
 * app holds the /live update stream open, so the network never goes idle.
 */
async function settle(page: import('@playwright/test').Page) {
  await page.waitForLoadState('load');
  await page.locator('main, form').first().waitFor({ state: 'visible', timeout: 15000 });
  await page.waitForTimeout(750);
}


/** Relative path from frontend/ to docs/screenshots/ at project root. */
const SCREENSHOT_DIR = '../docs/screenshots';
const SCREENSHOT_USER = 'screenshots@selko.local';
const SCREENSHOT_PASS = 'screenshotpass123';

const VIEWPORTS = [
  { name: 'desktop', width: 1280, height: 800 },
  { name: 'mobile', width: 390, height: 844 },
] as const;
const APPEARANCES = ['light', 'dark'] as const;

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
  // Every module and the locale JSON have loaded, so hydration has run. A
  // fixed 1 s delay used to stand in for this and lost the race on a slow CPU
  // (a throttled cloud-session container): the click then submitted the bare
  // HTML form as a GET to /login? and the test timed out waiting for /app.
  await settle(page);
}

/**
 * Create a new browser context at the given viewport, log in as the
 * screenshot user, and return the context + page (already at /app).
 */
async function createAuthContext(
  browser: Browser,
  viewport: { width: number; height: number },
  colorScheme: 'light' | 'dark'
): Promise<{ context: BrowserContext; page: Page }> {
  const context = await browser.newContext({ viewport, colorScheme, storageState: undefined });
  const page = await context.newPage();

  await page.goto('/login');
  for (let attempt = 1; ; attempt++) {
    await waitForLoginForm(page);
    await page.getByLabel('Email').fill(SCREENSHOT_USER);
    await page.getByLabel('Password').fill(SCREENSHOT_PASS);
    await page.getByRole('button', { name: 'Sign in' }).click();
    // Either the app signs in and routes to /app, or the click beat hydration
    // and the browser submitted the plain form (URL becomes /login?...).
    // (URL.search is "" for a bare "?", so match the href.)
    await page.waitForURL((url) => url.pathname === '/app' || url.href.includes('/login?'), {
      timeout: 15000,
    });
    if (new URL(page.url()).pathname === '/app') break;
    if (attempt === 3) throw new Error(`login never hydrated: still at ${page.url()}`);
  }

  return { context, page };
}

test.describe('Screenshot capture', () => {
  // i18n lazy-loading + SvelteKit hydration can be slow under parallel workers
  test.setTimeout(60000);

  for (const vp of VIEWPORTS) {
    for (const appearance of APPEARANCES) {
    test.describe(`${vp.name} ${appearance} (${vp.width}x${vp.height})`, () => {

      test('login page', async ({ browser }) => {
        const context = await browser.newContext({
          viewport: { width: vp.width, height: vp.height },
          colorScheme: appearance,
          storageState: undefined,
        });
        const page = await context.newPage();
        await page.goto('/login');
        await waitForLoginForm(page);
        await page.screenshot({
          path: `${SCREENSHOT_DIR}/web-login-${vp.name}-${appearance}.png`,
          fullPage: false,
        });
        await context.close();
      });

      test('register page', async ({ browser }) => {
        const context = await browser.newContext({
          viewport: { width: vp.width, height: vp.height },
          colorScheme: appearance,
          storageState: undefined,
        });
        const page = await context.newPage();
        await page.goto('/register');
        await page.getByLabel('Email').waitFor({ state: 'visible', timeout: 30000 });
        await page.waitForTimeout(500);
        await page.screenshot({
          path: `${SCREENSHOT_DIR}/web-register-${vp.name}-${appearance}.png`,
          fullPage: false,
        });
        await context.close();
      });

      test('review queue', async ({ browser }) => {
        const { context, page } = await createAuthContext(browser, {
          width: vp.width,
          height: vp.height,
        }, appearance);
        // Already at /app after login
        await settle(page);
        // Allow time for data to render after network settles
        await page.waitForTimeout(1000);
        await page.screenshot({
          path: `${SCREENSHOT_DIR}/web-review-queue-${vp.name}-${appearance}.png`,
          fullPage: false,
        });
        await context.close();
      });

      test('event detail', async ({ browser }) => {
        const { context, page } = await createAuthContext(browser, {
          width: vp.width,
          height: vp.height,
        }, appearance);
        await settle(page);
        await page.waitForTimeout(1000);

        // Click the first event card link to navigate to event detail
        const firstEventLink = page.locator('a[href*="/app/events/"]').first();
        await firstEventLink.click();
        await settle(page);
        // Wait for form content to be visible (indicates data loaded)
        await page.waitForSelector('#event-title', { timeout: 10000 });
        await page.waitForTimeout(500);
        await page.screenshot({
          path: `${SCREENSHOT_DIR}/web-event-detail-${vp.name}-${appearance}.png`,
          fullPage: false,
        });
        await context.close();
      });

      test('history', async ({ browser }) => {
        const { context, page } = await createAuthContext(browser, {
          width: vp.width,
          height: vp.height,
        }, appearance);
        await page.goto('/app/history');
        await settle(page);
        await page.waitForTimeout(1000);
        await page.screenshot({
          path: `${SCREENSHOT_DIR}/web-history-${vp.name}-${appearance}.png`,
          fullPage: false,
        });
        await context.close();
      });

      test('settings', async ({ browser }) => {
        const { context, page } = await createAuthContext(browser, {
          width: vp.width,
          height: vp.height,
        }, appearance);
        await page.goto('/app/settings');
        await settle(page);
        await page.waitForTimeout(1000);
        await page.screenshot({
          path: `${SCREENSHOT_DIR}/web-settings-${vp.name}-${appearance}.png`,
          fullPage: false,
        });
        await context.close();
      });

    });
    }
  }
});
