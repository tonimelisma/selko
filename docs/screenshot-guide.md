# Screenshot Capture Guide

Step-by-step guide for capturing product screenshots across all platforms.

Screenshots live in `docs/screenshots/` and are used for documentation and visual verification.

---

## Quick Start (Scripted)

Capture all 24 screenshots in ~3 minutes using automated scripts instead of manual MCP interaction.

**Prerequisites:** Local Supabase running + seed data loaded (see below).

```bash
# All platforms (web + iOS + Android)
./scripts/capture-all-screenshots.sh

# Single platform
./scripts/capture-all-screenshots.sh web       # 12 web screenshots via Playwright
./scripts/capture-all-screenshots.sh ios       # 6 iOS screenshots via XCUITest
./scripts/capture-all-screenshots.sh android   # 6 Android screenshots via UiAutomator
```

> **Android:** Requires a running emulator. **iOS:** Requires iPhone 17 Pro simulator. **Web:** Starts its own dev server via Playwright.

---

## Prerequisites

1. **Local Supabase running:** `supabase start`
2. **Seed data exists:** Run `uv run python scripts/seed_screenshot_data.py seed --cleanup-first` to create the screenshot user and sample data

**Screenshot user credentials:**
- Email: `screenshots@selko.local`
- Password: `screenshotpass123`

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

## Web Screenshots

**Tools:** Playwright MCP (`browser_navigate`, `browser_take_screenshot`, `browser_resize`)

### Steps

1. Start the dev server:
   ```bash
   cd frontend && npm run dev
   ```

2. Load Playwright MCP tools (ToolSearch: `+playwright navigate screenshot`)

3. **Desktop viewport** (1280x800):
   ```
   browser_resize(1280, 800)
   ```

4. Capture unauthenticated pages:
   - Navigate to `http://localhost:5173/login` → screenshot `web-login-desktop.png`
   - Navigate to `http://localhost:5173/register` → screenshot `web-register-desktop.png`

5. Log in:
   - Fill email: `screenshots@selko.local`, password: `screenshotpass123`
   - Click "Sign in"

6. Capture authenticated pages:
   - Review queue (landing page `/app`) → `web-review-queue-desktop.png`
   - Click an event to view detail → `web-event-detail-desktop.png`
   - Navigate to `/app/history` → `web-history-desktop.png`
   - Navigate to `/app/settings` → `web-settings-desktop.png`

7. **Mobile viewport** (390x844):
   ```
   browser_resize(390, 844)
   ```
   Repeat steps 4-6 with `-mobile` suffix (e.g., `web-login-mobile.png`)

8. **When done:** `browser_close`, then stop the dev server

### Notes
- Clear any stale form data before taking login/register screenshots
- Never use `fullPage: true` — produces oversized images
- Desktop and mobile viewports are both safe (under 2000px)

---

## iOS Screenshots

**Tools:** XcodeBuildMCP (`build_run_sim`, `screenshot`, `tap`, `type_text`, `snapshot_ui`)

### Steps

1. Load XcodeBuildMCP tools (ToolSearch: `+XcodeBuildMCP session build screenshot tap`)

2. Set session defaults:
   ```
   session-set-defaults({
     projectPath: "/absolute/path/to/selko/ios/iOS.xcodeproj",
     scheme: "iOS",
     simulatorName: "iPhone 17 Pro"
   })
   ```
   > **Must use absolute path** for `projectPath`

3. Build and run:
   ```
   build_run_sim()
   ```
   After build succeeds, set `simulatorId` and `bundleId` from the output:
   ```
   session-set-defaults({ simulatorId: "<id>", bundleId: "net.melisma.Selko" })
   ```

4. Take login screenshot:
   ```
   screenshot({ returnFormat: "path" })
   ```
   Read the image with Read tool, then copy to `docs/screenshots/ios-login.png`

5. Tap "Sign up" → screenshot → save as `ios-register.png` → tap "Cancel" to go back

6. Log in:
   - `tap({ id: "emailField" })` → `type_text("screenshots@selko.local")`
   - `tap({ id: "passwordField" })` → `type_text("screenshotpass123")`
   - `tap({ id: "signInButton" })`
   - Wait 2-3 seconds for navigation

7. Capture authenticated pages:
   - Review queue (initial screen) → `ios-review-queue.png`
   - Tap an event card → `ios-event-detail.png`
   - Navigate back, tap "History" tab → `ios-history.png`
   - Tap "Settings" tab → `ios-settings.png`

8. **When done:** `stop_app_sim()` to stop the app

### Accessibility Identifiers (for tap)

| Element | Identifier |
|---------|-----------|
| Email field | `emailField` |
| Password field | `passwordField` |
| Sign in button | `signInButton` |
| Sign up button | `createAccountButton` |

Use `snapshot_ui()` to discover identifiers for other elements.

### Image Size
- Check dimensions with `sips -g pixelHeight -g pixelWidth <file>`
- If height > 2000px: `sips --resampleHeight 1920 <file>`

---

## Android Screenshots

**Preferred: Use the automated script** (`./scripts/capture-android-screenshots.sh`). The manual MCP approach below is a fallback.

### Prerequisites
- Android emulator running: `emulator -avd Pixel_8` (or start from Android Studio)
- Local Supabase running with seed data

> **Cold boot tip:** After a cold boot (`-no-snapshot-load`), wait ~60s for "System UI isn't responding" dialogs to stop. If the emulator won't start with "snapshot operation pending", delete `~/.android/avd/Pixel_8.avd/*.lock`.

### Scripted Capture (Recommended)

```bash
./scripts/capture-android-screenshots.sh
```

This builds and installs the debug APK, runs the UiAutomator instrumented test (`ScreenshotCaptureTest.kt`), pulls screenshots from the device, and resizes them to ≤1920px.

### Key Implementation Details (for debugging)

The UiAutomator test (`android/app/src/androidTest/.../ScreenshotCaptureTest.kt`) has these important patterns:

- **Compose text input:** `By.text("Email")` finds the label `TextView` inside a Compose `OutlinedTextField`, NOT the `EditText` itself. You must navigate to `label.parent` (the `EditText`) before calling `.text = value`. Setting text on the label is a **silent no-op**.
- **Keyboard dismissal:** After entering text, call `device.pressBack()` to dismiss the soft keyboard before tapping buttons or looking for bottom nav items. The keyboard covers the bottom navigation bar.
- **Screenshot order:** Capture History and Settings tabs BEFORE navigating to Event Detail. Back-navigation from Event Detail is unreliable on Android 16 (API 36) due to predictive back gesture changes.
- **adb pull path:** `adb pull .../Pictures/ $DIR/` creates a `Pictures/` subdirectory inside `$DIR`. The script accounts for this.

### Manual MCP Capture (Fallback)

**Tools:** mobile-mcp (`mobile_take_screenshot`, `mobile_click_on_screen_at_coordinates`, `mobile_type_keys`, `mobile_list_elements_on_screen`)

1. Build and install: `cd android && ./gradlew installDebug`
2. Load mobile-mcp tools (ToolSearch: `+mobile screenshot tap type`)
3. Launch: `mobile_launch_app({ appId: "net.melisma.selko" })`
4. Use `mobile_list_elements_on_screen()` to find coordinates, `mobile_click_on_screen_at_coordinates()` to tap, `mobile_type_keys()` to type
5. Capture all 6 screens: login, register, review-queue, history, settings, event-detail
6. **When done:** `mobile_terminate_app({ appId: "net.melisma.selko" })`

### Notes
- Android emulator screenshots are 1080x2400 — **always resize** after capture: `sips --resampleHeight 1920 docs/screenshots/android-*.png`
- If `mobile-mcp` loses the device, restart adb: `adb kill-server && adb start-server`
- The `mobile_launch_app` function may fail right after install — launch via adb instead: `adb shell am start -n net.melisma.selko/.MainActivity`

---

## Complete Screenshot Checklist

| Screenshot | Filename | Viewport/Device |
|-----------|----------|-----------------|
| Web login (desktop) | `web-login-desktop.png` | 1280x800 |
| Web register (desktop) | `web-register-desktop.png` | 1280x800 |
| Web review queue (desktop) | `web-review-queue-desktop.png` | 1280x800 |
| Web event detail (desktop) | `web-event-detail-desktop.png` | 1280x800 |
| Web history (desktop) | `web-history-desktop.png` | 1280x800 |
| Web settings (desktop) | `web-settings-desktop.png` | 1280x800 |
| Web login (mobile) | `web-login-mobile.png` | 390x844 |
| Web register (mobile) | `web-register-mobile.png` | 390x844 |
| Web review queue (mobile) | `web-review-queue-mobile.png` | 390x844 |
| Web event detail (mobile) | `web-event-detail-mobile.png` | 390x844 |
| Web history (mobile) | `web-history-mobile.png` | 390x844 |
| Web settings (mobile) | `web-settings-mobile.png` | 390x844 |
| iOS login | `ios-login.png` | iPhone 17 Pro |
| iOS register | `ios-register.png` | iPhone 17 Pro |
| iOS review queue | `ios-review-queue.png` | iPhone 17 Pro |
| iOS event detail | `ios-event-detail.png` | iPhone 17 Pro |
| iOS history | `ios-history.png` | iPhone 17 Pro |
| iOS settings | `ios-settings.png` | iPhone 17 Pro |
| Android login | `android-login.png` | Emulator |
| Android register | `android-register.png` | Emulator |
| Android review queue | `android-review-queue.png` | Emulator |
| Android event detail | `android-event-detail.png` | Emulator |
| Android history | `android-history.png` | Emulator |
| Android settings | `android-settings.png` | Emulator |

**Total: 24 screenshots**

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

### Screenshots too large for Claude API
Both dimensions must be ≤ 2000px. Resize with:
```bash
sips --resampleHeight 1920 docs/screenshots/ios-*.png docs/screenshots/android-*.png
```
