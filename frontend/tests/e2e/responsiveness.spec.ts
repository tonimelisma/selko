import { test, expect } from '@playwright/test';

const viewportWidths = [375, 768, 800, 900, 1000, 1024, 1040, 1100, 1280, 1440];

test.describe('Responsive layout - no horizontal overflow', () => {
  for (const width of viewportWidths) {
    test(`login page has no horizontal overflow at ${width}px`, async ({ browser }) => {
      const context = await browser.newContext();
      const page = await context.newPage();
      await page.setViewportSize({ width, height: 800 });
      await page.goto('/login');
      await page.waitForLoadState('networkidle');

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
      await page.waitForLoadState('networkidle');

      const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
      const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
      expect(scrollWidth, `Page content (${scrollWidth}px) overflows viewport (${clientWidth}px) at ${width}px`).toBeLessThanOrEqual(clientWidth);
    });
  }

  for (const width of viewportWidths) {
    test(`history page has no horizontal overflow at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 });
      await page.goto('/app/history');
      await page.waitForLoadState('networkidle');

      const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
      const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
      expect(scrollWidth, `Page content (${scrollWidth}px) overflows viewport (${clientWidth}px) at ${width}px`).toBeLessThanOrEqual(clientWidth);
    });
  }

  for (const width of viewportWidths) {
    test(`settings page has no horizontal overflow at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 800 });
      await page.goto('/app/settings');
      await page.waitForLoadState('networkidle');

      const scrollWidth = await page.evaluate(() => document.documentElement.scrollWidth);
      const clientWidth = await page.evaluate(() => document.documentElement.clientWidth);
      expect(scrollWidth, `Page content (${scrollWidth}px) overflows viewport (${clientWidth}px) at ${width}px`).toBeLessThanOrEqual(clientWidth);
    });
  }
});
