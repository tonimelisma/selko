# Changelog

All notable changes to this project are documented in this file.

## 2026-02-11 - Fix Android Review Queue Consistency

### Fix: Add email grouping and fix button order in Android review queue

**Changes:**

1. **3-level hierarchy:** Review queue now groups events as Sender > Email > Events (was Sender > Events), matching web and iOS behavior
2. **Button order:** Changed event card action buttons from Reject/Edit/Approve to Approve/Edit/Reject, matching web and iOS order
3. **Email group header:** New `EmailGroupHeader` composable shows email subject, date, and "Approve All" button for multi-event emails
4. **Approve email group:** New `approveEmailGroup()` method in ViewModel for batch-approving all events from a single email

**Files Modified:**
- `android/app/src/main/java/net/melisma/selko/ui/screens/review/ReviewQueueViewModel.kt` - Added `EmailGroup` data class, updated `SenderGroup` to use `emailGroups`, updated `groupBySender()` for sub-grouping, added `approveEmailGroup()`
- `android/app/src/main/java/net/melisma/selko/ui/screens/review/ReviewQueueScreen.kt` - Added `EmailGroupHeader` composable, updated LazyColumn for 3-level hierarchy, updated `SenderGroupHeader` to use `allEvents`
- `android/app/src/main/java/net/melisma/selko/ui/screens/review/EventCardContent.kt` - Reordered buttons to Approve/Edit/Reject, changed Edit from `IconButton` to `OutlinedButton`

---

## 2026-02-11 - Fix iOS Review Queue Consistency

### Fix: Add email grouping and visible action buttons to iOS review queue

**Changes:**

1. **3-level hierarchy:** Review queue now groups events as Sender > Email > Events (was Sender > Events), matching web and Android
2. **Email group header:** New `EmailGroupView` shows envelope icon, email subject, date, and "Approve All" button for multi-event emails
3. **Visible action buttons:** Added Approve, Edit, and Reject buttons at the bottom of each event card (previously swipe-only)
4. **Approve email group:** New `approveAllInEmailGroup()` method for batch-approving all events from a single email

**Files Modified:**
- `ios/Selko/Features/Review/ViewModels/ReviewQueueViewModel.swift` - Added `EmailGroup` struct, updated `SenderGroup` to use `emailGroups`, updated grouping and removal logic
- `ios/Selko/Features/Review/Views/ReviewQueueView.swift` - Updated to nest email groups within sender sections, pass action callbacks
- `ios/Selko/Features/Review/Views/EventCardView.swift` - Added `onApprove`, `onEdit`, `onReject` callbacks with visible button row
- `ios/Selko/Features/Review/Views/SenderGroupView.swift` - Updated to use `allEvents.count`

**Files Added:**
- `ios/Selko/Features/Review/Views/EmailGroupView.swift` - New email group header view

---

## 2026-02-11 - Fix Web Review Queue Consistency

### Fix: Improve web review queue button layout, add Edit button and email icon

**Issues Fixed:**
1. **EventCard button placement:** Moved buttons from top-right inline with title to a separate row at the bottom-right of the card
2. **EventCard button order:** Changed from Reject + Approve to Approve + Edit + Reject (matching spec)
3. **EventCard Edit button:** Added new Edit button with pencil icon that calls `onedit` callback
4. **EventCard max width:** Added `max-w-3xl` to prevent cards from stretching full-width on desktop
5. **EmailHeader envelope icon:** Added envelope SVG icon before the subject text for visual distinction

**Files Modified:**
- `frontend/src/lib/components/EventCard.svelte`
- `frontend/src/lib/components/EmailHeader.svelte`

---

## 2026-02-11 - Fix iOS Email Placeholder Color

### Fix: Use correct placeholder text color on login and register screens

**Issue:** Email field placeholders ("you@example.com") appeared in blue instead of standard grey on iOS login and register screens. SwiftUI's TextField ignores all foreground styling on placeholder text (`.foregroundStyle()`, `.foregroundColor()`, `.tint()`, overlays, ZStacks, Canvas, `.drawingGroup()` — none work).

**Fix:** Replaced the SwiftUI TextField with a minimal `UIViewRepresentable` wrapper (`PlaceholderTextField`) that uses UITextField's `attributedPlaceholder` with `UIColor.placeholderText` for correct grey placeholder rendering.

**Files Modified:**
- `ios/Selko/Features/Auth/Views/LoginView.swift`
- `ios/Selko/Features/Auth/Views/RegisterView.swift`

---

## 2026-02-11 - Fix Android Screenshot Review Issues

### Fix: Resolve 2 Android UI issues found during screenshot review

**Issues Fixed:**
1. **Event Detail date/time fields:** Replaced raw ISO text fields with Material3 DatePicker and TimePicker dialogs for proper date/time editing
2. **Settings logout button:** Changed from filled red button to outlined button with error color for a less aggressive appearance

**Files Modified:**
- `android/app/src/main/java/net/melisma/selko/ui/screens/review/EventDetailViewModel.kt`
- `android/app/src/main/java/net/melisma/selko/ui/screens/review/EventDetailScreen.kt`
- `android/app/src/main/java/net/melisma/selko/ui/screens/settings/SettingsScreen.kt`

---

## 2026-02-11 - Fix iOS Screenshot Review Issues

### Fix: Resolve 6 iOS UI issues found during screenshot review

**Issues Fixed:**
1. **Event Detail blank form (P0):** Form nested inside ScrollView collapsed to zero height — made Form the root scrollable container on iPhone
2. **Register dimmed overlay:** Changed `.sheet` to `.fullScreenCover` so register screen isn't dimmed
3. **Settings calendar message:** Changed "No calendars available" to match web/Android wording
4. **Login blue placeholder:** Used explicit prompt styling with `.secondary` foreground
5. **Review Queue sort order:** Removed alphabetical sort to preserve database insertion order (matches web/Android)
6. **Brand name color:** Added `.foregroundStyle(Color.accentColor)` to "Selko" heading on login

**Files Modified:**
- `ios/Selko/Features/Review/Views/EventDetailView.swift`
- `ios/Selko/Features/Auth/Views/LoginView.swift`
- `ios/Selko/Features/Settings/Views/SettingsView.swift`
- `ios/Selko/Features/Review/ViewModels/ReviewQueueViewModel.swift`

---

## 2026-02-11 - Fix Web Screenshot Review Issues

### Fix: Resolve 3 web UI issues found during screenshot review

**Issues Fixed:**
1. **Settings mobile disconnect clipped:** Added flex-shrink-0 to buttons container and min-w-0 to text container to prevent button truncation
2. **Event detail mobile description cut off:** Added bottom padding (pb-24) to form to account for fixed bottom action bar
3. **Brand name color:** Added text-primary to "Selko" heading on login and register pages

**Files Modified:**
- `frontend/src/lib/components/IntegrationStatus.svelte`
- `frontend/src/routes/app/events/[id]/+page.svelte`
- `frontend/src/routes/login/+page.svelte`
- `frontend/src/routes/register/+page.svelte`

---

## 2026-02-10 - Fix iOS Model Deserialization

### Fix: Make iOS Email model tolerant of partial data from nested Supabase joins

**Problem:** Supabase nested joins (e.g., `events(emails(id, subject, from_email, from_name, date_sent))`) only return selected fields, but the iOS `Email` model required all fields — causing deserialization failures and empty screens.

**Solution:** Made all non-id fields in `Email` optional so partial selects decode correctly. Also fixed `UserCalendarSettings` to match the actual database schema (`user_id` PK, `target_calendar_id`, `default_invitees`).

**Files Modified:**
- `ios/Selko/Features/Emails/Models/Email.swift` — Made non-id fields optional
- `ios/Selko/Features/Settings/Services/CalendarSettingsService.swift` — Fixed model to match DB schema
- `ios/Selko/Features/Settings/ViewModels/SettingsViewModel.swift` — Updated field reference

---

## 2026-02-10 - Fix Android Model Deserialization

### Fix: Make Android Email model tolerant of partial data from nested Supabase joins

**Problem:** Supabase nested joins (e.g., `events(emails(id, subject, from_email, from_name, date_sent))`) only return selected fields, but the Android `Email` model required `userId` and `gmailId` to be non-null — causing deserialization failures and empty screens.

**Solution:** Made `userId` and `gmailId` optional with null defaults so partial selects decode correctly.

**Files Modified:**
- `android/app/src/main/java/net/melisma/selko/data/model/Email.kt` — Made `userId` and `gmailId` optional with defaults

---

## 2026-02-10 - Fix Screenshot Infrastructure

### Fix: Fix screenshot spec path and storageState, add Android cleartext config

**Frontend (screenshots.spec.ts):**
- Fixed `SCREENSHOT_DIR` path from `../../docs/screenshots` to `../docs/screenshots` (was saving outside the repo)
- Added `storageState: undefined` to all `browser.newContext()` calls to prevent the chromium project's saved auth state from interfering with the screenshot user's login

**Android:**
- Added `network_security_config.xml` allowing cleartext HTTP to `10.0.2.2` (emulator localhost alias)
- Referenced config in `AndroidManifest.xml` — required for debug builds to connect to local Supabase

**Files Changed:**
- `frontend/tests/e2e/screenshots.spec.ts`
- `android/app/src/main/AndroidManifest.xml`
- `android/app/src/main/res/xml/network_security_config.xml` (new)

---

## 2026-02-10 - Add Web Screenshot Capture Spec

### Feat: Add Playwright test spec for capturing web screenshots

Added `screenshots.spec.ts` — a Playwright E2E test that captures screenshots of all web screens at desktop (1280x800) and mobile (390x844) viewports.

**Screens captured (12 screenshots = 6 screens x 2 viewports):**
- Login page (`/login`)
- Register page (`/register`)
- Review Queue (`/app`) — requires login
- Event Detail (`/app/events/[id]`) — navigated from review queue
- Activity History (`/app/history`) — requires login
- Settings (`/app/settings`) — requires login

**Design decisions:**
- Uses its own user (`screenshots@selko.local`) independent of the existing auth setup
- Creates browser contexts manually via `browser.newContext()` so the chromium project's `storageState` does not interfere
- Screenshots saved to `docs/screenshots/` at project root
- Assumes seed data has been pre-inserted (by a separate seed script)

**Files Added:**
- `frontend/tests/e2e/screenshots.spec.ts`

---

## 2026-02-10 - iOS Local Supabase Config

### Feat: Add environment variable override for iOS Supabase URL

**Problem:** The iOS `Config.supabaseURL` was hardcoded to staging (DEBUG) and production (RELEASE) URLs. When using XcodeBuildMCP to launch the app on the simulator for local development, there was no way to point it at a local Supabase instance (`http://localhost:54321`).

**Solution:** Added `ProcessInfo.processInfo.environment["SUPABASE_URL"]` check at the top of `supabaseURL`, matching the existing pattern used by `apiURL` and `supabaseAnonKey`. When the environment variable is set, it takes priority over the hardcoded defaults. This allows XcodeBuildMCP to pass `SUPABASE_URL=http://localhost:54321` when launching the app.

**Files Modified:**
- `ios/Selko/Core/Config.swift`

---

## 2026-02-10 - Screenshot Data Seed Script

### Feat: Add seed script for screenshot test data

Created `scripts/seed_screenshot_data.py` that seeds and cleans up realistic fake data for capturing product screenshots.

**Usage:**
```bash
uv run python scripts/seed_screenshot_data.py seed            # Create user + data
uv run python scripts/seed_screenshot_data.py cleanup         # Remove everything
uv run python scripts/seed_screenshot_data.py seed --cleanup-first  # Clean + re-seed
```

**Test user:** `screenshots@selko.local` / `screenshotpass123` (display name: "Sarah Johnson")

**Seeded data:**
- 2 integrations (Gmail + Google Calendar, both active)
- 4 emails (school notices, dental appointment, work offsite)
- 7 events across all statuses (3 pending_review, 1 synced, 1 approved, 1 rejected, 1 sync_failed)
- 4 event sources linking events to their source emails with extracted quotes
- 1 calendar settings record (target calendar: primary)

**Cleanup** deletes the auth user; all related records are removed via ON DELETE CASCADE.

**Files Added:**
- `scripts/seed_screenshot_data.py`

---

## 2026-02-09 - Fix Web Horizontal Overflow

### Fix: Fix navbar causing horizontal overflow at all viewport widths

**Root cause:** DaisyUI's `navbar-start`/`navbar-center`/`navbar-end` pattern uses `width: 50%` for start and end, plus `flex-shrink: 0` for center. This totals >100% width, causing the navbar (and entire page body) to overflow horizontally.

**Navbar fix:**
- Replaced `navbar-start`/`navbar-center`/`navbar-end` with `flex-1`/`flex-none` layout
- `flex-1` gives the logo section flexible space, `flex-none` keeps nav links and logout at their natural size
- No more width overflow at any viewport size

**Safety net:**
- Added `overflow-x-hidden` to root app layout wrapper

**Regression test:**
- Added `responsiveness.spec.ts` E2E test that checks `scrollWidth <= clientWidth` (no horizontal overflow) at 10 viewport widths (375–1440px) across login, app, history, and settings pages

**Files Modified:**
- `frontend/src/lib/components/Navbar.svelte`
- `frontend/src/routes/app/+layout.svelte`

**Files Added:**
- `frontend/tests/e2e/responsiveness.spec.ts`

---

## 2026-02-09 - iOS Brand Colors Round 2

### Fix: Replace remaining hardcoded colors and improve touch targets on iOS

**IntegrationSetupView:**
- Replaced `.green` with `Color.selkoSuccess` for connected state icon and checkmark
- Removed `.controlSize(.small)` from Connect button for 44pt touch target

**SenderGroupView:**
- Replaced `.tint(.green)` with `.tint(.accentColor)` on Approve All button (brand blue)
- Removed `.controlSize(.mini)` for 44pt touch target
- Added `accessibilityLabel("Approve all events from this sender")`

**EventDetailView:**
- Replaced `.foregroundStyle(.red)` with `Color.selkoError` on Reject button
- Replaced `.tint(.green)` with `.tint(.accentColor)` on Approve button (brand blue)

**SettingsView:**
- Replaced `.green` with `Color.selkoSuccess` for status text and checkmark icon
- Added `accessibilityLabel("Connected")` to checkmark icon
- Added `accessibilityLabel("Connect <provider>")` to Connect buttons

**HistoryView:**
- Removed `.controlSize(.mini)` from Retry and Undo buttons for 44pt touch targets
- Replaced `.gray` with `Color.secondary` for cancelled status icon

**Files Modified:**
- `ios/Selko/Features/Review/Views/IntegrationSetupView.swift`
- `ios/Selko/Features/Review/Views/SenderGroupView.swift`
- `ios/Selko/Features/Review/Views/EventDetailView.swift`
- `ios/Selko/Features/Settings/Views/SettingsView.swift`
- `ios/Selko/Features/History/Views/HistoryView.swift`

---

## 2026-02-09 - Android Semantic Colors Round 2

### Fix: Replace hardcoded color and improve content descriptions on Android

**HistoryScreen:**
- Replaced hardcoded `Color(0xFF4CAF50)` with theme-aware `SelkoSuccess`/`SelkoSuccessDark` for synced status icon

**EventCardContent:**
- Added `contentDescription = "Event time"` to Schedule icon
- Added `contentDescription = "Event location"` to LocationOn icon
- Improved expand/collapse icon descriptions: "Expand" -> "Expand description", "Collapse" -> "Collapse description"

**Files Modified:**
- `android/app/src/main/java/net/melisma/selko/ui/screens/history/HistoryScreen.kt`
- `android/app/src/main/java/net/melisma/selko/ui/screens/review/EventCardContent.kt`

---

## 2026-02-09 - Web Responsiveness Fix

### Fix: Fix navbar overflow and content clipping at ~1024px viewport

- Changed navbar breakpoint from `lg` (1024px) to `md` (768px) so nav links and logout appear earlier
- Updated BottomNav to hide at `md` breakpoint (matching navbar)
- Updated app layout bottom padding to match new breakpoint
- Removed exclamation mark from welcome heading ("Welcome to Selko!" -> "Welcome to Selko")

**Files Modified:**
- `frontend/src/lib/components/Navbar.svelte`
- `frontend/src/lib/components/BottomNav.svelte`
- `frontend/src/routes/app/+layout.svelte`
- `frontend/src/lib/components/IntegrationStatus.svelte`

---

## 2026-02-09 - iOS Accessibility and Brand Compliance

### Fix: Improve iOS accessibility (VoiceOver labels, touch targets, brand colors)

**Auth screens (LoginView, RegisterView):**
- Added `accessibilityLabel` to email, password, and confirm password fields for VoiceOver
- Added `accessibilityHint` to Sign up button (login) and register button
- Increased Sign up link touch target to 44pt minimum (was 51x18pt)

**HomeView:**
- Added `accessibilityLabel("Welcome")` to hand wave emoji image
- Changed "Sign Out" to "Log out" per brand guide

**HistoryView:**
- Added `accessibilityLabel` to all status icons (Approved, Synced, Sync failed, Rejected, Cancelled, Pending)
- Replaced system colors with brand semantic colors: `.blue` -> `Color.accentColor`, `.green` -> `Color.selkoSuccess`, `.orange` -> `Color.selkoWarning`, `.red` -> `Color.selkoError`

**EventDetailView:**
- Changed corner radius from 8/12 to 2 on source quote box and source card (brand spec)

**IntegrationSetupView:**
- Changed corner radius from 12 to 2 on integration cards (brand spec)

**SettingsView:**
- Changed "Sign Out" to "Log out" per brand guide

**ReviewQueueView:**
- Added `accessibilityLabel` to swipe action buttons (Approve event, Reject event)

**EventCardView:**
- Added `accessibilityHint("Double tap to view details")` to event cards

**SettingsUITests:**
- Updated test to match renamed "Log out" button text

**Files Modified:**
- `ios/Selko/Features/Auth/Views/LoginView.swift`
- `ios/Selko/Features/Auth/Views/RegisterView.swift`
- `ios/Selko/Features/Home/Views/HomeView.swift`
- `ios/Selko/Features/History/Views/HistoryView.swift`
- `ios/Selko/Features/Review/Views/EventDetailView.swift`
- `ios/Selko/Features/Review/Views/IntegrationSetupView.swift`
- `ios/Selko/Features/Review/Views/ReviewQueueView.swift`
- `ios/Selko/Features/Review/Views/EventCardView.swift`
- `ios/Selko/Features/Settings/Views/SettingsView.swift`
- `ios/SelkoUITests/SettingsUITests.swift`

---

## 2026-02-09 - Android Accessibility and Brand Compliance

### Fix: Improve Android accessibility (content descriptions, button shapes, brand compliance)

**Button Shapes (all screens):**
- Added explicit `shape = MaterialTheme.shapes.medium` to all `Button`, `OutlinedButton`, `FilledTonalButton`, and `TextButton` composables. Material3 buttons default to pill shape (`ShapeKeyTokens.CornerFull`) which bypasses `MaterialTheme.shapes`, so explicit shapes are required for the 2dp brand corners.

**OutlinedTextField Shapes (all screens):**
- Added explicit `shape = MaterialTheme.shapes.small` to all `OutlinedTextField` composables for consistent 2dp brand corners.

**Icon Content Descriptions (accessibility):**
- EventDetailScreen: Reject/Approve button icons, source email icon
- EventCardContent: Reject/Approve button icons
- ReviewQueueScreen: Approve All icon, empty state Inbox icon
- IntegrationSetupContent: Email setup icon
- SettingsScreen: Service icons (Gmail/Calendar), Person icon, Log out icon
- HistoryScreen: Empty state History icon

**Terminology:**
- Changed "Sign Out" to "Log out" in SettingsScreen and HomeScreen (brand guide compliance)
- Updated corresponding UI test assertions

**Files Modified:**
- `android/app/src/main/java/net/melisma/selko/ui/screens/auth/AuthScreen.kt`
- `android/app/src/main/java/net/melisma/selko/ui/screens/review/ReviewQueueScreen.kt`
- `android/app/src/main/java/net/melisma/selko/ui/screens/review/EventCardContent.kt`
- `android/app/src/main/java/net/melisma/selko/ui/screens/review/EventDetailScreen.kt`
- `android/app/src/main/java/net/melisma/selko/ui/screens/review/IntegrationSetupContent.kt`
- `android/app/src/main/java/net/melisma/selko/ui/screens/settings/SettingsScreen.kt`
- `android/app/src/main/java/net/melisma/selko/ui/screens/history/HistoryScreen.kt`
- `android/app/src/main/java/net/melisma/selko/ui/screens/home/HomeScreen.kt`
- `android/app/src/androidTest/java/net/melisma/selko/ui/screens/home/HomeScreenTest.kt`
- `android/app/src/androidTest/java/net/melisma/selko/ui/screens/settings/SettingsScreenTest.kt`

**Note:** Date/time picker dialogs for EventDetailScreen are a follow-up item.

---

## 2026-02-09 - Web Accessibility Improvements

### Fix: Improve web accessibility (ARIA labels, roles, landmarks, heading hierarchy)

**Login page (`login/+page.svelte`):**
- Added `role="alert"` and `aria-live="polite"` to error alert
- Added `aria-busy` to submit button during loading
- Added `aria-hidden="true"` and sr-only text to loading spinner

**Register page (`register/+page.svelte`):**
- Added `role="alert"` and `aria-live="polite"` to error and success alerts
- Added `aria-invalid` and `aria-describedby` to inputs when validation fails
- Added `aria-busy` to submit button during loading
- Added sr-only text for loading spinner

**App home page (`app/+page.svelte`):**
- Added `<title>Home - Selko</title>` page title
- Added `role="alert"` and `aria-live="polite"` to error alert
- Added `aria-busy` and sr-only text to loading regions

**Navbar (`Navbar.svelte`):**
- Added `aria-label="Main navigation"` to nav element
- Added `aria-current="page"` to active navigation link
- Changed "Logout" to "Log out" per brand guide

**BottomNav (`BottomNav.svelte`):**
- Wrapped navigation in `<nav aria-label="Main navigation">`
- Added `aria-current="page"` to active link
- Added `aria-hidden="true"` to decorative SVG icons

**EventCard (`EventCard.svelte`):**
- Added `aria-expanded` to description toggle button

**ConfirmModal (`ConfirmModal.svelte`):**
- Added `aria-labelledby` pointing to title element
- Added `aria-describedby` pointing to description element

**Root layout (`+layout.svelte`):**
- Added skip-to-content link for keyboard navigation

**App layout (`app/+layout.svelte`):**
- Added `id="main-content"` to main element for skip link target
- Added `aria-busy` and sr-only text to loading spinner

**SenderHeader (`SenderHeader.svelte`):**
- Added descriptive `aria-label` to "Approve All" button

**EmailHeader (`EmailHeader.svelte`):**
- Added descriptive `aria-label` to "Approve All" button

**StatusBadge (`StatusBadge.svelte`):**
- Added `role="status"` to badge element

**Settings page (`app/settings/+page.svelte`):**
- Changed "Logout" to "Log out" per brand guide (mobile logout button)

**Files Modified:**
- `frontend/src/routes/login/+page.svelte`
- `frontend/src/routes/register/+page.svelte`
- `frontend/src/routes/app/+page.svelte`
- `frontend/src/routes/app/+layout.svelte`
- `frontend/src/routes/+layout.svelte`
- `frontend/src/lib/components/Navbar.svelte`
- `frontend/src/lib/components/BottomNav.svelte`
- `frontend/src/lib/components/EventCard.svelte`
- `frontend/src/lib/components/ConfirmModal.svelte`
- `frontend/src/lib/components/SenderHeader.svelte`
- `frontend/src/lib/components/EmailHeader.svelte`
- `frontend/src/lib/components/StatusBadge.svelte`
- `frontend/src/routes/app/settings/+page.svelte`

---

## 2026-02-09 - Android Auth Accessibility Fix

### Fix: Add confirm password field and brand corners on Android

**AuthViewModel.kt:**
- Added `confirmPassword` field to `AuthUiState`
- Added `onConfirmPasswordChange()` function that updates state and clears errors
- Updated `toggleAuthMode()` to clear confirm password when switching modes
- Added sign-up validation: checks confirm password is not blank and matches password

**AuthScreen.kt:**
- Added conditional "Confirm password" `OutlinedTextField` (shown only in sign-up mode)
- Password field `imeAction` is now dynamic: `Next` in sign-up mode, `Done` in sign-in mode

**Theme.kt:**
- Added `SelkoShapes` with 2dp `RoundedCornerShape` for all Material3 shape sizes
- Passed `shapes = SelkoShapes` to `MaterialTheme` — all components now use brand-spec 2dp corners

**Tests:**
- 6 new unit tests in `AuthViewModelTest.kt` (confirm password state, validation, error clearing)
- 4 new UI tests in `AuthScreenTest.kt` (confirm password field visibility, validation, error clearing)

**Files Modified:**
- `android/app/src/main/java/net/melisma/selko/ui/screens/auth/AuthViewModel.kt`
- `android/app/src/main/java/net/melisma/selko/ui/screens/auth/AuthScreen.kt`
- `android/app/src/main/java/net/melisma/selko/ui/theme/Theme.kt`
- `android/app/src/test/java/net/melisma/selko/ui/screens/auth/AuthViewModelTest.kt`
- `android/app/src/androidTest/java/net/melisma/selko/ui/screens/auth/AuthScreenTest.kt`

---

## 2026-02-09 - Web Tagline Contrast Fix

### Fix: Improve tagline text contrast on login and register pages

Changed tagline "Clear your mind." opacity from `text-base-content/60` to `text-base-content/70` on both login and register pages. This aligns with the project's secondary text convention defined in `docs/ui/03-patterns-and-components.md`.

**Files Modified:**
- `frontend/src/routes/login/+page.svelte`
- `frontend/src/routes/register/+page.svelte`

---

## 2026-02-09 - iOS Auth Accessibility Fix

### Fix: Improve auth screen accessibility and usability on iOS

**LoginView.swift:**
- Added persistent labels above email and password fields (placeholder text now shows hints)
- Full-width Sign in button with 44pt minimum height and 2px rounded corners
- Better "Sign up" link: full sentence "Don't have an account? Sign up" with larger touch target
- Reduced excessive whitespace (removed 2 of 4 Spacer elements, spacing 24->20)
- Tagline contrast bumped from .secondary to .primary.opacity(0.7)

**RegisterView.swift:**
- Added persistent labels above all fields (Email, Password, Confirm password)
- Full-width Sign up button with 44pt minimum height and 2px rounded corners
- Tightened spacing to match LoginView (24->20)

**Files Modified:**
- `ios/Selko/Features/Auth/Views/LoginView.swift`
- `ios/Selko/Features/Auth/Views/RegisterView.swift`

---

## 2026-02-09 - iOS Brand Colors Fix

### Fix: Use asset catalog color sets instead of UIColor for brand colors

**Problem:** BrandColors.swift used UIColor initializers for adaptive light/dark colors, requiring UIKit. This broke the iOS build and went against the goal of staying within SwiftUI.

**Solution:** Defined SelkoSuccess, SelkoError, and SelkoWarning as color sets in the asset catalog (like AccentColor). Xcode auto-generates SwiftUI Color extensions via `ASSETCATALOG_COMPILER_GENERATE_SWIFT_ASSET_SYMBOL_EXTENSIONS`. BrandColors.swift now contains only documentation.

**Files Added:**
- `ios/Selko/Assets.xcassets/SelkoSuccess.colorset/Contents.json`
- `ios/Selko/Assets.xcassets/SelkoError.colorset/Contents.json`
- `ios/Selko/Assets.xcassets/SelkoWarning.colorset/Contents.json`

**Files Modified:**
- `ios/Selko/BrandColors.swift` — Removed UIColor code, now documentation-only

---

## 2026-02-09 - Android Brand Design System

### Feat: Implement Selko brand identity for Android

**Colors:**
- Full Material3 color scheme with Selko Blue primary (#5B63D3 light, #8B91D6 dark)
- Disabled dynamic color (Material You) — brand colors always used
- Semantic colors: success, error, warning for both light and dark themes
- Cool-toned neutral grays matching brand guide

**Typography:**
- Inter font family (Regular, Medium, SemiBold) bundled as resources
- All Material3 typography styles using Inter with brand type scale

**Auth Screen:**
- Added "Clear your mind." tagline on sign-in view
- Updated terminology: "Sign in" / "Sign up" (sentence case)
- Toggle text: "Log in" / "Sign up" links

**Files Added:**
- `android/app/src/main/res/font/inter_regular.ttf`
- `android/app/src/main/res/font/inter_medium.ttf`
- `android/app/src/main/res/font/inter_semibold.ttf`

**Files Modified:**
- `android/app/src/main/java/net/melisma/selko/ui/theme/Color.kt`
- `android/app/src/main/java/net/melisma/selko/ui/theme/Type.kt`
- `android/app/src/main/java/net/melisma/selko/ui/theme/Theme.kt`
- `android/app/src/main/java/net/melisma/selko/ui/screens/auth/AuthScreen.kt`

---

## 2026-02-09 - iOS Brand Design System

### Feat: Implement Selko brand identity for iOS

**Accent Color:**
- Set AccentColor to Selko Blue (#5B63D3 light, #8B91D6 dark) in asset catalog
- Supports automatic light/dark mode switching

**Brand Colors:**
- Created BrandColors.swift with semantic color extensions
- Colors: selkoPrimary, selkoSuccess, selkoError, selkoWarning
- Helper initializers for hex colors and light/dark adaptive colors

**Auth Screens Updated:**
- LoginView: tagline changed to "Clear your mind.", button to "Sign in", link to "Sign up"
- RegisterView: title to "Sign up", button to "Sign up", sentence case labels

**Files Added:**
- `ios/Selko/BrandColors.swift`

**Files Modified:**
- `ios/Selko/Assets.xcassets/AccentColor.colorset/Contents.json`
- `ios/Selko/Features/Auth/Views/LoginView.swift`
- `ios/Selko/Features/Auth/Views/RegisterView.swift`

---

## 2026-02-09 - Web Brand Design System

### Feat: Implement Selko brand design system for web frontend

**Brand Colors:**
- Custom DaisyUI themes `selko-light` and `selko-dark` replacing default themes
- Selko Blue primary (#5B63D3 light, #8B91D6 dark)
- Cool-toned neutral grays with blue undertone
- Semantic colors for success, error, warning, info

**Typography:**
- Inter font (400, 500, 600 weights) loaded from Google Fonts
- Applied as base font-family

**Visual System:**
- 2px border radius everywhere (buttons, inputs, cards, badges)
- System-preference dark mode detection via inline script
- Login card shadow: 0 1px 3px rgba(0,0,0,0.06)

**Auth Pages Restyled:**
- Login: "Selko" display heading + "Clear your mind." tagline + "Sign in" button
- Register: "Selko" display heading + "Clear your mind." tagline + "Sign up" button
- Removed "OR" divider from both pages
- Updated terminology: "Sign in", "Sign up", "Log in"

**Files Modified:**
- `frontend/tailwind.config.js` — Custom selko-light and selko-dark DaisyUI themes
- `frontend/src/app.css` — Inter font import and base font-family
- `frontend/src/app.html` — System theme detection script, selko-light default
- `frontend/src/routes/login/+page.svelte` — Brand styling and terminology
- `frontend/src/routes/register/+page.svelte` — Brand styling and terminology
- `frontend/src/routes/login/__tests__/page.test.js` — Updated for new terminology
- `frontend/tests/e2e/auth.spec.ts` — Updated for new terminology

---

## 2026-02-08 - iOS XCUITests

### Test: Add XCUITests and accessibility identifiers for iOS screens

**Accessibility Identifiers Added:**
- ReviewQueueView: reviewQueueLoading, integrationSetupView, emptyStateView, eventList
- EventCardView: eventCard, eventTitle
- EventDetailView: eventDetailTitle, rejectButton, approveButton
- HistoryView: historyLoading, historyEmptyState, historyList, undoButton, retryButton
- SettingsView: connectedAccountsSection, signOutButton

**XCUITest Files Added (4):**
- `ReviewQueueUITests.swift` — Loading state, navigation title, states detection
- `EventDetailUITests.swift` — Navigation structure
- `HistoryUITests.swift` — Tab navigation, empty state, navigation title
- `SettingsUITests.swift` — Tab navigation, sections display, sign out button

**Files Modified:**
- `ios/Selko/Features/Review/Views/ReviewQueueView.swift`
- `ios/Selko/Features/Review/Views/IntegrationSetupView.swift`
- `ios/Selko/Features/Review/Views/EventCardView.swift`
- `ios/Selko/Features/Review/Views/EventDetailView.swift`
- `ios/Selko/Features/History/Views/HistoryView.swift`
- `ios/Selko/Features/Settings/Views/SettingsView.swift`

**Files Added:**
- `ios/SelkoUITests/ReviewQueueUITests.swift`
- `ios/SelkoUITests/EventDetailUITests.swift`
- `ios/SelkoUITests/HistoryUITests.swift`
- `ios/SelkoUITests/SettingsUITests.swift`

---

## 2026-02-08 - Android Compose UI Tests

### Test: Add Compose UI tests for Android screens

**Test Files Added (4):**
- `ReviewQueueScreenTest.kt` — Loading indicator, empty state, integration setup display
- `EventDetailScreenTest.kt` — Top bar, back button, error for missing events
- `HistoryScreenTest.kt` — Empty state display, description text
- `SettingsScreenTest.kt` — Title, sections (Connected Accounts, Calendar Defaults, Account), sign out button, user email, integration rows

**Pattern:** Follows existing AuthScreenTest.kt pattern with createComposeRule(), MockK repositories, and onNodeWithText() assertions.

**Files Added:**
- `android/app/src/androidTest/java/net/melisma/selko/ui/screens/review/ReviewQueueScreenTest.kt`
- `android/app/src/androidTest/java/net/melisma/selko/ui/screens/review/EventDetailScreenTest.kt`
- `android/app/src/androidTest/java/net/melisma/selko/ui/screens/history/HistoryScreenTest.kt`
- `android/app/src/androidTest/java/net/melisma/selko/ui/screens/settings/SettingsScreenTest.kt`

---

## 2026-02-08 - Playwright E2E Tests

### Feat: Add Playwright E2E test suite for web frontend

**Setup:**
- Added `@playwright/test` to devDependencies
- Created `playwright.config.ts` with 5 browser/viewport projects (chromium, webkit, mobile-chrome, mobile-safari, tablet)
- Auth fixture for Supabase login reuse across tests
- Web server auto-start configuration

**Test Specs (6 files):**
- `auth.spec.ts` — Login form, register page, invalid credentials, form validation
- `navigation.spec.ts` — Desktop navbar, mobile bottom nav, auth guard, route navigation
- `review-queue.spec.ts` — Page loading, integration setup vs queue states
- `event-detail.spec.ts` — Non-existent event handling
- `history.spec.ts` — History page loading, empty state
- `settings.spec.ts` — Settings sections display

**Files Added:**
- `frontend/playwright.config.ts`
- `frontend/tests/e2e/auth.setup.ts`
- `frontend/tests/e2e/fixtures/auth.ts`
- `frontend/tests/e2e/auth.spec.ts`
- `frontend/tests/e2e/navigation.spec.ts`
- `frontend/tests/e2e/review-queue.spec.ts`
- `frontend/tests/e2e/event-detail.spec.ts`
- `frontend/tests/e2e/history.spec.ts`
- `frontend/tests/e2e/settings.spec.ts`
- `frontend/.gitignore`

**Files Modified:**
- `frontend/package.json` — Added test:e2e, test:e2e:ui, test:e2e:headed scripts

---

## 2026-02-08 - Fix CLI OAuth refresh token

### Fix: Force consent prompt in CLI OAuth flows

**Problem:** CLI OAuth tools (`cli_auth_gmail`, `cli_auth_gcal`) didn't pass `prompt="consent"` to Google's OAuth flow. On re-authentication, Google would reuse the existing grant without issuing a new refresh token, causing `refresh_token` to be `None`. This broke staging integration tests.

**Fix:** Added `prompt="consent"` to `flow.run_local_server()` in both `gmail.py:run_oauth_flow()` and `cli_auth_gcal.py:run_calendar_oauth_flow()`. This matches the web app's OAuth routes which already had this parameter.

**Files changed:**
- `backend/selko/services/gmail.py` — `run_oauth_flow()`
- `cli/cli_auth_gcal.py` — `run_calendar_oauth_flow()`

## 2026-02-08 - Backend Calendar Delete (Unsync)

### Feat: Add calendar event delete and unsync endpoint

**Problem:** Once an event was synced to Google Calendar, there was no way to remove it from the calendar and revert the event back to pending_review status for re-editing.

**Solution:** Added `delete_calendar_event()` service function and `POST /events/{event_id}/unsync` API endpoint.

**New Service Function:** `delete_calendar_event()`
- Deletes the event from Google Calendar using `events().delete()`
- Handles 404 gracefully (event already deleted from Google Calendar)
- Clears `google_calendar_event_id` and `synced_at` fields
- Reverts event status to `pending_review`
- Logs the deletion to `calendar_sync_log` with action="deleted"

**New API Endpoint:** `POST /events/{event_id}/unsync`
- Validates event exists, belongs to user, and is in `synced` status
- Returns 400 if event is not synced, 403 if not authorized, 404 if not found
- Returns `EventUnsyncResponse` with event_id and new status

**New Schema:** `EventUnsyncResponse`
- Fields: `event_id` (str), `status` (Literal["pending_review"])

**Tests Added:**
- 6 unit tests for `delete_calendar_event` (success, 404 graceful handling, no credentials, no google_event_id, sync logging, non-404 API error)
- 4 integration tests for `POST /events/{id}/unsync` (not found, auth required, not synced, wrong user)

**Files Changed:**
- `backend/selko/services/calendars.py` - Added `delete_calendar_event()`
- `backend/selko/api/routes/events.py` - Added `POST /{event_id}/unsync` endpoint
- `backend/selko/api/schemas/events.py` - Added `EventUnsyncResponse`
- `backend/tests/test_calendars.py` - Added `TestDeleteCalendarEvent` (6 tests)
- `backend/tests/integration/test_integration_api.py` - Added `TestEventUnsyncEndpoint` (4 tests)

---

## 2026-02-08 - Web Frontend UI Screens

### Feat: Implement web UI screens (Review Queue, Event Detail, History, Settings)

**New Screens:**
- **Review Queue** (`/app`): Rewritten to show pending events grouped by sender and email, with approve/reject actions. Shows integration setup mode when accounts not connected, empty state when caught up.
- **Event Detail** (`/app/events/[id]`): Side-by-side source email and editable event form. Auto-save on blur, approve/reject with calendar sync. Responsive layout (desktop grid, mobile stacked with collapsible source).
- **Activity History** (`/app/history`): Shows approved, synced, failed, rejected events grouped by date. Undo (back to pending) and retry (re-sync failed) actions. Paginated with Load More.
- **Settings** (`/app/settings`): Integration management with disconnect confirmation modals, calendar target selection, read-only account email, mobile logout button.

**New Shared Components:**
- `Navbar.svelte` - Desktop navigation with Selko brand, Review/History/Settings links, logout button
- `BottomNav.svelte` - Mobile bottom tab navigation with SVG icons
- `EmptyState.svelte` - Centered heading + description for empty lists
- `PageHeader.svelte` - Page title with optional back link and action slot
- `StatusBadge.svelte` - DaisyUI badge mapping for event and integration statuses
- `ConfirmModal.svelte` - DaisyUI dialog for destructive action confirmation
- `IntegrationStatus.svelte` - Setup and settings mode for Gmail/Calendar connections
- `SenderHeader.svelte` - Sender grouping header with "Approve All"
- `EmailHeader.svelte` - Email subject/date with "Approve All"
- `EventCard.svelte` - Event display with title, datetime, location, description toggle, approve/reject buttons

**App Layout:**
- `+layout.svelte` for `/app/*` routes with auth guard, navbar, bottom nav, page container
- Auth redirect to `/login` when not authenticated

**Service Layer Additions:**
- `fetchPendingEventsWithSources()` - Events with joined source email data for Review Queue grouping
- `fetchActivityEvents()` - Paginated activity history with status filters
- `disconnectIntegration()` - Delete an integration
- `getCalendarAuthUrl()` / `initiateCalendarAuth()` - Calendar OAuth flow

**Test Coverage:**
- 6 component test files: Navbar, BottomNav, EmptyState, StatusBadge, EventCard, IntegrationStatus
- 5 route test files: app layout, app page (review queue), events/[id], history, settings
- 7 new service tests for fetchPendingEventsWithSources and fetchActivityEvents
- All 179 tests passing

**Files Added:**
- `frontend/src/lib/components/` - 10 new Svelte components
- `frontend/src/routes/app/+layout.svelte` - App shell layout
- `frontend/src/routes/app/events/[id]/+page.svelte` - Event detail page
- `frontend/src/routes/app/history/+page.svelte` - Activity history page
- `frontend/src/routes/app/settings/+page.svelte` - Settings page
- Test files in `__tests__/` directories for all components and routes

**Files Modified:**
- `frontend/src/routes/app/+page.svelte` - Complete rewrite for Review Queue
- `frontend/src/lib/api/backend.js` - Added Calendar OAuth functions
- `frontend/src/lib/services/events.js` - Added fetchPendingEventsWithSources, fetchActivityEvents
- `frontend/src/lib/services/integrations.js` - Added disconnectIntegration
- `frontend/src/lib/services/index.js` - Added new exports
- `frontend/src/routes/app/__tests__/page.test.js` - Rewritten for new Review Queue

---

## 2026-02-08 - Android UI Screens

### Feat: Implement Android UI (Review Queue, Event Detail, History, Settings)

**New Screens:**
- **Review Queue** - Displays pending events grouped by sender email. Supports approve/reject individual events and approve-all for a sender group. Shows integration setup prompt when Gmail/Calendar not connected.
- **Event Detail** - Full event editor with source email display, editable form fields (title, datetime, location, description, all-day toggle), and approve/reject from bottom bar.
- **Activity History** - Shows non-pending events (approved, synced, rejected, cancelled, sync_failed) grouped by date. Supports undo (back to pending_review) and retry (for sync failures). Paginated with "Load More".
- **Settings** - Connected accounts management (Gmail, Google Calendar), calendar defaults (target calendar picker, default invitees), and sign-out.

**Navigation:**
- Material3 bottom navigation bar with Review, History, Settings tabs
- MainScaffold wraps tab navigation with nested NavHost
- EventDetail navigated from parent NavHost (full-screen overlay)

**New Repository:**
- `CalendarSettingsRepository` - Read/write `user_calendar_settings` table for target calendar and default invitees

**Repository Additions:**
- `EventRepository.fetchPendingEventsWithSources()` - Fetch pending events with joined event_sources and emails
- `EventRepository.fetchActivityEvents()` - Fetch non-pending events with pagination
- `BackendApiClient.getCalendarAuthUrl()` - Google Calendar OAuth URL

**New ViewModels:**
- `ReviewQueueViewModel` - Integration checking, event grouping by sender, approve/reject
- `EventDetailViewModel` - Event loading, form editing, save/approve/reject
- `HistoryViewModel` - Paginated history with date grouping, undo/retry
- `SettingsViewModel` - Integration management, calendar settings, sign-out

**Files Added:**
- `android/app/src/main/java/net/melisma/selko/data/repository/CalendarSettingsRepository.kt`
- `android/app/src/main/java/net/melisma/selko/ui/components/SelkoBottomNavigation.kt`
- `android/app/src/main/java/net/melisma/selko/ui/navigation/MainScaffold.kt`
- `android/app/src/main/java/net/melisma/selko/ui/screens/review/ReviewQueueViewModel.kt`
- `android/app/src/main/java/net/melisma/selko/ui/screens/review/ReviewQueueScreen.kt`
- `android/app/src/main/java/net/melisma/selko/ui/screens/review/IntegrationSetupContent.kt`
- `android/app/src/main/java/net/melisma/selko/ui/screens/review/EventCardContent.kt`
- `android/app/src/main/java/net/melisma/selko/ui/screens/review/EventDetailViewModel.kt`
- `android/app/src/main/java/net/melisma/selko/ui/screens/review/EventDetailScreen.kt`
- `android/app/src/main/java/net/melisma/selko/ui/screens/history/HistoryViewModel.kt`
- `android/app/src/main/java/net/melisma/selko/ui/screens/history/HistoryScreen.kt`
- `android/app/src/main/java/net/melisma/selko/ui/screens/settings/SettingsViewModel.kt`
- `android/app/src/main/java/net/melisma/selko/ui/screens/settings/SettingsScreen.kt`

**Files Modified:**
- `android/app/src/main/java/net/melisma/selko/data/repository/EventRepository.kt` - Added 2 methods
- `android/app/src/main/java/net/melisma/selko/data/api/BackendApiClient.kt` - Added getCalendarAuthUrl
- `android/app/src/main/java/net/melisma/selko/ui/navigation/NavRoutes.kt` - Added Review, History, Settings, EventDetail routes
- `android/app/src/main/java/net/melisma/selko/ui/navigation/SelkoNavHost.kt` - Replaced Home with MainScaffold, added EventDetail route
- `android/app/src/main/java/net/melisma/selko/di/AppModule.kt` - Registered new repositories and ViewModels

---

## 2026-02-08 - iOS UI Screens

### Feat: Implement iOS UI screens (Review Queue, Event Detail, History, Settings)

**TabView Navigation:**
- Added `MainTabView` with three tabs: Review, History, Settings
- Updated `SelkoApp.swift` to show `MainTabView` instead of `HomeView` when authenticated

**Review Queue:**
- `ReviewQueueView` displays pending events grouped by sender email
- `IntegrationSetupView` shown when Gmail or Google Calendar are not connected, with Connect buttons
- `SenderGroupView` shows sender name/email with "Approve All" button for batch approval
- `EventCardView` displays event title, date/time, location with swipe-to-approve/reject
- `ReviewQueueViewModel` handles loading integrations, fetching pending events with sources, grouping, and approve/reject actions

**Event Detail:**
- `EventDetailView` with adaptive layout: side-by-side on iPad (source email + form), stacked on iPhone
- Editable form fields: title, all-day toggle, date/time pickers, location, description
- Auto-save with 1-second debounce on field changes
- Source email display with sender info, subject, and extracted quote
- Toolbar actions for Approve and Reject

**Activity History:**
- `HistoryView` shows non-pending events grouped by date (Today, Yesterday, older dates)
- Status icons and descriptions for approved, synced, sync_failed, rejected, cancelled
- Undo button to revert events back to pending_review
- Retry button for sync failures
- Pagination with "Load More" button

**Settings:**
- `SettingsView` with Connected Accounts, Calendar Defaults, and Account sections
- Integration status display with Connect/Disconnect actions
- Calendar picker for default calendar selection
- Sign Out button
- `CalendarSettingsService` for managing `user_calendar_settings` Supabase table

**Service Additions:**
- `EventService`: Added `fetchPendingEventsWithSources()` and `fetchActivityEvents(limit:offset:)`
- `BackendAPI`: Added `getCalendarAuthUrl(redirectUri:)` for Google Calendar OAuth
- `DependencyContainer`: Added `calendarSettingsService`

**Files Added:**
- `ios/Selko/Navigation/MainTabView.swift`
- `ios/Selko/Features/Review/ViewModels/ReviewQueueViewModel.swift`
- `ios/Selko/Features/Review/ViewModels/EventDetailViewModel.swift`
- `ios/Selko/Features/Review/Views/ReviewQueueView.swift`
- `ios/Selko/Features/Review/Views/IntegrationSetupView.swift`
- `ios/Selko/Features/Review/Views/SenderGroupView.swift`
- `ios/Selko/Features/Review/Views/EventCardView.swift`
- `ios/Selko/Features/Review/Views/EventDetailView.swift`
- `ios/Selko/Features/History/ViewModels/HistoryViewModel.swift`
- `ios/Selko/Features/History/Views/HistoryView.swift`
- `ios/Selko/Features/Settings/ViewModels/SettingsViewModel.swift`
- `ios/Selko/Features/Settings/Views/SettingsView.swift`
- `ios/Selko/Features/Settings/Services/CalendarSettingsService.swift`

**Files Modified:**
- `ios/Selko/SelkoApp.swift` - Show `MainTabView` instead of `HomeView`
- `ios/Selko/Features/Events/Services/EventService.swift` - Added two new methods
- `ios/Selko/Core/API/BackendAPI.swift` - Added `getCalendarAuthUrl`
- `ios/Selko/Core/DI/DependencyContainer.swift` - Added `calendarSettingsService`

---

## 2026-01-30 (30) - OAuth Redirect Port Fix

### Fix: Use fixed port for CLI OAuth redirect

**Problem:** CLI OAuth flows (`cli_auth_gmail`, `cli_auth_gcal`) used `port=0` (random port) for the local redirect server. This works with Desktop OAuth clients but fails with Web OAuth clients because Web clients require exact redirect URI matches including port.

**Solution:** Changed both CLI OAuth flows to use fixed port 8080:
- `http://localhost:8080` is now the redirect URI for CLI OAuth flows
- Users must add `http://localhost:8080` to their Web OAuth client's authorized redirect URIs in GCP Console

**Files Changed:**
- `backend/selko/services/gmail.py` - Fixed `run_oauth_flow()` to use port 8080
- `cli/cli_auth_gcal.py` - Fixed `run_calendar_oauth_flow()` to use port 8080

---

## 2026-01-30 (30)

### Fix: Add missing LLM call logging database migration

**Problem:** PR #17 (Unified LLM Gateway) merged the Python code for `LLMLoggingService` but forgot to include the database migration from PR #16. The logging service was silently failing because the `llm_call_log` table didn't exist.

**Solution:** Added the missing migration and integration tests.

**New Database Table:** `llm_call_log`
- Stores all LLM API calls with full prompt and response text
- Tracks operation type (extract_events, compare_events, merge_events)
- Records timing (started_at, completed_at, latency_ms)
- Tracks token usage (prompt_tokens, completion_tokens, total_tokens)
- Estimates cost based on Gemini pricing
- Links to source email when applicable
- Stores error details for failed calls

**New SQL Function:** `get_llm_usage_summary(user_id, start_date, end_date)`
- Returns aggregated usage statistics for a user

**RLS Policies:**
- Users can view their own LLM call history
- Service role can write logs (bypasses RLS for backend writes)

**Files Added:**
- `supabase/migrations/20260130000001_create_llm_call_log.sql` - Database migration
- `backend/tests/integration/test_llm_logging.py` - 316 lines of integration tests

---

## 2026-01-28 (28)

### Remove credentials.json dependency

**Problem:** OAuth client credentials were stored in `cli/credentials.json` file, separate from the `.env` files where other credentials are stored. This led to confusion and stale credentials causing "unauthorized_client" errors during token refresh.

**Solution:** Removed `credentials.json` entirely. OAuth flows now use `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` from `.env` files, matching all other credential storage.

**Files Changed:**
- `backend/selko/config.py` - Removed `credentials_file` field
- `backend/selko/services/gmail.py` - Use `config.google_client_id/secret` instead of file
- `backend/selko/services/integrations.py` - Use `config.google_client_id/secret` for OAuth flows
- `cli/cli_auth_gcal.py` - Use `config.google_client_id/secret` instead of file
- `docs/testing-guide.md` - Updated token refresh instructions

---

### Unified LLM Gateway

**Problem:** LLM call concerns (rate limiting, retries, logging, error handling) were scattered across multiple modules. Each function in `gemini.py` had its own timing, retry logic, and error handling. Adding logging or quotas required modifying every function.

**Solution:** Created `LLMGateway` class that centralizes all LLM execution concerns while keeping prompts in their domain-specific locations.

**Key Features:**
- **Per-call rate limiting**: Every LLM call checks user quota before execution
- **Automatic retry with exponential backoff**: Rate limit errors (429) trigger automatic retry
- **Unified logging**: All calls logged with operation type, timing, token counts, and cost estimates
- **Error classification**: Errors categorized (rate_limit, api_error, timeout, invalid_response)
- **Method chaining**: `gateway.for_user(id).for_email(id)` for context

**Architecture:**
- Gateway created per-request via FastAPI dependency injection
- Callers use gateway directly (no wrapper functions)
- Prompts stay in gemini.py - gateway only handles execution
- Workers don't enforce quotas (that's done at API level)

**Files Changed:**
- `backend/selko/services/llm_gateway.py` - **New** gateway class
- `backend/selko/services/llm_logging.py` - **New** logging service with cost estimation
- `backend/selko/services/gemini.py` - Simplified to use gateway
- `backend/selko/services/events.py` - Accept gateway parameter
- `backend/selko/api/deps.py` - Added `get_llm_gateway()` dependency
- `backend/selko/api/routes/emails.py` - Inject gateway
- `backend/selko/workers/email_process.py` - Create gateway with logging
- `cli/cli_process_emails.py` - Create gateway
- `backend/tests/test_llm_gateway.py` - **New** 21 unit tests
- `backend/tests/test_gemini.py` - Updated for gateway API

---

## 2026-01-27 (27)

### Docker Layer Caching for CI

**Problem:** The `supabase start` command in CI takes ~182 seconds, primarily due to Docker image pulls. While path filtering (implemented in entry 26) skips this for non-backend changes, backend/supabase PRs still pay this cost.

**Solution:** Added `actions/cache@v4` to cache `/var/lib/docker` between CI runs. Cache key is based on `supabase/config.toml` to invalidate when Supabase configuration changes.

**Expected Behavior:**
- First run after cache miss: Full 182 seconds (builds cache)
- Subsequent runs with cache hit: 10-30 seconds faster (skipped image pulls)
- Cache invalidates when `supabase/config.toml` changes

**Caveats:**
- GitHub's 5 GB cache limit may cause eviction on busy repos
- Cache upload adds overhead but happens in parallel with other steps

**Files Changed:**
- `.github/workflows/test.yml` - Added Docker layer cache step before `supabase start`

---

## 2026-01-27 (26)

### CI Path Filtering Optimization

**Problem:** CI runs all tests on every push, even for documentation-only changes. Integration tests take 4+ minutes due to Supabase startup (182 seconds).

**Solution:** Expanded `dorny/paths-filter` to detect backend, supabase, and android changes. Jobs now only run when relevant files change.

**Path Filters:**
- `backend`: `backend/**`, `cli/**`, `pyproject.toml`, `uv.lock`
- `supabase`: `supabase/**`
- `android`: `android/**`

**Conditional Jobs:**
- **Unit Tests**: Only run when backend files change
- **Integration Tests**: Only run when backend OR supabase files change
- **Android Tests**: Only run when android files change (removed `|| github.event_name == 'push'` that defeated filtering)
- **Deploy Staging**: Only run when backend OR supabase files change

**Expected Behavior:**
- Markdown-only PR → No test jobs run (fast)
- Backend-only PR → Unit tests + integration tests (skips Android)
- Android-only PR → Android tests only (skips Supabase startup)
- Supabase-only PR → Integration tests only

**Files Changed:**
- `.github/workflows/test.yml` - Added path filters and job conditions

---

## 2026-01-27 (25)

### Consolidate Google OAuth Callbacks + Fix Error Handling

**Problem 1:** Separate OAuth callback endpoints (`/gmail/callback`, `/google_calendar/callback`) required duplicate code and multiple redirect URIs in Google Cloud Console.

**Solution 1:** Unified all Google OAuth callbacks to a single endpoint (`/integrations/google/callback`). The provider is determined from the `state` parameter that already tracked which provider initiated the flow.

**Problem 2:** `google.auth.exceptions.RefreshError` was not caught in Gmail service, causing unhandled exceptions that bypassed error handling and CORS middleware.

**Solution 2:** Catch `RefreshError` in `get_user_profile()` and `fetch_messages()` and convert to `GmailError`. Email sync endpoint now returns 401 for expired/revoked credentials.

**Changes:**
- Renamed `/integrations/gmail/callback` → `/integrations/google/callback`
- Added `/integrations/calendar/auth` endpoint for Google Calendar OAuth initiation
- Updated `ALLOWED_REDIRECT_PATHS` to only allow the unified callback path
- Fixed `gmail.py` to catch `RefreshError` and convert to `GmailError`
- Fixed `emails.py` to return 401 for expired/revoked Gmail credentials
- Updated documentation to reflect the new endpoint structure

**Files Changed:**
- `backend/selko/api/routes/integrations.py` - Unified callback, added calendar auth
- `backend/selko/api/routes/emails.py` - Return 401 for expired credentials
- `backend/selko/services/gmail.py` - Catch RefreshError in API calls
- `backend/tests/integration/test_integration_api.py` - Updated callback URLs, added calendar auth tests
- `backend/tests/integration/test_rate_limiting.py` - Updated callback URL
- `docs/api-workflow.md` - Updated endpoint documentation
- `docs/supabase-frontend-queries.md` - Updated endpoint documentation

**Google Cloud Console:** Update authorized redirect URIs:
- Remove: `*/integrations/gmail/callback`, `*/integrations/google_calendar/callback`
- Add: `http://localhost:8000/integrations/google/callback`, `https://selko.onrender.com/integrations/google/callback`

---

## 2026-01-27 (24)

### Fix CI Polling to Handle Failures

**Problem:** The documented `while ! gh pr checks; do sleep 10; done` pattern loops forever if CI fails because `gh pr checks` returns non-zero for both pending (exit 8) and failed (exit 1) states.

**Solution:** Replace with a loop that checks exit codes:
- Exit 0 → checks passed → merge PR
- Exit 8 → checks pending → keep polling
- Any other code → checks failed → stop with error

**Files Changed:**
- `CLAUDE.md` - Updated polling pattern (4 locations)
- `docs/parallel-agents.md` - Updated polling pattern (4 locations)
- `docs/ci-cd.md` - Updated polling pattern (3 locations)
- `.claude/hooks/block-interactive-commands.sh` - Updated suggested alternative

---

## 2026-01-27 (23)

### CI Speed Optimization

**Optimizations:**
- Skip Android tests on backend-only PRs using `dorny/paths-filter`
- Add parallel test execution with `pytest-xdist` for unit tests only
- Integration tests run sequentially (shared DB state prevents parallelization)

**Fixes Required:**
- Added `contents: read` permission (required for checkout when permissions block exists)
- Added `pull-requests: read` permission (required for paths-filter to access PR files)
- Explicitly install pytest-xdist (workspace structure prevented automatic install)

**Expected Savings:**
- Backend-only PR: ~1.5 min saved (no Android tests)
- Unit tests: ~30% faster (parallel execution)

**Files Changed:**
- `.github/workflows/test.yml` - Path filter, permissions, parallel unit tests
- `backend/pyproject.toml` - Added `pytest-xdist>=3.0`
- `CLAUDE.md` - Reduced CI polling interval from 30s to 10s

---

## 2026-01-27 (22)

### Reset Stale Jobs on Startup

**Problem:** When the API server crashes or is killed while jobs are in-progress, those jobs remain "locked" until their lock expires. This delays reprocessing by the lock timeout duration.

**Solution:** On startup, immediately call the existing `unlock_expired_*` functions to recover any stale jobs from a previous instance crash.

**Why It's Safe:**
- All job types are idempotent (upsert-based, no duplicates)
- Unlock functions already exist and are tested
- Only resets jobs where `locked_until < now()` (truly stale)

**Files Changed:**
- `backend/selko/api/app.py` - Added stale job recovery after worker pool starts

**Log Output:**
```
INFO: Recovered stale jobs on startup: 2 emails, 1 events, 0 tasks
```
(Only logs if any jobs were recovered)

---

## 2026-01-27 (21)

### Block Interactive Commands in Claude Code

**Problem:** `gh pr checks --watch` is an interactive command that Claude Code cannot parse properly. The output stream causes the agent to hang or produce unparsable results.

**Solution:**
- Created PreToolUse hook to block `gh pr checks --watch` commands
- Updated CLAUDE.md to use polling approach instead: `while ! gh pr checks; do sleep 30; done`
- Added "Blocked Commands" section documenting blocked commands and alternatives

**Files Changed:**
- `.claude/hooks/block-interactive-commands.sh` - New hook script
- `.claude/settings.json` - Added Bash hook matcher
- `CLAUDE.md` - Updated commands and added blocked commands section

---

## 2026-01-27 (20)

### Replace Job Queue with Status-Based Workers

**Architectural Change:** Replaced the `jobs` table with status-based workers that poll data tables directly. The data tables ARE the queue.

**Why:**
- Single source of truth (no job-data synchronization bugs)
- Simpler debugging (query data tables directly to see pending work)
- Natural idempotency (data state is always consistent)

**Before:** `jobs` table → worker claims job → fetches data → updates both job and data
**After:** Worker claims data via status → processes → updates data

**Database Changes:**
- Added claiming columns to `emails`: `locked_until`, `locked_by`, `attempts`, `max_attempts`
- Added sync tracking columns to `events`: `locked_until`, `locked_by`, `sync_attempts`, `max_sync_attempts`, `sync_error`
- Added `syncing` status to events for in-progress calendar sync
- Created atomic claiming RPC functions: `claim_unprocessed_email()`, `claim_approved_event()`, `unlock_expired_email_locks()`, `unlock_expired_event_locks()`
- Dropped `jobs` table entirely
- Created `scheduled_tasks` table for periodic tasks only (email_fetch)

**Service Changes:**
- Deleted `backend/selko/services/jobs.py`
- Created `backend/selko/services/scheduled_tasks.py` for periodic tasks
- Added claiming functions to `emails.py`: `claim_pending_email()`, `complete_email_processing()`, `fail_email_processing()`
- Added claiming functions to `events.py`: `claim_approved_event_for_sync()`, `complete_event_sync()`, `fail_event_sync()`

**Worker Changes:**
- `pool.py`: Polls three sources: scheduled_tasks, pending emails, approved events
- `email_process.py`: Receives full email record (not job payload)
- `calendar_sync.py`: Receives full event record (not job payload)
- `email_fetch.py`: Removed job enqueueing (emails auto-picked up by status)

**Data Flow:**
```
Cron (5 min) -> scheduled_tasks -> emails (status=pending)
                                   -> Worker claims -> LLM -> events (status=pending_review)
User approves -> status=approved -> Worker claims -> Calendar API -> status=synced
```

---

## 2026-01-27 (19)

### CI Fixes and Documentation Updates

**Bug Fixes:**
- Fixed pre-commit hook to work correctly in git worktrees
  - Changed PROJECT_ROOT detection to use `git rev-parse --show-toplevel`
  - Fixed pytest cache detection to check `nodeids` file (created on every run) instead of only `lastfailed` (only created when tests fail)
- Added missing INSERT RLS policy for `calendar_sync_log` table
  - Sync operations can now write audit log entries
- Added `pytest-asyncio` dependency and `asyncio_mode = "auto"` config
  - Async worker tests now run correctly

**Documentation:**
- Updated workflow documentation to use manual merge (auto-merge requires GitHub Pro)
  - Use `gh pr checks --watch && gh pr merge --squash` instead of `gh pr merge --auto --squash`
  - Added explicit cleanup steps for AI agents after PR merge
- Removed PLAN5.md (auto-merge issue resolved by documentation update)

---

## 2026-01-27 (18)

### Opt-in Background Processing

**Change:** Background processing (worker pool + APScheduler) is now OFF by default and requires explicit opt-in.

**Why:** Allows running the API without background workers for development, testing, or lightweight deployments where automatic email fetching isn't needed.

**Configuration:**
- New environment variable: `ENABLE_BACKGROUND_PROCESSING`
- Default: `false` (disabled)
- Set to `true` to enable automatic email fetching and job processing

**Files Changed:**
- `backend/selko/config.py` - Added `enable_background_processing` config field
- `backend/selko/api/app.py` - Conditional startup of workers and scheduler
- `.env.example` - Documented the new variable
- `.env.production` - Enabled for production deployments

**Usage:**
```bash
# Development (background processing disabled by default)
uv run python -m selko.api

# Production or when you want background workers
ENABLE_BACKGROUND_PROCESSING=true uv run python -m selko.api
```

**Note:** CLI tools (`cli_fetch_emails`, `cli_process_emails`) continue to work regardless of this setting since they don't depend on background workers.

---

## 2026-01-27 (17)

### LLM Evaluation Framework Improvements

**New Features:**
- `--dry-run` flag for fixture validation without LLM calls
  - Validates JSON structure (required fields: `input`, `expected`, `events_found`)
  - Checks that referenced attachments exist
  - Reports validation errors for invalid fixtures
- Thread scenario evaluation (`--threads`)
  - Processes multi-email sequences in order
  - Tracks event state across emails in a thread
  - Compares final state against expected outcome
- Configurable model via `SELKO_EVAL_MODEL` environment variable
  - Default remains `gemini-3-flash-preview`
  - Override with e.g. `SELKO_EVAL_MODEL=gemini-2.0-flash`

**Usage Examples:**
```bash
# Validate all fixtures without LLM calls
uv run python -m backend.tests.eval.run_eval --all --dry-run

# Run thread scenario evaluation
uv run python -m backend.tests.eval.run_eval --threads --dry-run

# Use different model
SELKO_EVAL_MODEL=gemini-2.0-flash uv run python -m backend.tests.eval.run_eval --all
```

---

## 2026-01-27 (16)

### Email-to-Calendar Manual CLI Walkthrough

**Purpose:** Create CLI tool for processing emails into saved events and comprehensive walkthrough documentation for the email-to-calendar flow.

**New CLI Tool:** `cli_process_emails`
- Process emails through the LLM to extract calendar events
- `--recent N`: Process N most recent unprocessed emails
- `--email-id ID`: Process a specific email by ID
- `--all`: Process all unprocessed emails
- Events are created with "new" status, awaiting user approval

**New Documentation:** `docs/manual-email-to-calendar-walkthrough.md`
- Step-by-step guide from authenticated user to synced calendar event
- Covers all CLI commands in the email→event→calendar pipeline
- Includes troubleshooting for common issues (quota limits, OAuth errors)

**Commands in order:**
```bash
# 1. Auth & fetch
uv run python -m cli.cli_fetch_emails --max 10

# 2. Process emails to events
uv run python -m cli.cli_process_emails --recent 5

# 3. Review extracted events
uv run python -m cli.cli_events new

# 4. Approve events
uv run python -m cli.cli_events approve <event_id>

# 5. Sync to Google Calendar
uv run python -m cli.cli_events sync <event_id>
```

---

## 2026-01-27 (15)

### Test Coverage Improvements

**New test files:**
- `test_integration_events.py` - Event processing, sender rules, event sources, undo/redo
- `test_integration_calendars.py` - Calendar settings, sync to Google Calendar, cancel events
- `test_integration_gemini.py` - LLM extraction tests (skipped by default due to API costs)

**Key coverage:**
- Event lifecycle: create → approve → sync → cancel
- Sender rules: exact email match, domain wildcards, rule priority
- Event sources: email attribution, multi-source events, undo/redo of sources
- Calendar sync: create/update Google events, audit logging, error handling
- Gemini integration: birthday/appointment extraction, newsletter filtering

**Running LLM tests:**
```bash
# Skip LLM tests (default)
uv run pytest backend/tests/ -v

# Include LLM tests (costs ~$0.01/test)
uv run pytest backend/tests/ -v --run-llm
```

---

## 2026-01-26 (14)

### Job Queue System

**New Tables:**
- `jobs` - Persistent job queue with priorities, retries, scheduled execution
- `usage_quotas` - Track daily usage per user for rate limiting
- `global_limits` - System-wide default limits per resource type

**Job Features:**
- Priority-based claiming (lower number = higher priority)
- Automatic retry with exponential backoff (configurable max attempts)
- Job locking with `FOR UPDATE SKIP LOCKED` to prevent double-processing
- Scheduled jobs via `scheduled_for` timestamp
- Dead letter queue for failed jobs (status: 'dead')

**Rate Limiting:**
- Daily quotas per user per resource type (emails, LLM calls)
- RPC function `check_and_increment_quota` for atomic check-and-increment
- API middleware returns `X-RateLimit-*` headers
- Returns 429 when quota exceeded

**Worker System:**
- Configurable worker pool size via `WORKER_POOL_SIZE`
- APScheduler for periodic tasks (email fetch, job unlock, cleanup)
- Graceful shutdown on SIGINT/SIGTERM

**CLI Updates:**
- `cli_events sync` now enqueues calendar sync jobs
- Jobs processed by background workers

---

## 2026-01-25 (13)

### Complete Event Flow + Calendar Integration

**Event System:**
- Created `events` table with full lifecycle (new → approved → synced/rejected)
- Implemented undo/redo via snapshot storage in `event_sources`
- Event attribution tracks which emails contributed to each event
- Sender rules for auto-trust/auto-ignore patterns

**Calendar Integration:**
- Created `user_calendar_settings` table for default calendar preferences
- Google Calendar sync creates/updates/deletes events
- Audit logging via `calendar_sync_log` table
- Cancel operation prefixes title with "[CANCELLED]"

**CLI Tools:**
- `cli_events` - List, approve, reject, undo events
- `cli_events sync` - Sync approved events to Google Calendar

---

## 2026-01-24 (12)

### Email Processing Status + Gemini Integration

**Email Processing:**
- Added `processing_status` column to emails table
- Status flow: unprocessed → processing → processed/failed
- Trigger prevents re-processing already processed emails

**Gemini Service:**
- Created `selko/services/gemini.py` for LLM event extraction
- Structured output using Pydantic models
- Configurable thinking level (none/low/medium/high)
- Support for email attachments (images, PDFs)

**CLI Tools:**
- `cli_process_emails` - Extract events from emails via LLM

---

## Earlier Entries

See git history for changes prior to 2026-01-24.
