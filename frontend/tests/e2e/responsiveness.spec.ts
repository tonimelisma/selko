import { test, expect } from '@playwright/test';

/**
 * Wait for the page to load and its data to render. Not 'networkidle': the
 * app holds the /live update stream open, so the network never goes idle.
 */
async function settle(page: import('@playwright/test').Page) {
  await page.waitForLoadState('load');
  await page.locator('main, form').first().waitFor({ state: 'visible', timeout: 15000 });
  await page.waitForTimeout(750);
}


const viewportWidths = [375, 768, 800, 900, 1000, 1024, 1040, 1100, 1280, 1440];

test.describe('Responsive layout - no horizontal overflow', () => {
  for (const width of viewportWidths) {
    test(`login page has no horizontal overflow at ${width}px`, async ({ browser }) => {
      const context = await browser.newContext();
      const page = await context.newPage();
      await page.setViewportSize({ width, height: 800 });
      await page.goto('/login');
      await settle(page);

      const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
      const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
      expect(scrollWidth, `Page content (${scrollWidth}px) overflows viewport (${clientWidth}px) at ${width}px`).toBeLessThanOrEqual(clientWidth);

      await context.close();
    });
  }
});

test.describe('Responsive layout - app pages', () => {
  for (const width of viewportWidths) {
    test(`app page has no horizontal overflow at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 });
      await page.goto('/app');
      await settle(page);

      const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
      const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
      expect(scrollWidth, `Page content (${scrollWidth}px) overflows viewport (${clientWidth}px) at ${width}px`).toBeLessThanOrEqual(clientWidth);
    });
  }

  for (const width of viewportWidths) {
    test(`history page has no horizontal overflow at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 });
      await page.goto('/app/history');
      await settle(page);

      const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
      const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
      expect(scrollWidth, `Page content (${scrollWidth}px) overflows viewport (${clientWidth}px) at ${width}px`).toBeLessThanOrEqual(clientWidth);
    });
  }

  for (const width of viewportWidths) {
    test(`settings page has no horizontal overflow at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 });
      await page.goto('/app/settings');
      await settle(page);

      const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
      const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
      expect(scrollWidth, `Page content (${scrollWidth}px) overflows viewport (${clientWidth}px) at ${width}px`).toBeLessThanOrEqual(clientWidth);
    });
  }
});
