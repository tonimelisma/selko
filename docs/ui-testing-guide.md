# UI Testing Guide

Comprehensive guide to UI testing in Selko, covering three layers: unit/component tests, E2E tests, and MCP visual verification.

---

## Testing Layers

| Layer | Tool | What It Tests | When to Run |
|-------|------|---------------|-------------|
| Unit/Component | Vitest (web), XCTest (iOS), JUnit (Android) | Individual components in isolation | Every commit (pre-commit hook) |
| E2E / Integration | Playwright (web), XCUITest (iOS), Compose UI Tests (Android) | Full user journeys through the app | Before PRs, CI |
| MCP Visual | Playwright MCP, XcodeBuildMCP, mobile-mcp | Visual appearance, layout, responsiveness | On-demand during development |

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

**Auth fixture:** Tests that need authentication use the shared auth fixture from `frontend/tests/e2e/fixtures/auth.ts`. This logs in once via the UI and reuses stored Supabase auth state.

```typescript
import { test } from './fixtures/auth';

test('authenticated page works', async ({ page }) => {
  await page.goto('/app');
  await expect(page.getByRole('heading')).toBeVisible();
});
```

**Prerequisites:**
- Local Supabase running (`supabase start`)
- Test user created (`test@selko.local` / `testpass123`)

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

## iOS XCUITests

### Running Tests

```bash
xcodebuild test -project ios/iOS.xcodeproj -scheme iOS \
  -destination 'platform=iOS Simulator,name=iPhone 16' \
  -resultBundlePath ios/TestResults.xcresult
```

### Accessibility Identifiers

All testable views should have `accessibilityIdentifier` set on key elements. Convention:

| View | Identifier Pattern | Example |
|------|-------------------|---------|
| Buttons | `camelCaseAction` | `approveButton`, `rejectButton` |
| Lists | `camelCaseList` | `eventList`, `historyList` |
| State views | `camelCaseState` | `emptyStateView`, `reviewQueueLoading` |
| Text fields | `camelCaseField` | `eventDetailTitle`, `eventDetailDate` |

### Test Pattern

Follow the existing pattern in `SelkoUITests.swift`:

```swift
final class ReviewQueueUITests: XCTestCase {
    let app = XCUIApplication()

    override func setUp() {
        super.setUp()
        continueAfterFailure = false
        app.launchArguments = ["--uitesting"]
        app.launch()
    }

    func testElementExists() {
        let element = app.staticTexts["expectedText"]
        XCTAssertTrue(element.waitForExistence(timeout: 5))
    }
}
```

**Key points:**
- Use `app.launchArguments = ["--uitesting"]` for test configuration
- Use `waitForExistence(timeout: 5)` for async elements
- Look up elements by `accessibilityIdentifier` or text content

### Auth in Tests

Tests for post-login screens need to navigate through login first. Use a shared helper that fills email/password and taps sign-in, or leverage the `--uitesting` launch argument for auto-authentication.

---

## Android Compose UI Tests

### Running Tests

```bash
# Requires a running emulator or connected device
cd android && ./gradlew connectedAndroidTest
```

### Test Pattern

Follow the existing pattern in `AuthScreenTest.kt`:

```kotlin
class ReviewQueueScreenTest {
    @get:Rule
    val composeTestRule = createComposeRule()

    private val repository = mockk<SomeRepository>(relaxed = true)

    @Test
    fun reviewQueueDisplaysTitle() {
        val viewModel = ReviewQueueViewModel(repository)

        composeTestRule.setContent {
            SelkoTheme {
                ReviewQueueScreen(viewModel = viewModel)
            }
        }

        composeTestRule.onNodeWithText("Review Queue")
            .assertIsDisplayed()
    }
}
```

**Key points:**
- Use `createComposeRule()` with `@get:Rule`
- Mock repositories with `mockk(relaxed = true)`
- Use `MutableStateFlow` for reactive ViewModel state
- Wrap content in `SelkoTheme { }`
- Find elements with `onNodeWithText()` (matches existing pattern — no `testTag`)
- Assert with `assertIsDisplayed()`, `performClick()`, etc.

### Test Organization

Tests live in `android/app/src/androidTest/java/net/melisma/selko/ui/screens/`:

| Directory | Tests |
|-----------|-------|
| `review/` | ReviewQueueScreenTest, EventDetailScreenTest |
| `history/` | HistoryScreenTest |
| `settings/` | SettingsScreenTest |

---

## MCP Visual Verification

### What It Is

MCP (Model Context Protocol) servers give Claude Code direct access to browsers, iOS simulators, and Android emulators. This enables visual verification — Claude can screenshot the running app and analyze the UI.

### MCP Servers

Configured in `.mcp.json`:

| Server | Purpose | Key Tools |
|--------|---------|-----------|
| `playwright` | Browser automation + screenshots | `browser_navigate`, `browser_screenshot`, `browser_snapshot`, `browser_resize` |
| `XcodeBuildMCP` | iOS build + simulator control | Build, launch, screenshot |
| `mobile-mcp` | iOS Simulator + Android Emulator | `mobile_take_screenshot`, `mobile_tap`, `mobile_launch_app`, `mobile_list_elements_on_screen` |

### Slash Commands

Three slash commands are available for visual verification:

| Command | What It Does |
|---------|-------------|
| `/verify-web` | Screenshots web app at 3 viewports, checks layout, responsiveness, accessibility tree |
| `/verify-ios` | Builds iOS app, launches simulator, screenshots each screen, checks accessibility |
| `/verify-android` | Installs Android app, launches on emulator, screenshots each screen, checks accessibility |

### When to Use

- **After implementing a new screen** — run the relevant `/verify-*` command to check your work
- **After layout changes** — verify responsiveness across viewports
- **Before creating a PR** — quick visual sanity check
- **Debugging visual issues** — get screenshots without leaving the terminal

### How It Works

1. Run the slash command (e.g., `/verify-web`)
2. Claude uses MCP tools to navigate the app, capture screenshots, and inspect accessibility
3. Claude analyzes each screenshot and reports PASS/ISSUE findings
4. Fix any issues and re-run

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

Requires Supabase to be running in CI (use `supabase start` in workflow).

### iOS (XCUITests)

Requires macOS runner. Add to iOS CI workflow:

```yaml
runs-on: macos-latest
steps:
  - name: Run XCUITests
    run: |
      xcodebuild test -project ios/iOS.xcodeproj -scheme iOS \
        -destination 'platform=iOS Simulator,name=iPhone 16' \
        -resultBundlePath ios/TestResults.xcresult
```

### Android (Compose UI Tests)

Requires Android emulator. Add to Android CI workflow:

```yaml
- name: Run instrumented tests
  uses: reactivecircus/android-emulator-runner@v2
  with:
    api-level: 34
    script: cd android && ./gradlew connectedAndroidTest
```
