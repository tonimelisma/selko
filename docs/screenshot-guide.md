# Screenshot Capture Guide

Screenshots live in `docs/screenshots/` and are used for documentation and visual verification.

---

## How to Capture Screenshots

**There is ONE command.** Always use the unified script:

```bash
# All platforms (web + iOS + Android) — seeds data + runs all 3 in parallel
./scripts/capture-all-screenshots.sh

# Single platform
./scripts/capture-all-screenshots.sh web       # 24 web screenshots via Playwright
./scripts/capture-all-screenshots.sh ios       # 12 iOS screenshots via XCUITest
./scripts/capture-all-screenshots.sh android   # 12 Android screenshots via UiAutomator
```

**That's it.** The script handles everything: seeding data, booting simulators/emulators, building, running tests, pulling screenshots, and resizing.

> **Do NOT** manually seed data, run individual platform scripts (`capture-web-screenshots.sh` etc.), or use MCP tools for screenshot capture. Those are internal helpers called by the unified script.

> **Android:** Requires emulator (script starts one if needed). **iOS:** Requires iPhone 17 Pro simulator (script boots it if needed). **Web:** Starts its own dev server via Playwright.
>
> **Keep simulators/emulators running** after capture — they're reused for testing and future screenshots.

**Only prerequisite:** Local Supabase must be running (`supabase start`).

---

## Platform Connection Details

All three platforms connect to **local Supabase** (`localhost:54321`) in development/debug builds:

| Platform | Config File | Supabase URL | Anon Key |
|----------|------------|--------------|----------|
| Web | `frontend/.env` | `http://localhost:54321` | Local demo key (hardcoded) |
| iOS | `ios/Selko/Core/Config.swift` | `http://localhost:54321` (DEBUG default) | Local demo key (DEBUG default) |
| Android | `android/app/build.gradle.kts` | `http://10.0.2.2:54321` (debug buildType) | Local demo key (hardcoded) |

> **iOS/Web** use `localhost` directly. **Android** emulator uses `10.0.2.2` which maps to the host's `localhost`.

All platforms support environment variable overrides (`SUPABASE_URL`, `SUPABASE_ANON_KEY`) if you need to point to staging or production.

---

## Appendix: Debugging Reference

> **You should NOT need this section for normal screenshot capture.** Use `./scripts/capture-all-screenshots.sh` above. This section is reference material for debugging test failures or understanding the implementation.

### Screenshot User Credentials
- Email: `screenshots@selko.local`
- Password: `screenshotpass123`

### Web (Playwright)

The Playwright test (`frontend/tests/e2e/screenshots.spec.ts`) captures 24 screenshots: six screens at desktop and mobile sizes, each in light and dark appearance. It starts its own dev server.

- Never use `fullPage: true` — produces oversized images
- Desktop and mobile viewports are both safe (under 2000px)

### iOS (XCUITest)

The XCUITest (`ios/iOSUITests/ScreenshotCaptureTests.swift`) captures 12 screenshots on iPhone 17 Pro simulator: six screens in light and dark appearance.

**Accessibility Identifiers:**

| Element | Identifier |
|---------|-----------|
| Email field | `emailField` |
| Password field | `passwordField` |
| Sign in button | `signInButton` |
| Sign up button | `createAccountButton` |

Use XcodeBuildMCP `snapshot_ui()` to discover identifiers for other elements.

**Image sizing:** iPhone 17 Pro captures at 2622px height. The script resizes to 1920px. Both dimensions must be ≤ 2000px for the Claude API.

### Android (UiAutomator)

The UiAutomator test (`android/app/src/androidTest/.../ScreenshotCaptureTest.kt`) captures 12 screenshots: six screens in light and dark appearance.

**Key implementation details:**

- **Compose text input:** `By.text("Email")` finds the label `TextView` inside a Compose `OutlinedTextField`, NOT the `EditText` itself. You must navigate to `label.parent` (the `EditText`) before calling `.text = value`. Setting text on the label is a **silent no-op**.
- **Keyboard dismissal:** After entering text, call `device.pressBack()` to dismiss the soft keyboard before tapping buttons or looking for bottom nav items. The keyboard covers the bottom navigation bar.
- **Screenshot order:** Capture History and Settings tabs BEFORE navigating to Event Detail. Back-navigation from Event Detail is unreliable on Android 16 (API 36) due to predictive back gesture changes.
- **adb pull path:** `adb pull .../Pictures/ $DIR/` creates a `Pictures/` subdirectory inside `$DIR`. The script accounts for this.
- **Image sizing:** Emulator captures at 1080x2400. The script resizes to 1920px height.

### Manual MCP Capture (Last Resort Fallback)

Only use if the automated scripts are broken and you need screenshots urgently.

- **Web:** Playwright MCP — `browser_navigate`, `browser_take_screenshot`, `browser_resize`
- **iOS:** XcodeBuildMCP — `build_run_sim`, `screenshot`, `tap`, `type_text`
- **Android:** mobile-mcp — `mobile_take_screenshot`, `mobile_click_on_screen_at_coordinates`, `mobile_type_keys`

---

## Complete Screenshot Checklist

Every standard screen is captured in both light and dark appearances. Append
`-light` or `-dark` immediately before `.png`; for example,
`web-history-desktop-light.png` and `web-history-desktop-dark.png`.

| Screenshot | Filename | Viewport/Device |
|-----------|----------|-----------------|
| Web login (desktop) | `web-login-desktop-{light,dark}.png` | 1280x800 |
| Web register (desktop) | `web-register-desktop-{light,dark}.png` | 1280x800 |
| Web review queue (desktop) | `web-review-queue-desktop-{light,dark}.png` | 1280x800 |
| Web event detail (desktop) | `web-event-detail-desktop-{light,dark}.png` | 1280x800 |
| Web history (desktop) | `web-history-desktop-{light,dark}.png` | 1280x800 |
| Web settings (desktop) | `web-settings-desktop-{light,dark}.png` | 1280x800 |
| Web login (mobile) | `web-login-mobile-{light,dark}.png` | 390x844 |
| Web register (mobile) | `web-register-mobile-{light,dark}.png` | 390x844 |
| Web review queue (mobile) | `web-review-queue-mobile-{light,dark}.png` | 390x844 |
| Web event detail (mobile) | `web-event-detail-mobile-{light,dark}.png` | 390x844 |
| Web history (mobile) | `web-history-mobile-{light,dark}.png` | 390x844 |
| Web settings (mobile) | `web-settings-mobile-{light,dark}.png` | 390x844 |
| iOS login | `ios-login-{light,dark}.png` | iPhone 17 Pro |
| iOS register | `ios-register-{light,dark}.png` | iPhone 17 Pro |
| iOS review queue | `ios-review-queue-{light,dark}.png` | iPhone 17 Pro |
| iOS event detail | `ios-event-detail-{light,dark}.png` | iPhone 17 Pro |
| iOS history | `ios-history-{light,dark}.png` | iPhone 17 Pro |
| iOS settings | `ios-settings-{light,dark}.png` | iPhone 17 Pro |
| Android login | `android-login-{light,dark}.png` | Emulator |
| Android register | `android-register-{light,dark}.png` | Emulator |
| Android review queue | `android-review-queue-{light,dark}.png` | Emulator |
| Android event detail | `android-event-detail-{light,dark}.png` | Emulator |
| Android history | `android-history-{light,dark}.png` | Emulator |
| Android settings | `android-settings-{light,dark}.png` | Emulator |

The final matrix contains 48 screenshots: 24 web, 12
iOS, and 12 Android.

---

## Troubleshooting

### "No API key found in request" (iOS)
The iOS app's `SUPABASE_ANON_KEY` is empty. In DEBUG builds, it should default to the local demo key. If you see this error:
- Ensure you're on a commit that includes the fix in `Config.swift` (PR #60)
- Rebuild the app: `build_run_sim()`

### Web form has stale credentials
Clear fields before screenshotting: use `browser_run_code` to fill empty strings, or navigate to the page fresh.

### Android emulator won't start ("snapshot operation pending")
Delete stale lock files: `rm ~/.android/avd/Pixel_8.avd/*.lock`, then retry with `emulator -avd Pixel_8 -no-snapshot-load`.

### Android emulator can't reach Supabase
The emulator uses `10.0.2.2` to reach the host's `localhost`. Ensure local Supabase is running on port 54321.

### iOS test fails: "No matches found for createAccountButton"
The app is already logged in from a previous test run. The test expects to start from the login screen. Fix: the screenshot test should log out first if it detects an authenticated state, or uninstall/reinstall the app before running.

### Screenshots too large for Claude API
Both dimensions must be ≤ 2000px. Resize with:
```bash
sips --resampleHeight 1920 docs/screenshots/ios-*.png docs/screenshots/android-*.png
```
