import { defineConfig, devices } from '@playwright/test';

// Support testing against staging via STAGING_FRONTEND_URL env var
const stagingUrl = process.env.STAGING_FRONTEND_URL;
const baseURL = stagingUrl || 'http://localhost:5173';

export default defineConfig({
	testDir: './tests/e2e',
	fullyParallel: true,
	forbidOnly: !!process.env.CI,
	retries: process.env.CI ? 2 : 0,
	workers: process.env.CI ? 1 : undefined,
	reporter: 'html',
	use: {
		baseURL,
		trace: 'on-first-retry'
	},
	projects: [
		{
			name: 'chromium',
			use: { ...devices['Desktop Chrome'] }
		}
	],
	// Only start local dev server when not testing against staging
	webServer: stagingUrl
		? undefined
		: {
				command: 'npm run dev',
				url: 'http://localhost:5173',
				reuseExistingServer: !process.env.CI,
				timeout: 120 * 1000
			}
});
