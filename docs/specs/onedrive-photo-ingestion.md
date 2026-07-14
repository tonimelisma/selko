# Spec: OneDrive photo ingestion (Microsoft Graph)

**Status:** PARKED (2026-07-13) — designed but deliberately not implemented.
Decision: photo ingestion is too expensive for the value right now (~$0.70–8.50
per user per month in LLM spend depending on mitigations — see §7 — against an
unproven hit rate of event-bearing photos). The research below is kept
indefinitely so implementation can start from here when the cost/value math
changes (cheaper vision models, higher-value user base, or picker-based manual
photo selection instead of full-stream scanning).
**Companion spec:** [`photo-surface-removal.md`](photo-surface-removal.md) —
removing photo mentions from UI and docs while this is parked.
**Author:** Design plan (see git history)
**Related reference docs:** [`docs/database-schema.md`](../database-schema.md), [`docs/job-queue.md`](../job-queue.md), [`docs/specs/outlook-email-support.md`](outlook-email-support.md), [`docs/llm-integration.md`](../llm-integration.md)

---

## 1. Goal

Let a user connect a **consumer OneDrive account** so their phone's photo stream —
the camera-roll photos the OneDrive mobile app auto-uploads to
`Pictures/Camera Roll` — is ingested into Selko like email is today: photo
records land in the `photos` table with `processing_status='pending'`, the
worker pool runs multimodal LLM extraction on each image, and any calendar
events found flow into the **same review pipeline** (New/Changes lanes →
approve → Google Calendar sync) that email-extracted events use.

**Terminology note:** OneDrive has no separate "photo stream" API. The photo
experience in the OneDrive apps (timeline, albums, Stories) is a view over
ordinary `driveItem` files; albums/Stories are not exposed via Microsoft Graph.
The API surface is the drive itself, so "photo stream" here = *new image files
appearing under designated photo folders*, primarily the Camera Roll backup
folder.

### Non-goals (v1)

- Webhooks / change notifications (Graph `/subscriptions`). We poll, like email.
- Videos (camera roll contains them; we filter to `image/*`).
- OneDrive for Business / SharePoint document libraries (personal MSA first;
  the code path mostly works for business accounts but is untested and delta
  semantics differ).
- Albums, Stories, shared libraries, or photos shared *with* the user.
- Writing anything back to OneDrive.
- File organization / "digital filing" journeys (Journey 4 in PRD). This spec is
  photo → calendar event only.

---

## 2. Background: what exists today

### 2.1 The email pipeline (the template)

```
OAuth → integrations row → scheduler enqueues email_fetch every 5 min
  → fetch (Gmail history cursor / Outlook per-folder delta cursor)
  → emails table (processing_status='pending')
  → worker pool claims → LLM extraction        [services/event_processing.py]
  → save_extracted_events()                     [services/events.py]
      ├─ find_matching_event (LLM dedup) → no match → New lane (pending_review)
      └─ match → propose_event_update → Changes lane (pending_change) or silent skip
  → user approves → status='approved' → calendar sync worker → Google Calendar
```

### 2.2 The existing Google Photos pipeline (the cautionary tale)

`services/google_photos.py`, `workers/photo_fetch.py`, `workers/photo_process.py`
implement a working end-to-end photo pipeline: `photos` table with the same
claiming columns as `emails`, `claim_pending_photo` RPC, LLM prompt tuned for
tickets/posters/invitations, `event_sources.source_origin='google_photos'`,
frontend support (photo icon on event cards, integration card, sender grouping).

Two problems:

1. **The API is dead for our use case.** Google removed third-party
   library-wide read access to the Photos Library API (the
   `photoslibrary.readonly` scope) on **March 31, 2025** — `mediaItems.search`
   now only returns content the app itself uploaded. The pipeline can no longer
   see the user's camera photos. OneDrive camera-roll backup is the replacement
   "mobile photo ingestion" path (PRD FR-A.1).
2. **It bypasses the shared event pipeline.** `_create_photo_event()` inserts
   events directly — no `find_matching_event` dedup, no Changes lane, no
   past-event cutoff. A poster photographed twice, or an event present in both
   an email and a photo, creates duplicates. This spec routes OneDrive photos
   through `save_extracted_events()` instead.

Reusable as-is: the `photos` table + claiming RPCs, the worker-pool slot, the
LLM prompt, the frontend photo-source affordances.

---

## 3. Microsoft Graph facts (verified against docs, July 2026)

**Auth.** Same MSAL confidential-client stack as `services/outlook.py`
(`authority=common`, works for personal Microsoft accounts). Delegated scope
**`Files.Read`** is the least-privileged scope for everything below (delta,
metadata, thumbnails, content) and is supported for personal MSAs. There is no
folder-scoped read permission on consumer OneDrive — `Files.Read` sees the
whole drive. Token refresh is identical to Outlook's.

**Change tracking.** `GET /me/drive/root/delta` is the one reliable way to
track changes on consumer OneDrive — **delta on non-root folders is not
supported for personal accounts** (the documented HTTP paths are root-only).
Behavior:

- First call enumerates the entire drive hierarchy in pages
  (`@odata.nextLink`), ending with an `@odata.deltaLink` cursor.
- Later calls with the deltaLink return only changed items (latest state per
  item, tracked by `id`; deletions carry a `deleted` facet).
- `?token=latest` returns an empty page + fresh deltaLink — "start from now,
  skip history".
- Supports `$select` and `$top`; `deltaExcludeParent` header suppresses parent
  chatter.
- Expired/invalid cursor → **HTTP 410 Gone** with a `Location` header holding a
  fresh enumeration URL. Same shape as Outlook's resync (`RESYNC_REQUIRED`
  sentinel already exists in `services/outlook.py`).

**Photo folders.** Special-folder aliases avoid localization problems:
`GET /me/drive/special/cameraroll` (Camera Roll backup folder),
`/special/photos` (Pictures), `/special/screenshots` is not an alias — Android
screenshots land under `Pictures/Screenshots` as a normal folder. Aliases stay
valid if the user renames/moves the folder. We resolve alias → folder id + path
at connect time and filter delta output by `parentReference.path` prefix.

**Metadata facets on `driveItem`** (free context for the LLM, no EXIF parsing
needed): `photo` (takenDateTime, camera make/model — full EXIF set on
consumer), `image` (width/height), `location` (GPS lat/long/alt), `file`
(mimeType, sha256/quickXor hashes).

**Thumbnails.** `GET /me/drive/items/{id}/thumbnails` returns pre-generated
JPEGs: `small` 96px / `medium` 176px / `large` 800px longest edge, plus custom
sizes: `?select=c2048x2048` = bounded box, aspect preserved. Thumbnail URLs are
pre-authenticated and cache-safe. **This is the LLM input path**: HEIC/HEIF
originals (every modern iPhone) are not accepted by our LLM providers, but
OneDrive's thumbnail pipeline hands us JPEG at any size — format conversion and
downscaling for free. Full originals remain available via
`/items/{id}/content` (302 to a download URL) if ever needed.

**Throttling.** 429 + `Retry-After`; no published fixed quota for consumer
OneDrive. Delta polling with a cursor is the documented low-cost pattern.

---

## 4. Design overview

```
Settings → Connect OneDrive
  → GET /integrations/onedrive/auth → Microsoft consent (Files.Read User.Read)
  → callback stores integrations row (provider='onedrive_photos')
  → resolve special folders (cameraroll, photos) → store included root paths

APScheduler (every FETCH_INTERVAL min)
  → scheduled_tasks: photo_fetch {provider:'onedrive_photos', user_id}
  → worker: fetch_drive_changes(cursor from integrations.sync_cursor)
      /me/drive/root/delta  ($select=id,name,size,file,folder,photo,image,
                             location,parentReference,deleted,createdDateTime,
                             lastModifiedDateTime)
  → filter: image mimetype + photo/image facet + path under included roots
            + not deleted + taken/created after backfill cutoff
  → upsert photos rows (provider='onedrive_photos', processing_status='pending')
  → persist new deltaLink (nextLink mid-enumeration → resumable initial scan)

Worker pool (existing claim_pending_photo slot)
  → fetch c2048x2048 JPEG thumbnail  ← not the original; solves HEIC + cost
  → [optional triage stage — §7]
  → LLM extract (existing photo prompt + takenDateTime/GPS/folder context)
  → save_extracted_events(source=photo)   ← shared dedup / New / Changes lanes
  → (optionally) store analyzed JPEG in Supabase Storage — §8

Review list → approve → existing calendar-sync worker → Google Calendar
```

Everything below the `photos` table is shared machinery; the new surface area
is one Graph service module, fetch-worker provider branch, process-worker
provider branch, two API routes, and frontend/type plumbing.

---

## 5. Components

### 5.1 `services/msgraph.py` (new, extracted from `outlook.py`)

`outlook.py` already contains everything Graph-generic: `_msal_app`,
`build_auth_url`, `exchange_code`, token refresh with expiry handling,
`_graph_get` with `GraphHttpError`, `_graph_prefer`. Extract these into a
shared `msgraph.py` parameterized by scope set; `outlook.py` and the new
`onedrive.py` both import it. (Alternative: copy-paste like
`google_photos.py` did from `gmail.py` — see Q-E1.)

Add here (both providers benefit): 429 handling that sleeps `Retry-After`
up to a cap, then raises.

### 5.2 `services/onedrive.py` (new)

```python
SCOPES = ["Files.Read", "User.Read"]
PHOTO_ROOT_ALIASES = ["cameraroll", "photos"]   # subject to Q-P1
RESYNC_REQUIRED = "__onedrive_resync_required__"

def resolve_photo_roots(access_token) -> dict[str, dict]:
    """alias -> {id, path} via /me/drive/special/{alias}; 404s skipped."""

def fetch_drive_changes(access_token, cursor: str | None,
                        ) -> tuple[list[dict], str]:
    """One page-loop over /me/drive/root/delta (or stored cursor URL).

    Returns (items, next_cursor). next_cursor is the deltaLink when done, or
    the current nextLink if we stop early (page budget) — both are resumable
    URLs, so initial enumeration of a huge drive survives task restarts.
    410 → follow Location header restart URL, return RESYNC_REQUIRED handling
    like outlook.fetch_message_changes.
    """

def is_ingestible_photo(item, included_root_paths, cutoff) -> bool:
    """image/* mimeType, has image or photo facet, not deleted, not a folder,
    parentReference.path under an included root, taken/created >= cutoff."""

def download_llm_image(access_token, item_id,
                       size="c2048x2048") -> tuple[bytes, str]:
    """Thumbnail JPEG bytes + 'image/jpeg'. Falls back large→medium if the
    custom size 404s; raises OneDriveError if no thumbnail exists."""

def parse_photo_item(item) -> dict:
    """driveItem -> photos-table dict (provider_photo_id, filename, mime_type,
    date_taken from photo.takenDateTime else createdDateTime, width, height,
    location_latitude/longitude, folder_path, size_bytes)."""
```

### 5.3 Fetch: generalize `workers/photo_fetch.py`

- `schedule_photo_fetches()` queries active integrations for **both** photo
  providers and enqueues `photo_fetch` tasks with `payload.provider`
  (Google Photos branch kept or retired per Q-P8).
- OneDrive branch: read cursor from `integrations.sync_cursor`; no cursor →
  initial sync per backfill decision (Q-P2):
  - *No backfill:* `?token=latest`, done in one call; only future photos flow.
  - *Backfill window:* full delta enumeration (metadata-only, ~200 items/page;
    a 100k-item drive ≈ 500 requests, one-time), filtering to photos taken
    within the window. Persist `nextLink` as the cursor after each page so the
    scan is resumable and bounded per task run (e.g. 50 pages/run).
- Upsert via `save_photo_metadata` with `on_conflict="user_id,provider,provider_photo_id"`
  (upsert only touches metadata columns, so re-seen items keep their
  processing status — no reprocessing after a 410 resync).
- Deletions (`deleted` facet): see Q-P7.
- Success → update `integrations.sync_cursor` + `last_photo_sync_at`.

### 5.4 Process: `workers/photo_process.py` provider branch

- `photos.provider == 'onedrive_photos'` → get token via
  `onedrive`/`msgraph` helpers, `download_llm_image()` (JPEG thumbnail),
  instead of the Google Photos original download.
- Prompt: reuse `_build_photo_prompt` with added context lines — taken
  datetime, GPS coordinates if present, containing folder name (e.g.
  "Screenshots" is a strong hint the image is a screenshot of an invite).
- **Route through the shared pipeline:** replace `_create_photo_event()` with a
  call into `save_extracted_events()`. This requires generalizing that function
  from `email_id: str` to a source descriptor (`email_id=...` or
  `photo_id=...`), so `create_event`/`event_sources` write the right link and
  dedup + Changes-lane + past-event-cutoff logic applies to photos. This is the
  main engineering lift of the spec (see Q-E2, Q-E3); the fallback is to keep
  direct insertion but call `find_matching_event()` first and skip on match.

### 5.5 API routes (`api/routes/integrations.py`)

- `GET /integrations/onedrive/auth` — mirrors the Outlook flow: create
  `oauth_states` row (provider `onedrive_photos`), redirect to Microsoft.
- `GET /integrations/onedrive/callback` — exchange code, fetch `/me` profile
  for `provider_email`, upsert integration row, resolve + persist photo roots,
  seed cursor (`token=latest`) or leave null for backfill enumeration.
- Disconnect goes through whatever the existing generic integration-delete
  route does today (verify while implementing).
- `cli/cli_auth_onedrive.py` — clone of `cli_auth_outlook.py` for
  staging/local token seeding and manual walkthroughs.

### 5.6 Schema migration (sketch)

```sql
-- photos: multi-provider
alter table photos add column provider text not null default 'google_photos';
alter table photos add column provider_photo_id text;
update photos set provider_photo_id = google_photo_id;
alter table photos alter column provider_photo_id set not null;
alter table photos alter column google_photo_id drop not null;  -- or drop, Q-E4
create unique index photos_user_provider_photo_uidx
  on photos (user_id, provider, provider_photo_id);
-- drop old unique (user_id, google_photo_id) index
alter table photos add column folder_path text;
alter table photos add column size_bytes bigint;

-- integrations / oauth_states / event_sources / scheduled_tasks:
-- extend provider / source_origin / task-payload allowed values with
-- 'onedrive_photos' (check constraints + docs). integrations.sync_cursor
-- stores the OneDrive deltaLink/nextLink; last_photo_sync_at reused.

-- event_sources: if Q-E3 = proper FK, add photo_id uuid references photos(id)
-- + require it for photo origins + partial unique (event_id, photo_id).
```

RPCs (`claim_pending_photo`, `unlock_expired_photo_locks`) are
provider-agnostic and unchanged.

### 5.7 Frontend (web first; iOS/Android as later increments)

- `types.js`: add `onedrive_photos` to `IntegrationProvider` and `SourceOrigin`.
- `IntegrationStatus.svelte` + Settings: OneDrive connect card ("Scan photos
  for event details" copy, Microsoft branding), connect/disconnect wiring to
  the new routes.
- `EventCard.svelte` / `event-sender.js`: treat `onedrive_photos` like
  `google_photos` (photo icon, photo sender grouping) — small additions since
  the affordances exist.
- Review card thumbnail (show the actual photo on the suggestion) is a product
  decision (Q-P5) — if yes, a signed Supabase Storage URL of the stored
  analyzed JPEG, which interacts with the storage-policy decision (Q-P4).

---

## 6. Sync-state & failure semantics

| Situation | Handling |
|---|---|
| Delta cursor expired (410) | Follow `Location` restart URL; re-enumerate; upserts keep processing state, so no duplicate processing. Mirrors Outlook resync. |
| Task dies mid initial enumeration | Cursor column holds last `nextLink` → next run resumes. |
| Photo deleted in OneDrive | `deleted` facet in delta → per Q-P7 (default: delete stored copy, keep photo row tombstoned + keep events). |
| Photo modified (edit/re-upload) | Delta re-emits item; upsert refreshes metadata; we do **not** reprocess (content edits that change event text are vanishingly rare) — revisit if evals disagree. |
| Thumbnail missing (rare formats) | Skip with `processing_status='skipped'` + reason, don't dead-letter. |
| 429 | Sleep `Retry-After` (capped), then fail task → normal scheduled-task retry. |
| Token refresh `invalid_grant` | `integrations.status='expired'` → surfaced in Settings, same as Outlook. |
| LLM failure | Existing photo retry/backoff/dead-letter columns. |

---

## 7. Cost control

Grounded in a real 13-day iPhone camera-roll sample (2026-07-01..13): 284
files — 228 images (mean 17.5/day, peak 36/day) and 56 videos (20% of files,
excluded from scope). **41% of images are burst followers** (taken ≤10 s
after the previous image).

Claude vision math: image tokens ≈ pixels ÷ 750. Sonnet 5 (project default
LLM) has high-res vision and does *not* downscale below 2576 px, so the
thumbnail size we request directly sets spend: c2048 (≈3.1 MP) ≈ 4,200
tokens, c1568 (≈1.8 MP) ≈ 2,460 tokens, 800 px `large` ≈ 640 tokens. Prompt +
schema ≈ 1,000 tokens; output ≈ 40–250 tokens. Pricing: Sonnet 5 $3/M input,
$15/M output; Haiku 4.5 $1/$5.

Per-photo: full extraction ≈ **$0.011** at c1568 (≈$0.016 at c2048); Haiku
triage on the 800 px thumbnail ≈ **$0.0008** (~14× cheaper than one
extraction).

Monthly cost at the sampled volume (~525 images/month/user), levers stacked:

| Pipeline | $/user/month |
|---|---|
| Full extraction on everything @ c2048 | ~$8.50 |
| Full extraction on everything @ c1568 | ~$5.90 |
| + Haiku triage (assuming ~12% escalate) | ~$1.15 |
| + burst dedup first (skip ≤10 s followers; free) | **~$0.70** |

Levers, in order:

1. **Burst dedup** (free, code-only): skip images taken ≤10 s after the
   previous ingested image (keep the first frame of each burst). −41% volume
   on the sample; a poster shot in a burst still gets its first frame
   processed.
2. **Thumbnail input at c1568, not c2048**: since Sonnet 5 no longer
   downscales at this size, c1568 saves 33% per call with negligible fidelity
   loss for poster/ticket text. c2048 remains an eval question (Q-E8).
3. **Two-stage triage** (decided: yes in v1): Haiku 4.5 on the 800 px `large`
   thumbnail, yes/no "does this image contain event-relevant text
   (poster/ticket/invitation/schedule/sign or a screenshot of one)?" — only
   hits escalate to full Sonnet extraction. Detection needs far less
   resolution than extraction, so 800 px is recall-safe; tune with the eval
   suite (Q-E7).
4. **No daily cap in v1** (decided): measure real spend via `llm_call_log`,
   add a cap only if numbers justify it. Backfill bursts self-limit via the
   pending queue draining at worker speed.

File-size note (bandwidth/memory, not tokens): a typical iPhone HEIC is
~2–4 MB (24 MP default on recent models), JPEG ~2× that, PNG screenshots
1–8 MB. Downloading originals at this user's volume ≈ 1.3 GB/month of
transfer; c1568 JPEG thumbnails ≈ 150–400 KB each (~10× less, keeps worker
RSS flat — relevant after the prod OOM work). LLM cost depends on pixel
dimensions only, never on file bytes.

The existing `llm_call_log` cost tracking and `quotas.py` service are the
enforcement points; evals (`docs/evals-process.md`) should get a photo
extraction suite before tuning triage thresholds (Q-E7).

---

## 8. Privacy

- `Files.Read` sees the **entire drive**, not just photos — must be disclosed
  in the connect UI copy. No narrower consumer scope exists.
- Selko-side retention of image bytes is a real decision (Q-P4): today's
  Google Photos path uploads **every processed photo** (original quality) to
  Supabase Storage. Options: (a) keep parity — store every analyzed JPEG;
  (b) store only photos where events were found (evidence for the review
  card); (c) store nothing, re-fetch thumbnails on demand. Recommendation: (b).
- Honor OneDrive deletions per Q-P7.

---

## 9. Testing / DoD

- Backend unit tests (the gate): `onedrive.py` parsing/filtering/delta/410
  paths, fetch-worker cursor + resumable enumeration + upsert idempotency,
  process-worker provider branch + shared-pipeline routing, migration
  backfill — Graph mocked with `MagicMock`/`patch` per repo convention.
- Regression tests for the `save_extracted_events` generalization (email path
  unchanged).
- Frontend unit tests + `npm run check` + web screenshots (Settings card,
  event card icon).
- Manual walkthrough: `cli_auth_onedrive` against a real consumer account with
  a seeded Camera Roll (poster photo, ticket screenshot, cat photo) →
  events appear in review; document alongside
  `docs/manual-email-to-calendar-walkthrough.md`.

### Increments (each its own worktree + PR)

1. Migration + `msgraph.py` extraction + `onedrive.py` + unit tests.
2. Fetch worker generalization + OAuth routes + CLI auth tool.
3. Process worker branch + `save_extracted_events` source generalization.
4. Web frontend (Settings + review affordances) + screenshots.
5. (Later) iOS/Android Settings parity; triage stage; webhooks.

---

## 10. Decisions & open questions

### Decided (2026-07-13, with Toni)

| Q | Decision |
|---|---|
| Q-P1 scan scope | **Camera Roll + Pictures tree** (includes Android/other Screenshots folders) |
| Q-P2 backfill | **Last 30 days** at connect (resumable delta enumeration, filter by takenDateTime) |
| Q-P3 videos | **Never** — filter to `image/*` permanently |
| Q-P4 retention | **Store only event-bearing photos** (analyzed JPEG kept as review evidence) |
| Q-P5 review UX | **Thumbnail on the review card** (signed Storage URL) |
| Q-P6 daily cap | **No cap in v1**; measure via `llm_call_log` first |
| Q-P7 deletions | **Delete our stored copy, tombstone the photo row, keep events** |
| Q-P8 Google Photos code | **Evaluate on merit**: reuse genuinely sound parts (photos table/claiming rails, worker slot), rewrite suboptimal parts (direct event insert, original downloads, no cursor); don't be constrained by the existing implementation |
| Q-E1 Graph plumbing | **Extract shared `msgraph.py`**; refactor `outlook.py` to use it |
| Q-E2 event pipeline | **Generalize `save_extracted_events`** to a source descriptor — full dedup/Changes-lane for photos |
| Q-E5 triage | **Yes, two-stage triage in v1** (Haiku-class on 800 px → Sonnet extraction on hits) |
| Q-E6 poll cadence | **Every 5 min**, matching email_fetch |

### Still open (defaults proposed)

- **Q-P9** auto-approve for photo events — default: none in v1 (no
  sender-rule analog for photos).
- **Q-P10** multiple OneDrive accounts per user — default: one in v1
  (matches one-Gmail/one-Outlook today).
- **Q-P11** relation to PRD's native mobile photo-upload path — default:
  OneDrive is the Phase-1 "mobile photo ingestion" (FR-A.1); in-app
  upload/camera stays future work.
- **Q-E3** `event_sources.photo_id` FK vs photo id in `extracted_data` JSON —
  default: proper FK column (needed anyway for the review-card thumbnail
  join).
- **Q-E4** keep or drop `photos.google_photo_id` after backfill — default:
  drop after backfilling `provider_photo_id` (one increment later).
- **Q-E7** photo eval suite timing — default: build a small suite (~30
  labeled images: posters, tickets, screenshots of invites, cats) **before**
  tuning the triage prompt; extraction ships with prompt as-is.
- **Q-E8** extraction input size — default: c1568 (see §7); promote to c2048
  only if evals show missed fine print.
- **Q-E9** task type — default: reuse `photo_fetch` scheduled-task type with
  `payload.provider`.
- **Q-E10** burst-dedup window — default: skip images ≤10 s after the
  previous ingested image (−41% on the sample); make the window a config
  value.
