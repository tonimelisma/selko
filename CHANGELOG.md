# Changelog

All notable changes to this project are documented in this file.

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
