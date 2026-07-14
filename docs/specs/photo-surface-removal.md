# Spec: Remove photo surfaces from UI and docs (photos parked)

**Status:** Ready to implement
**Author:** Design plan (see git history)
**Context:** Photo ingestion is parked for cost/value reasons — see
[`onedrive-photo-ingestion.md`](onedrive-photo-ingestion.md) (PARKED), which
also documents why the existing Google Photos pipeline is already
non-functional (Google removed third-party library-wide read access to the
Photos Library API on 2025-03-31). This spec removes photo *mentions* from
user-visible surfaces and docs so the product doesn't advertise a feature
that doesn't work, while keeping the plumbing dormant for cheap restoration.

---

## 1. Principles

1. **Remove what users can see; keep what data depends on.** The Settings
   "Connect Google Photos" surfaces are visible to everyone and advertise a
   dead feature — remove them. Event-source *rendering* branches (photo icon
   on a card, "Source Photo" panel) only render when a photo-sourced event
   exists in the user's data — keep them, so any historical photo-sourced
   events still display correctly.
2. **No schema changes.** The `photos` table, `event_sources.source_origin =
   'google_photos'` constraint, and claiming RPCs stay. Historical rows keep
   working; restoration is a UI/docs revert, not a migration.
3. **Never remove the `google_photos` enum/serialization cases** in iOS
   (`EventSource.swift`, `Integration.swift`) and Android (`EventSource.kt`,
   `Integration.kt`) — decoding a historical `event_sources` row (or an
   `integrations` row for a user who once connected) would crash/fail if the
   raw value became unknown. Same for web `types.js` typedefs (JSDoc only,
   but keep for the same reason).
4. Each source-code increment follows the worktree + PR workflow and the
   scoped DoD (platform tests + screenshots for the platform touched). The
   docs increment edits `main` directly.

---

## 2. Inventory and disposition

### Web (`frontend/src/`) — Increment 1

| File | What | Action |
|---|---|---|
| `lib/components/IntegrationStatus.svelte` | Dashboard connect card: `google_photos` entry ("Scan photos for event details"), `photosIntegration`/`photosConnected` derived state, `partiallyConnected` includes photos | **Remove** the photos card + derived state; drop photos from `partiallyConnected` |
| `routes/app/settings/+page.svelte` | Photos connect/disconnect handler (`initiatePhotosAuth`, provider label map entry) | **Remove** the photos branch + import + label entry |
| `routes/app/+page.svelte` | `initiatePhotosAuth` import + connect branch (lines ~17/330); `googlePhotos` label; `isPhotoSource` props | **Remove** connect branch + import; **keep** `isPhotoSource` rendering props (data-driven) |
| `lib/api/backend.js` | `getPhotosAuthUrl` / `initiatePhotosAuth` | **Remove** (connect-only helpers) |
| `lib/i18n/en.json` | `integrations.googlePhotos`, `integrations.googlePhotosDescription` | **Remove** connect strings; **keep** `eventSource.*Photo*` + `history.fromPhoto` (rendering strings for historical events) |
| `lib/event-sender.js`, `lib/components/EventCard.svelte`, `SenderHeader.svelte`, `routes/app/events/[id]/+page.svelte`, `routes/app/history/+page.svelte`, `lib/services/event-sources.js`, `lib/types.js` | Photo-source rendering + typedefs | **Keep** (render only for existing photo-sourced events) |
| Tests: `IntegrationStatus.test.js`, `settings/__tests__/page.test.js`, `app/__tests__/page.test.js`, `backend-api.test.js`, `integrations.test.js` | Connect-flow expectations | **Update** (drop photos connect assertions); keep EventCard/SenderHeader/event-sender photo-rendering tests |

DoD: frontend unit tests + `npm run check` + web screenshots.

### iOS (`ios/Selko/`) — Increment 2

| File | What | Action |
|---|---|---|
| `Features/Settings/Views/SettingsView.swift` | `integrationRow(provider: .googlePhotos)` + `getPhotosAuthUrl` case | **Remove** row + auth case |
| `Core/API/BackendAPI.swift`, `SelkoTests/Mocks/MockBackendAPI.swift` | `getPhotosAuthUrl` | **Remove** |
| `Features/Settings/ViewModels/SettingsViewModel.swift` + tests | Photos connect state | **Remove** connect-flow pieces; update tests |
| `Features/Integrations/Models/Integration.swift`, `Features/Events/Models/EventSource.swift` | `googlePhotos` cases + mock | **Keep** cases (decoding safety, principle 3); mocks may stay |
| `Features/Review/…` (`ReviewQueueViewModel`, `EventDetailView`) | Photo-source rendering | **Keep** |

DoD: iOS tests + iOS screenshots.

### Android (`android/app/`) — Increment 3

| File | What | Action |
|---|---|---|
| `ui/screens/settings/SettingsScreen.kt` | Google Photos `IntegrationRow` (PhotoCamera icon, connect intent, disconnect) + `photosAuthUrl` param | **Remove** |
| `ui/screens/settings/SettingsViewModel.kt` + test | `getPhotosAuthUrl` | **Remove** |
| `data/api/BackendApiClient.kt`, `data/repository/IntegrationRepository.kt` | Photos auth URL plumbing | **Remove** connect-only pieces |
| `res/values/strings.xml` | `settings_google_photos` (+ description) | **Remove** |
| `data/model/Integration.kt`, `data/model/EventSource.kt` | `@SerialName("google_photos")` cases | **Keep** (principle 3) |
| `ui/screens/review/…` | Photo-source rendering | **Keep** |

DoD: Android tests + Android screenshots.

### Docs — Increment 4 (edit `main` directly)

| File | Action |
|---|---|
| `README.md` | Rewrite the two marketing sentences: drop "camera roll"/"photos" — email → calendar is the product today |
| `PRD_ARCH.md` | Mark FR-A.1, Journey 4, Google Photos integration rows, "Next" list, and scope bullets as **Parked** (not "Not Started") with a pointer to `docs/specs/onedrive-photo-ingestion.md`; drop `photoslibrary.readonly` from the scopes list (API access revoked by Google) |
| `CLAUDE.md` | Project overview: "(emails, photos)" → "(emails; photo ingestion parked — see docs/specs/onedrive-photo-ingestion.md)"; add both specs to the Reference Index |
| `docs/backlog.md` | Replace the Google Photos entry with a pointer to the parked OneDrive spec (Google Photos path is dead — API restriction) |
| `docs/llm-integration.md` | Mark photo-extraction sections as dormant (pipeline kept, no active source) |
| `docs/database-schema.md` | Keep `photos` table docs; add one line noting the table is dormant while photo ingestion is parked |
| `docs/supabase-frontend-queries.md`, `docs/ui/02-screen-specs.md` | Remove/annotate photo connect-card references to match the post-removal UI |
| `docs/specs/review-list-quality-fixes.md` | No change (historical, marked Implemented) |

### Backend — Increment 5 (optional hygiene, small PR)

Not strictly "UI and docs", but recommended so nothing advertises or burns
cycles on the dead path:

- `api/routes/photos.py` connect routes (`/integrations/photos/auth` +
  callback): return 410 Gone (or remove the router registration) so no new
  `google_photos` integrations can be created once the UI stops linking them.
- `workers/photo_fetch.py::schedule_photo_fetches`: stop registering the
  APScheduler job (one line in `api/app.py` lifespan) — it currently queries
  integrations every cycle for a fetch that can no longer see user photos.
- **Keep**: `photos` table, `photo_process` worker, `claim_pending_photo`
  polling slot, `services/photos.py`, `services/google_photos.py`. Dormant
  code is the restoration path; it is exercised by unit tests and costs
  nothing at runtime once the scheduler job is off.
- DoD: backend unit tests.

---

## 3. Sequencing

Increments 1–3 are independent (parallel agents OK — separate worktrees).
Increment 4 lands last so docs describe the shipped UI. Increment 5 can ride
with any of them or stand alone. No prod deploy urgency; batch behind the
next scheduled deploy.

## 4. Restoration

Revert increments 1–3 + 5 (small, self-contained diffs), then implement
[`onedrive-photo-ingestion.md`](onedrive-photo-ingestion.md) — schema, RPCs,
worker rails, and event-source rendering all remain in place.
