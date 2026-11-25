# UI Testing Guide

Guide to UI testing of the web app, Selko's only client, in three layers: unit/component tests, E2E tests, and MCP visual verification. The native iOS and Android apps are unmaintained and untested (`legacy/README.md`).

---

## Testing Layers

| Layer | Tool | What It Tests | When to Run |
|-------|------|---------------|-------------|
| Unit/Component | Vitest | Individual components in isolation | Every commit (pre-commit hook) |
| E2E / Integration | Playwright | Full user journeys through the app | Before PRs, CI |
| MCP Visual | Playwright MCP | Visual appearance, layout, responsiveness | On-demand during development |

---

## Web E2E Testing (Playwright)

### Setup

Playwright is configured in `frontend/`. Install dependencies:

```bash
cd frontend && npm ci
npx playwright install
```

### Running Tests

```bash
# All browsers
cd frontend && npm run test:e2e

# Single browser (fastest for development)
cd frontend && npm run test:e2e -- --project=chromium

# Headed mode (see the browser)
cd frontend && npm run test:e2e:headed

# Interactive UI mode
cd frontend && npm run test:e2e:ui
```

### Configuration

Config file: `frontend/playwright.config.ts`

**Projects (5 browsers/viewports):**

| Project | Device | Viewport |
|---------|--------|----------|
| chromium | Desktop Chrome | 1280x720 |
| webkit | Desktop Safari | 1280x720 |
| mobile-chrome | Pixel 5 | 393x851 |
| mobile-safari | iPhone 13 | 390x844 |
| tablet | iPad-like | 768x1024 |

**Web server:** Auto-starts `npm run dev` on localhost:5173.

**Traces:** Captured on first retry for debugging.

**Screenshots:** Captured on failure.

### Writing Tests

Test files go in `frontend/tests/e2e/`. File naming: `*.spec.ts`.

**Auth:** `frontend/tests/e2e/auth.setup.ts` (the `setup` project) logs in once via the UI and saves the browser state to `tests/e2e/.auth/user.json`; the other projects reuse it. That state carries the `selko_refresh` cookie, from which the app restores its session.

```typescript
import { test } from './fixtures/auth';

test('authenticated page works', async ({ page }) => {
  await page.goto('/app');
  await expect(page.getByRole('heading')).toBeVisible();
});
```

**Prerequisites:**
- The local API running over a data directory (`uv run uvicorn selko.api.app:app --port 8000`), or set `SELKO_E2E_BASE_URL` to an API that serves the built app
- Test user created (`test@selko.local` / `testpass123`), e.g. through `/register`

### Debugging Failed Tests

```bash
# Show trace viewer for last run
npx playwright show-trace frontend/test-results/*/trace.zip

# Run a single test with debug
cd frontend && npx playwright test auth.spec.ts --debug
```

### Mobile Viewport Testing

The `mobile-chrome` and `mobile-safari` projects automatically test at phone viewports. The `tablet` project tests at 768x1024. This ensures responsive layouts are covered.

---

## MCP Visual Verification

### What It Is

MCP (Model Context Protocol) servers give Claude Code direct access to a browser. This enables visual verification — Claude can screenshot the running app and analyze the UI.

### MCP Servers



| Server | Purpose | Key Tools |
|--------|---------|-----------|
| `playwright` | Browser automation + screenshots | `browser_navigate`, `browser_screenshot`, `browser_snapshot`, `browser_resize` |
### Standard Visual Verification

Use the screenshot capture script for standard visual verification:

```bash
./scripts/capture-all-screenshots.sh web
```

The script handles seeding and capturing automatically. Review the resulting screenshots in `docs/screenshots/` to verify UI correctness.

### MCP Tools (Manual Debugging Only)

MCP tools (`/verify-web`) are available for **manual debugging only**:

- Clicking a new button or testing a specific interaction
- Investigating a visual bug that screenshots alone can't diagnose
- Testing dynamic behavior (animations, swipe gestures, state transitions)

Do NOT use MCP tools or `/verify-*` slash commands as a standard verification step in the Definition of Done.

---

## CI Integration (Future)

### Web (Playwright)

Add to `.github/workflows/frontend-tests.yml`:

```yaml
- name: Install Playwright Browsers
  run: cd frontend && npx playwright install --with-deps
- name: Run E2E tests
  run: cd frontend && npm run test:e2e
```

Needs the API running in CI (no database service: it creates its own SQLite file).
