# 03 — Client API, auth, live updates, web client, attachments

Part of the migration plan for `docs/specs/sqlite-single-process.md` (Q1, Q2,
Q3, Q5 and the web half of Q7/Q8). Everything here was read from the
repository on 2026-11-25. Nothing was run against a database. Columns were
derived statically from `supabase/migrations/*.sql` (CREATE TABLE plus later
`ADD/DROP/RENAME COLUMN`); the Q1 route integration tests are what confirm
them against the live local schema.

Conventions used below:

- "PostgREST timestamp" means the string form PostgREST emits for
  `timestamptz`, e.g. `2026-11-25T10:00:00.123456+00:00`. Every new endpoint
  returns timestamps as **strings in that exact form** (response models type
  them `str`, not `datetime`, so Pydantic does not re-serialise them as `Z`).
  Q6's SQLite codec must emit the same form. `time` columns stay `HH:MM:SS`.
- Errors: every new endpoint raises `HTTPException(detail=error_detail(code,
  message))` (`backend/selko/api/schemas/common.py:58`), so the body is
  `{"detail": {"error": CODE, "detail": message}}`. That is the shape
  `parseApiError` in `frontend/src/lib/api/backend.js:124` already parses into
  `{message, status, code}`.
- Ownership: "owned" means the row's `user_id` equals the token subject, or for
  `event_sources` (no `user_id` column) the parent `events.user_id`. A row that
  exists but is not owned answers exactly like a missing row: **404**, never
  403 (Q3's generated cross-user test requires 404; the existing
  `_get_owned_event` at `backend/selko/api/routes/events.py:276` returns 403
  and is changed to 404 in Q3).
- Rate limits: `limiter = Limiter(key_func=get_user_id_or_ip,
  default_limits=["60/minute"])` (`backend/selko/api/app.py:69`) applies to every
  route through `SlowAPIMiddleware` (`app.py:261`), per route per key. "Default"
  below means that limit; others are an explicit `@limiter.limit(...)`.

---

## A. Client data API

### A.1 Every supabase-js call in `frontend/src` (tests excluded)

Callers were found by grepping every exported function name across
`frontend/src/routes` and `frontend/src/lib` (excluding `__tests__`). **13 of
the 31 service functions have no caller** and are deleted instead of ported
(marked DEAD).

#### `frontend/src/lib/services/events.js`

`EVENT_RELATIONS` (line 9):
```
*, event_sources(*, emails(id, subject, from_email, from_name, date_sent)),
event_change_proposals(id, event_id, user_id, source_id, kind, status, change_set,
  event_snapshot_before, resolution_reason, created_at, resolved_at, updated_at),
calendar_work_items(id, event_id, user_id, action, generation, status, provider_event_id,
  expected_provider_revision, force_overwrite, attempts, max_attempts, next_retry_at,
  failure_code, failure_detail, created_at, updated_at, completed_at)
```
Every result is passed through `withDeliveryStatus` (line 45), which adds
`status` from `deriveEventStatus` (line 25), a JS copy of
`derive_delivery_status` (`backend/selko/services/events.py:79`).

| Line | Function | Query | Callers / what the UI does |
|---|---|---|---|
| 88 | `fetchPendingEvents` | `events` `select('*',{count:'exact'})`, `review_status=eq.pending_review`, `.or(end>=now, (end null and start>=now), (both null))`, order `start_datetime asc`; client post-filter by `end||start >= now` | DEAD |
| 118 | `fetchEvents` | `events` `select('*',{count:'exact'})` order `start_datetime asc`, optional `in review_status`, `gte/lte start_datetime`, `range` | DEAD |
| 151 | `getEvent` | `events` `select(EVENT_RELATIONS)` `eq id` `.single()` | `routes/app/events/[id]/+page.svelte:93` (form fields `title, all_day, location, description, start_datetime, end_datetime`; `event_sources[0].source_origin`, `.email_id`); `routes/app/history/+page.svelte:503` (re-fetch one row after undo) |
| 172 | `updateEventStatus` | `rpc('set_event_review_status', {p_event_id, p_review_status: 'active'|'rejected'})`; returns `{event_id, review_status, work_item_id, generation}` (not an event; `withDeliveryStatus` of it is meaningless) | `routes/app/+page.svelte:397,422,522`, `events/[id]/+page.svelte:196,219`. **Only `error` is read** at every call site |
| 192 | `fetchPendingEventsWithSources` | `events` `select(EVENT_RELATIONS)` `in review_status (pending_review, active)` + same `.or(...)` time filter, order `start_datetime asc`; client keeps only `isNewReviewEvent` (review_status pending_review) or `isChangeReviewEvent` (a proposal with status pending) and `end||start >= now` | `routes/app/+page.svelte:333` — the whole Review queue: `EventCard`/`ChangeCard` read event columns, `status`, `event_sources[].emails.{from_email,from_name,subject,date_sent}`, `event_sources[].source_origin`, `event_change_proposals[].{kind,status,change_set,event_snapshot_before}` (`lib/event-sender.js:17-30`) |
| 222 | `fetchActivityEvents` | `events` `select(EVENT_RELATIONS,{count:'exact'})` `in review_status (active, rejected, cancelled)`, `.not('event_change_proposals.status','eq','pending')` — **this filters the embedded proposals array, not the parent rows** (no `!inner`), order `updated_at desc`, `range(offset, offset+limit-1)` | `routes/app/history/+page.svelte:109,120,155,169`; reads `data`, `count` (`totalCount`), proposal `status` in (`applied`,`closed_legacy`) (lines 376–409), `event.status` (422, 646) |
| 246 | `updateEvent` | `events` `.update(updates).eq('id').select().single()`; `updates` ⊂ `{title, start_datetime, end_datetime, all_day, location, description}` (undefined keys dropped by JSON) | `events/[id]/+page.svelte:175` on every field blur and before approve; **assigns `event = result.data`**, which today is a bare row with no relations and no `status` |

#### `frontend/src/lib/services/event-sources.js`

| 41 | `fetchEventSources` | `event_sources` `*, emails(id,subject,from_email,from_name,date_sent)` `eq event_id` order `created_at asc` | DEAD (only mocked in `routes/app/events/[id]/__tests__/page.test.js`) |

#### `frontend/src/lib/services/email-history.js`

| Line | Function | Query | Callers / UI |
|---|---|---|---|
| 13 | `fetchEmailHistory` | `emails` `select('id,email_provider,subject,from_email,from_name,date_sent,processing_status,processing_error,processing_outcome,processing_explanation,processed_at,event_sources(id,event_id,source_type,events(id,title,review_status,event_change_proposals(id,kind,status,change_set,resolution_reason),calendar_work_items(id,action,status,generation,failure_code,failure_detail)))',{count:'exact'})`, `.or('processing_status.in.(processed,failed),and(processing_status.eq.skipped,processing_outcome.eq.calendar_invite)')`, order `date_sent desc` then `id desc`, `range` | `history/+page.svelte:127,182,196`; reads `data`, `count` |
| 52 | `fetchEmailProcessingState` | `emails` `select('id,processing_status,processing_error,processing_outcome,processing_explanation,processed_at')` `eq id` `.maybeSingle()` | `history/+page.svelte:289` (poll while a reprocess runs) |
| 41 | `queueEmailReprocess` | already the API (`POST /emails/{id}/reprocess`) | `history/+page.svelte:328` |

#### `frontend/src/lib/services/emails.js`

| 34 | `fetchEmails` | `emails *` with flag filters, `range` | DEAD |
| 70 | `getEmail` | `emails` `select('*')` `eq id` `.single()` — returns `body_text` and every lease column | `events/[id]/+page.svelte:137`; reads only `from_name, from_email, subject, date_sent, snippet` (lines 261–302) |
| 89 | `updateEmailReadStatus` | `emails` update `is_unread` | DEAD |

#### `frontend/src/lib/services/attachments.js`

| 25 | `fetchAttachments` | `attachments` `select('*')` `eq email_id` order `filename asc` | `events/[id]/+page.svelte:138`; reads `length` and `filename` (lines 271–310) |
| 46 | `getAttachment` | `attachments *` `eq id` `.single()` | DEAD |
| 67 | `downloadAttachment` | `supabase.storage.from('attachments').download(storagePath)` | DEAD — **the one Storage call in the web app has no caller** |
| 85 | `getAttachmentUrl` | `storage.createSignedUrl(path, 3600)` | DEAD |

#### `frontend/src/lib/services/integrations.js`

Columns everywhere: `id, user_id, provider, status, provider_email, scopes, last_sync_at, created_at, updated_at`.

| 16 | `fetchIntegrations` | `integrations` that select, `{count:'exact'}`, order `created_at desc` | `routes/app/+page.svelte:295`, `events/[id]/+page.svelte:94`, `settings/+page.svelte:152`; reads `data` only (`count` unused); `hasWritableCalendar` (`lib/calendar-providers.js`) reads `provider, status, scopes` |
| 36 | `getIntegration` | `eq id .single()` | DEAD |
| 57 | `getIntegrationByProvider` | `eq provider .single()`, PGRST116 → null | DEAD (only via DEAD `isProviderConnected`) |
| 84 | `disconnectIntegration` | `delete().eq('id')` | DEAD |
| 101 | `disconnectIntegrations` | `delete().in('id', ids)` | `settings/+page.svelte:328` (Google card passes the Gmail + Google Calendar ids together) |
| 136 | `fetchCalendarRecovery` | `integration_recoveries` `select('id, integration_id, user_id, provider, status, discovered_count, completed_count, remaining_count, withdrawn_count, error_detail, requested_at')` `eq provider google_calendar` order `requested_at desc` `limit 1` `.maybeSingle()` | `lib/components/ConnectionRecovery.svelte:69`, polled every 5 s while non-terminal (lines 75–94) |

#### `frontend/src/lib/services/email-folders.js`

| 10 | `fetchEmailFolders` | `email_folders` `select('id,provider,name,full_path,classification_decision,classification_reason,user_override,is_included,is_system')` `eq provider` `eq is_system false` order `full_path` | `settings/+page.svelte:194`. **Duplicate:** `GET /integrations/{provider}/folders` (`backend/selko/api/routes/integrations.py:64`) returns exactly this select, and `backend.fetchEmailFolders` (`lib/api/backend.js:295`) already calls it but nothing imports it |
| 31 | `updateEmailFolder` | already the API (`PATCH /integrations/{provider}/folders/{id}`) | `settings/+page.svelte:219` |

#### `frontend/src/lib/services/sender-rules.js`

| 25 | `fetchSenderRules` | `sender_rules *` order `created_at desc` | `lib/components/SenderRulesPanel.svelte:37`; reads `id, action, sender_email, sender_domain` |
| 53–60 | `createSenderRule` | `auth.getUser()` for `user.id`, then `insert({...rule, user_id}).select().single()`; rule = `{sender_email?|sender_domain?, action}` | `SenderRulesPanel.svelte:58`, `routes/app/+page.svelte:592` (`{sender_email, action:'auto_approve'}`); reads `error.message` (23505 → "A record with this information already exists.") |
| 81 | `ignoreSenderRetroactive` | `rpc('ignore_sender_and_reject_pending', {p_sender_email})` → `{rejected_new, discarded_changes}` | `routes/app/+page.svelte:570`; reads `error` only |
| 98 | `deleteSenderRule` | `delete().eq('id')` | `SenderRulesPanel.svelte:84` |
| 118 | `findMatchingRule` | `or(sender_email.eq.X, sender_domain.eq.Y)` | DEAD |

#### `frontend/src/lib/services/calendar-settings.js`

| 25 | `getCalendarSettings` | `user_calendar_settings` `select('*')` `.maybeSingle()` | `settings/+page.svelte:153`; reads `target_calendar_id, all_day_display_mode, all_day_custom_start, all_day_custom_end` |
| 51–64 | `updateCalendarSettings` | `auth.getUser()`, then `upsert({user_id, ...settings, updated_at: now}).select().single()`; payload is `{target_calendar_id}` (line 261) or `{all_day_display_mode[, all_day_custom_start, all_day_custom_end]}` (line 303) | `settings/+page.svelte:261,303`; reads `error.message` |

#### Auth and realtime call sites (detailed in B and C)

| File:line | Call |
|---|---|
| `lib/supabase.js:1-6` | `createClient(VITE_SUPABASE_URL, VITE_SUPABASE_ANON_KEY)` (default: session persisted in `localStorage` key `sb-<ref>-auth-token`, auto refresh) |
| `lib/stores.js:32` | `supabase.auth.getSession()` → `user.set(session?.user)`; `loading.set(false)` |
| `lib/stores.js:36-41` | `onAuthStateChange` → `user.set`; on `TOKEN_REFRESHED`/`SIGNED_IN` calls `live-updates.refreshAuth(access_token)` |
| `lib/api/backend.js:26` | `supabase.auth.getSession()` for the Bearer token of every API call |
| `lib/services/calendar-settings.js:53`, `lib/services/sender-rules.js:55` | `supabase.auth.getUser()` (a GoTrue round trip) to put `user_id` into the payload |
| `routes/login/+page.svelte:20` | `signInWithPassword({email,password})`; shows `authError.message` |
| `routes/register/+page.svelte:31` | `signUp({email,password,options:{emailRedirectTo: origin+'/login'}})`; client-side checks: passwords match, length ≥ 6; on success always shows `auth.checkEmail` |
| `routes/app/+layout.svelte:74`, `routes/app/settings/+page.svelte:356` | `supabase.auth.signOut()` — supabase-js v2 default scope is **`global`** (every session of the user) |
| `lib/live-updates.js:42,154-163,211,237` | `realtime.setAuth`, `auth.getSession`, `channel(topic,{config:{private:true}})`, `removeChannel` |
| `routes/+page.svelte:8`, `lib/stores.js:11` | JSDoc type `import('@supabase/supabase-js').User` only |

The user object is read for `id` (`routes/app/+layout.svelte:35`) and
`email` (`lib/components/Navbar.svelte:18`, `settings/+page.svelte:138`) only.

### A.2 API routes the web already calls (not duplicated)

| Route | Defined at | Web caller |
|---|---|---|
| `POST /emails/{email_id}/reprocess` | `api/routes/emails.py:46` | `backend.reprocessEmail` ← `email-history.js:41` |
| `GET /integrations/{provider}/folders` | `api/routes/integrations.py:64` | `backend.fetchEmailFolders` (unused today; **becomes the folder list**) |
| `PATCH /integrations/{provider}/folders/{folder_id}` | `integrations.py:87` | `email-folders.js:31` → `backend.updateEmailFolder` |
| `GET /integrations/google/auth`, `GET /integrations/outlook/auth` | `integrations.py:285,309` | `backend.initiateGoogleAuth/initiateOutlookAuth` |
| `GET /integrations/google/callback`, `/integrations/microsoft/callback` | `integrations.py:328,445` | provider redirects (no web token) |
| `GET /calendars` | `api/routes/calendars.py:27` | `backend.listCalendars` ← `settings/+page.svelte:242` |
| `POST /events/{id}/sync` | `api/routes/events.py:47` | `history/+page.svelte` retry |
| `POST /events/{id}/apply-change`, `/reject-change`, `/undo` | `events.py:311,345,365` | review, history, event detail |
| `GET /health` | `api/routes/health.py:87` | `backend.checkHealth` (no caller) |

Not called by the web: `POST /emails/sync`, `/emails/{id}/process`,
`/emails/batch-process`, `/events/{id}/unsync`, `/integrations/photos/auth`.

### A.3 Where the new code lives

- `backend/selko/services/client_data.py` (new): one function per operation,
  each `(client, user_id, ...)`, always filtering by `user_id`. Q1 implements
  them with PostgREST through the **shared, egress-hooked** service client
  (`get_service_client`, `services/auth.py:122`), not `get_service_role_client`
  (`api/deps.py:130`), which builds a fresh unhooked client per request and
  would bypass the egress meter (CLAUDE.md: "do not construct a second
  service client without that hook"). New dependency in `api/deps.py`:
  `get_shared_service_client()` = `lru_cache`d `get_service_client(get_config())`.
  Q6 reimplements the same functions over `selko/db/`; routes do not change.
- Response models: `backend/selko/api/schemas/client.py` (new) for the shapes
  below; `ErrorCode` (`schemas/common.py:10`) gains `CONFLICT`,
  `INVALID_CREDENTIALS`, `USER_ALREADY_EXISTS`, `WEAK_PASSWORD`,
  `INVALID_GRANT`, `ATTACHMENT_NOT_FOUND`, `ATTACHMENT_NOT_STORED`.
- Routers: additions to `routes/events.py`, `routes/emails.py`,
  `routes/integrations.py`; new `routes/sender_rules.py`, `routes/settings.py`,
  `routes/attachments.py`, `routes/auth.py`, `routes/live.py`, exported from
  `routes/__init__.py` and included in `create_app` (`app.py:275-280`), which
  keeps them reachable for `backend/tests/test_reachability.py`.
- Why the service client and not the user-JWT client (`get_authenticated_client`,
  `deps.py:106`): Q5 replaces GoTrue tokens with Selko tokens, which PostgREST
  will not accept; anything built on RLS-with-the-user's-JWT would break at Q5.
  Explicit `user_id` filters are also exactly what Q3 and Q6 require.
- Ordering in Postgres terms must be reproduced exactly: `ASC` sorts NULLs
  **last**, `DESC` sorts NULLs **first** (PostgREST's default). Embedded arrays
  have no order today (physical order); the new endpoints pin one:
  `event_sources` by `created_at, id`; `event_change_proposals` by
  `created_at, id`; `calendar_work_items` by `generation, id`.
  `events/[id]/+page.svelte:130-136` uses `sources[0]`, so the earliest source
  is now guaranteed to be first.

### A.4 Endpoints

Event row shape `EventRow` (every `events` column, as `select *` returns
today): `id, user_id, title, start_datetime, end_datetime, all_day, location,
description, source_attribution, google_calendar_event_id, synced_at,
created_at, updated_at, importance, recurrence_rule, recovery_id,
review_status`, **plus `status`** computed server-side by
`derive_delivery_status` (one implementation; the JS `deriveEventStatus` is
deleted in D, its cases already covered by `backend/tests/test_events.py`).

`EventWithRelations` = `EventRow` +
- `event_sources: [ {id, event_id, email_id, source_type, extracted_data, created_at, source_origin, google_calendar_source_event_id, emails: {id, subject, from_email, from_name, date_sent} | null} ]`
- `event_change_proposals: [ {id, event_id, user_id, source_id, kind, status, change_set, event_snapshot_before, resolution_reason, created_at, resolved_at, updated_at} ]`
- `calendar_work_items: [ {id, event_id, user_id, action, generation, status, provider_event_id, expected_provider_revision, force_overwrite, attempts, max_attempts, next_retry_at, failure_code, failure_detail, created_at, updated_at, completed_at} ]`

(`calendar_work_items.desired_event`, `locked_by`, `locked_until`, `provider`
stay server-side, as today.)

#### E1. `GET /events/review`
- Replaces `fetchPendingEventsWithSources`.
- Query: none. Response `200`: `EventWithRelations[]`.
- Server logic: owned events with `review_status IN ('pending_review','active')`
  and `(end_datetime >= now) OR (end_datetime IS NULL AND start_datetime >= now)
  OR (both NULL)`; keep a row only if `review_status = 'pending_review'` or it
  has a proposal with `status = 'pending'`; order `start_datetime ASC NULLS
  LAST, id`. `now` is the server clock (UTC). Q1 does the lane filter in Python
  after the PostgREST query (same work the browser does today); Q6 does it in
  SQL (`EXISTS (SELECT 1 FROM event_change_proposals p WHERE p.event_id = e.id
  AND p.status = 'pending')`), so the query no longer reads every active event.
- No pagination (today's has none; the queue is bounded by what is pending).
- Rate limit: default. Errors: 401.
- Reuses: the select string moves from `events.js:9`.

#### E2. `GET /events/activity?limit=20&offset=0`
- Replaces `fetchActivityEvents`.
- Query: `limit` int 1–500 (default 20), `offset` int ≥ 0 (default 0).
  The history page asks for `Math.max(20, currentLen)` on live refresh
  (`history/+page.svelte:109,120`); the client wrapper clamps to 500.
- Response `200`: `{items: EventWithRelations[], total: int, offset, limit}`
  (`PaginatedResponse`, `schemas/common.py:78`). `total` = exact count of
  matching parent rows (today's `count:'exact'`).
- Server logic: owned events, `review_status IN ('active','rejected','cancelled')`,
  embedded `event_change_proposals` **exclude** `status = 'pending'` (parent rows
  are not filtered by it — preserves today's PostgREST semantics), order
  `updated_at DESC NULLS FIRST, id DESC` (id tiebreak is new: today's paging
  can repeat or skip rows with equal `updated_at`).
- Rate limit: default. Errors: 401, 422 (bad limit/offset).

#### E3. `GET /events/{event_id}`
- Replaces `getEvent`. Path `event_id` UUID (declared **after** `/events/review`
  and `/events/activity` in the router, so those literals are not parsed as ids).
- Response `200`: `EventWithRelations`. `404 EVENT_NOT_FOUND` if missing or not owned.
- Rate limit: default.

#### E4. `PATCH /events/{event_id}`
- Replaces `updateEvent`.
- Body (all optional, unknown keys → 422, `extra='forbid'`):
  `title: str (1–500 chars, trimmed non-empty)`, `start_datetime: str ISO 8601
  with offset | null`, `end_datetime: same`, `all_day: bool`, `location: str
  (≤ 1000) | null`, `description: str (≤ 20000) | null`. At least one field, else 422.
- Ownership: `UPDATE events SET … WHERE id = :id AND user_id = :uid`; 0 rows → 404.
- Response `200`: `EventWithRelations` of the updated row (today it returns a
  bare row and the page replaces its `event` with it, dropping `event_sources`
  and `status`; returning the full shape fixes that without a UI change).
- Behaviour kept as is: no calendar work is enqueued; the edit applies to any
  review status, as today. (Hazard noted, not changed here: editing an already
  active event does not reach the calendar. A product decision for Toni.)
- Triggers that fire today still fire in Q1 (`set_events_updated_at`,
  `trg_events_broadcast_upd`, the change-proposal invariant).
- Rate limit: default (the page saves on every blur; 60/min is ample).
- Errors: 401, 404, 422.

#### E5. `POST /events/{event_id}/accept` and E6. `POST /events/{event_id}/reject`
- Replace `updateEventStatus(id,'approved'|'rejected')`.
- Body: none. Response `200`: `{event_id, review_status: 'active'|'rejected', work_item_id: str|null, generation: int|null}` (the RPC's own return).
- Server: `set_event_review_status(p_event_id, 'active'|'rejected', p_user_id = user.id)`
  as service role — the function already accepts `p_user_id` from
  `service_role` and checks ownership (`20260831000001_extraction_decision_intent.sql`,
  `SELECT … WHERE id = p_event_id AND user_id = v_user_id`). Its `42501`
  ("not owned by the caller") maps to **404**; `22023` to 422. After accept,
  `worker_pool.nudge()` exactly as `apply_change` does (`events.py:322-328`).
- Rate limit: default. Errors: 401, 404, 500. (The function checks only
  ownership and the target value; any refusal comes from
  `_enqueue_calendar_work`, which the endpoint maps to 409 `CONFLICT` with the
  function's message. The route test covers accept on a `pending_review` and
  on a `rejected` event so the mapping is pinned against real SQL.)

#### E7. `GET /emails/history?limit=20&offset=0`
- Replaces `fetchEmailHistory`.
- Query: `limit` 1–500 (default 20), `offset` ≥ 0.
- Response `200`: `{items: [EmailHistoryRow], total, offset, limit}` where
  `EmailHistoryRow = {id, email_provider, subject, from_email, from_name,
  date_sent, processing_status, processing_error, processing_outcome,
  processing_explanation, processed_at, event_sources: [{id, event_id,
  source_type, events: {id, title, review_status, event_change_proposals: [{id,
  kind, status, change_set, resolution_reason}], calendar_work_items: [{id,
  action, status, generation, failure_code, failure_detail}]} | null}]}`.
- Server: owned emails where `processing_status IN ('processed','failed') OR
  (processing_status = 'skipped' AND processing_outcome = 'calendar_invite')`,
  order `date_sent DESC NULLS FIRST, id DESC`.
- Rate limit: default. Errors: 401, 422.

#### E8. `GET /emails/{email_id}`
- Replaces `getEmail`. Narrow on purpose: today's `select('*')` ships
  `body_text`, lease and dead-letter columns that the page never reads.
- Response `200`: `{id, email_provider, subject, from_email, from_name, date_sent, snippet, has_attachments}`.
- `404 EMAIL_NOT_FOUND` if missing or not owned. Rate limit: default.

#### E9. `GET /emails/{email_id}/processing-state`
- Replaces `fetchEmailProcessingState`.
- Response `200`: `{id, processing_status, processing_error, processing_outcome, processing_explanation, processed_at}`; `404` if missing or not owned
  (today `maybeSingle` returns `data: null`; the page treats a missing row and an
  error alike, `history/+page.svelte:289-300`).
- Rate limit: default (polled while one reprocess runs).

#### E10. `GET /emails/{email_id}/attachments`
- Replaces `fetchAttachments`.
- Response `200`: `[{id, email_id, filename, mime_type, size_bytes, ingestion_status, created_at}]`, order `filename ASC, id`. `storage_path`, `content_hash`, `provider_attachment_id` and lease columns are no longer sent to the browser.
- Ownership: the email must be owned (404 otherwise); attachments filtered by `user_id` too.
- Rate limit: default.

#### E11. `GET /integrations`
- Replaces `fetchIntegrations`.
- Response `200`: `[{id, user_id, provider, status, provider_email, scopes, last_sync_at, created_at, updated_at}]`, order `created_at DESC, id`. No tokens, ever (pinned by a test that the response has no `access_token`/`refresh_token` key). `count` is dropped (no reader).
- Rate limit: default. Path is the router root (`""`); no clash with `/{provider}/folders`.

#### E12. `POST /integrations/disconnect`
- Replaces `disconnectIntegrations`.
- Body: `{integration_ids: [uuid, …]}` (1–10 ids).
- Server: `DELETE FROM integrations WHERE user_id = :uid AND id IN (:ids)`.
  Cascades as today (`email_folders`, `integration_recoveries`; `emails.integration_id` set null).
  No provider-side token revocation (same as today).
- Response `200`: `{deleted: int}`. If none of the ids is owned → 404 (so a
  cross-user call is indistinguishable from a missing id); a partial match deletes
  the owned ones and reports the count.
- Rate limit: `10/minute`. Errors: 401, 404, 422.

#### E13. `GET /integrations/recovery?provider=google_calendar`
- Replaces `fetchCalendarRecovery`.
- Query: `provider` (pattern `^(google_calendar|gmail|outlook)$`, default `google_calendar`).
- Response `200`: `{recovery: {id, integration_id, user_id, provider, status, discovered_count, completed_count, remaining_count, withdrawn_count, error_detail, requested_at} | null}`, the owned row with the latest `requested_at`.
- Rate limit: `30/minute` (the card polls every 5 s = 12/min).

#### (reused) `GET /integrations/{provider}/folders`
`settings/+page.svelte:16` imports `fetchEmailFolders` from
`$lib/services/email-folders.js`; that module switches to `backend.fetchEmailFolders`.
Same response, no new endpoint. The route moves to the shared service client
plus its existing `.eq("user_id", user.id)` in Q3.

#### E14. `GET /sender-rules`
- Response `200`: `[{id, user_id, sender_email, sender_domain, action, created_at, updated_at}]`, order `created_at DESC, id`.
- Rate limit: default.

#### E15. `POST /sender-rules`
- Body: `{sender_email?: str, sender_domain?: str, action: 'auto_approve'|'ignore'}`; exactly the validation of `sender-rules.js:49` (at least one of email/domain) → 422 otherwise. Email lowercased and trimmed? **No** — kept as given, because `ignore_sender_and_reject_pending` matches `from_email = p_sender_email` verbatim and today's rows are stored as given.
- Server: insert with `user_id = token subject` (the client no longer sends `user_id`).
- Response `201`: the row. `409 CONFLICT` "A record with this information already exists." on the partial unique indexes `(user_id, sender_email)` / `(user_id, sender_domain)` — the same text `parseSupabaseError` gives for `23505` today.
- Rate limit: `20/minute`.

#### E16. `DELETE /sender-rules/{rule_id}`
- Server: `DELETE … WHERE id AND user_id`; the `sender_rule_before_delete` trigger still resets matching skipped emails.
- Response `204`; `404` if missing or not owned. Rate limit: `20/minute`.

#### E17. `POST /sender-rules/ignore-sender`
- Replaces `ignoreSenderRetroactive`.
- Body: `{sender_email: str}` (or `sender_domain`; exactly one).
- Response `200`: `{rejected_new: int, discarded_changes: int}`.
- **Needs a migration in Q1.** Today's function is `SECURITY INVOKER` and takes the user from `auth.uid()` (`20260829000001_delete_events_status.sql`, `v_user_id uuid := auth.uid()`), granted to `authenticated` only; called as service role, `auth.uid()` is NULL and it raises "not authenticated". New migration `2026112xxxxxxx_ignore_sender_takes_user.sql`: `ignore_sender_and_reject_pending(p_user_id uuid, p_sender_email text DEFAULT NULL, p_sender_domain text DEFAULT NULL)` with the same body using `p_user_id`, `REVOKE ALL … FROM PUBLIC, anon, authenticated; GRANT EXECUTE … TO service_role`. The old 2-argument signature is dropped in Q3, once no deployed web build calls it (D.4 step 2 + 7 days).
- Rate limit: `20/minute`. Errors: 401, 422.

#### E18. `GET /settings/calendar`
- Response `200`: `{settings: {user_id, target_calendar_id, default_invitees, timezone, all_day_display_mode, all_day_custom_start, all_day_custom_end, updated_at} | null}`.
- Rate limit: default.

#### E19. `PATCH /settings/calendar`
- Body (partial, `extra='forbid'`): `target_calendar_id: str|null` (opaque; Outlook ids are `outlook:`-prefixed and stored unchanged), `default_invitees: str|null`, `timezone: str` (must be a valid IANA zone, `zoneinfo.ZoneInfo`), `all_day_display_mode: 'all_day'|'day_9_to_5'|'morning_8_to_9'|'custom'`, `all_day_custom_start: 'HH:MM'|'HH:MM:SS'|null`, `all_day_custom_end: same`.
  If the resulting row has mode `custom`, both times are required and end > start (the table's CHECK enforces the same; the API returns 422 before the database does).
- Server: upsert on `user_id` merging only the given columns (PostgREST `Prefer: resolution=merge-duplicates`, as supabase-js `upsert` does today); `updated_at` is set by the server/trigger, not the client.
- Response `200`: `{settings: <row>}`. Rate limit: `20/minute`. Errors: 401, 422.

E20–E23 (auth), E24 (`/live`) and E25 (attachment download) are in B, C and E.

### A.5 Dropped with the client code

`fetchPendingEvents`, `fetchEvents`, `fetchEventSources`, `fetchEmails`,
`updateEmailReadStatus`, `getAttachment`, `downloadAttachment`,
`getAttachmentUrl`, `getIntegration`, `getIntegrationByProvider`,
`disconnectIntegration`, `isProviderConnected`, `findMatchingRule`. The spec's
§2 list named `event_sources` list, `emails` list/update and attachment download
as client operations; none of them has a caller, so the real Q1 surface is 19
data endpoints, not ~20.

### A.6 Tests that Q1 adds (backend)

- One integration test per route against local Postgres (CLAUDE.md "a route no
  test calls has not been tested"), asserting the exact keys the UI reads.
- The Q3 cross-user test enumerates `app.routes`: every route with a path
  parameter or a body id is called as user B with user A's ids and must answer
  404 (E12 with only foreign ids: 404). It fails when a route is added without
  an entry in its allowlist of id-free routes.
- `test_frontend_select_columns_exist_in_the_live_schema`
  (`backend/tests/integration/test_schema_contract.py:1177`) is deleted; a new
  frontend unit test asserts no file under `frontend/src` (tests excluded)
  contains `.from(`, `.rpc(`, `supabase`, or imports `@supabase/supabase-js`.

---

## B. Auth

### B.1 Today

- Sign-in: `supabase.auth.signInWithPassword` (`routes/login/+page.svelte:20`);
  sign-up `supabase.auth.signUp` with `emailRedirectTo` (`routes/register/+page.svelte:31`).
- Session: supabase-js keeps access + refresh token in `localStorage`
  (`sb-<project ref>-auth-token`) and refreshes before expiry.
- Server: `get_current_user` (`backend/selko/api/deps.py:38-103`) creates a
  Supabase client **per request** and calls `auth.get_user(token)` — a network
  round trip to GoTrue on every API call. `get_authenticated_client`
  (`deps.py:106`) forwards the user's JWT to PostgREST for RLS.
- Rate-limit key: `get_user_id_or_ip` (`app.py:44-65`) decodes the JWT with
  `python-jose` **without verifying the signature** — any caller can choose
  whose budget to spend. Fixed in B.6.
- GoTrue settings (`supabase/config.toml [auth]`, local): `jwt_expiry = 3600`,
  `enable_refresh_token_rotation = true`, `refresh_token_reuse_interval = 10`,
  `minimum_password_length = 6`, `password_requirements = ""`,
  `[auth.email] enable_confirmations = false`, `[auth.rate_limit]
  sign_in_sign_ups = 30` (per 5 min per IP), `token_refresh = 150` (per 5 min per IP).
  **Production's settings are UNKNOWN from the repo:** read them in Q0 with
  `GET https://api.supabase.com/v1/projects/khahcozfbnpykspvatrg/config/auth`
  (network secret for `api.supabase.com` exists): fields `mailer_autoconfirm`,
  `password_min_length`, `jwt_exp`, `refresh_token_rotation_enabled`,
  `security_refresh_token_reuse_interval`, `sessions_timebox`,
  `sessions_inactivity_timeout`.
- Server-side user admin: `backend/selko/services/users.py` (`create_user`,
  `list_users`, `delete_user`, `get_user` via `auth.admin.*`), used by
  `scripts/seed_screenshot_data.py:22,57,81`, `scripts/seed_test_tokens.py:139`,
  `scripts/verify.sh:128-133` and `backend/tests/integration/conftest.py`,
  `test_integration_users.py`, `test_integration_e2e.py`,
  `test_integration_seed_fixtures.py`. `services/auth.py:25`
  `get_authenticated_client(config)` signs in the test user (tests/CLI only).
- **Account deletion today: there is no user-facing flow.** The privacy
  policy (`frontend/src/routes/privacy/+page.svelte:143-147`) says: email the
  contact address; "we delete it within 30 days". The operator deletes the
  `auth.users` row (cascade: `public.users` → every owned table, since every
  table's `user_id` references `public.users(id) ON DELETE CASCADE`), which
  `users.delete_user` (`services/users.py:117`) does. Storage objects are not
  cascaded by that delete.
- Profile row: trigger `on_auth_user_created` on `auth.users`
  (`20260122000001_auto_create_user_profile.sql`) inserts `public.users (id,
  email, display_name = split_part(email,'@',1))`. `public.users.id`
  `REFERENCES auth.users(id) ON DELETE CASCADE`
  (`20260121000001_create_users.sql:5`) — the only foreign key into `auth`.

### B.2 Dependencies (checked in `backend/pyproject.toml` and `uv.lock`)

- **`bcrypt` is not a dependency** (no entry in `uv.lock`). The standard
  library cannot verify bcrypt (`crypt` was removed in Python 3.13; `hashlib`
  has scrypt/pbkdf2 only), so verifying the existing `$2a$10$` hashes **requires
  adding `bcrypt` (pyca)** — the one new package in this section, and an owner
  decision. Its abi3 wheels cover CPython 3.14 on manylinux x86_64; the exact
  version is UNKNOWN until `uv add bcrypt` resolves it in Q5 (not run here).
  New hashes use the same scheme (`$2b$`, cost 10 — GoTrue's cost, ~70 ms on a
  shared vCPU; run in `asyncio.to_thread` so the loop never blocks).
- JWT: `pyjwt 2.13.0` is already locked (pulled in by `msal` and
  `supabase-auth`); `python-jose 3.5.0` is a direct dependency used only at
  `app.py:58`. Q5 lists `pyjwt` as a direct dependency (no new download: it is
  in the lock) and removes `python-jose` (and with it `ecdsa`/`rsa`/`pyasn1`
  if nothing else needs them).
- No SSE library is needed (C uses Starlette's `StreamingResponse`).

### B.3 Tables (Q5 migration on today's Postgres; the same tables in `0001_initial.sql` for Q6)

```sql
CREATE TABLE public.accounts (
    id               uuid PRIMARY KEY,             -- = auth.users.id = public.users.id
    email            text NOT NULL,                -- lowercased, trimmed
    password_hash    text NOT NULL,                -- bcrypt, copied verbatim from auth.users.encrypted_password
    email_confirmed_at timestamptz,
    created_at       timestamptz NOT NULL DEFAULT now(),
    updated_at       timestamptz NOT NULL DEFAULT now(),
    last_sign_in_at  timestamptz,
    disabled_at      timestamptz
);
CREATE UNIQUE INDEX accounts_email_key ON public.accounts (email);
ALTER TABLE public.accounts ENABLE ROW LEVEL SECURITY;          -- no policies: service only

CREATE TABLE public.auth_sessions (
    id           uuid PRIMARY KEY,                  -- the JWT `sid`
    user_id      uuid NOT NULL REFERENCES public.accounts(id) ON DELETE CASCADE,
    created_at   timestamptz NOT NULL DEFAULT now(),
    refreshed_at timestamptz NOT NULL DEFAULT now(),
    user_agent   text,                              -- first 200 chars; no IP stored
    revoked_at   timestamptz,
    revoked_reason text CHECK (revoked_reason IN ('logout','logout_global','reuse_detected','expired','password_changed','account_deleted'))
);
CREATE INDEX auth_sessions_user_active ON public.auth_sessions (user_id) WHERE revoked_at IS NULL;
ALTER TABLE public.auth_sessions ENABLE ROW LEVEL SECURITY;

CREATE TABLE public.auth_refresh_tokens (
    id          uuid PRIMARY KEY,
    session_id  uuid NOT NULL REFERENCES public.auth_sessions(id) ON DELETE CASCADE,
    token_hash  text NOT NULL,                      -- hex SHA-256 of the 32 random bytes
    parent_id   uuid REFERENCES public.auth_refresh_tokens(id) ON DELETE SET NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    rotated_at  timestamptz                         -- set when its child was issued
);
CREATE UNIQUE INDEX auth_refresh_tokens_hash_key ON public.auth_refresh_tokens (token_hash);
ALTER TABLE public.auth_refresh_tokens ENABLE ROW LEVEL SECURITY;
```
All three: `REVOKE ALL … FROM anon, authenticated`, `GRANT … TO service_role`
(CLAUDE.md: every new table enables RLS in the same migration).
SHA-256 without salt is correct for 256-bit random tokens (bcrypt is for
low-entropy secrets and would make every refresh cost 70 ms).

**Keeping the ids and foreign keys (Q5, in this order, one migration):**
1. Backfill: `INSERT INTO public.accounts (id, email, password_hash,
   email_confirmed_at, created_at, updated_at, last_sign_in_at) SELECT id,
   lower(email), encrypted_password, email_confirmed_at, created_at,
   updated_at, last_sign_in_at FROM auth.users WHERE deleted_at IS NULL AND
   encrypted_password IS NOT NULL ON CONFLICT (id) DO NOTHING`.
   Q0 also counts `auth.users` rows with `is_sso_user`, `is_anonymous`,
   `banned_until > now()`, `deleted_at`, `encrypted_password IS NULL` or not
   starting `$2a$`; each must be 0 or get an explicit rule.
2. Mirror until GoTrue is retired: trigger `accounts_mirror_auth_user` AFTER
   INSERT OR UPDATE OF email, encrypted_password, email_confirmed_at ON
   auth.users → upsert `accounts`. The name sorts before `on_auth_user_created`,
   so on an `auth.users` insert the `accounts` row exists before the profile
   insert that now references it (Postgres fires same-event triggers in name
   order). This covers a sign-up through an old web tab during the switch.
3. Repoint the profile FK: `ALTER TABLE public.users DROP CONSTRAINT
   users_id_fkey, ADD CONSTRAINT users_id_fkey FOREIGN KEY (id) REFERENCES
   public.accounts(id) ON DELETE CASCADE`. Every data table already references
   `public.users(id)`, so nothing else changes and every id survives into
   Q6/Q7 (SQLite has no `auth` schema; `0001_initial.sql` declares the same FK).
4. Sign-ups through Selko insert `accounts` and `public.users` (id, email,
   display_name = local part) in one transaction — the work
   `handle_new_user` does today.
The mirror trigger and `on_auth_user_created` are dropped at Q8 with GoTrue.

### B.4 Tokens

- **Access token**: JWT HS256, signed with `SELKO_JWT_SECRET` (≥ 32 random
  bytes; on Render an environment variable until cutover, then the server's
  secrets file; added to `config.py` next to `supabase_jwt_secret` at line 39).
  Header `kid` = `"1"`; `SELKO_JWT_SECRET_PREVIOUS` (kid `"0"`) is accepted for
  verification only, so the secret can be rotated without signing everyone out.
  Claims: `iss "selko"`, `aud "selko"`, `sub` user id, `sid` session id,
  `email`, `iat`, `exp = iat + 3600` (today's `jwt_expiry`), `typ "access"`.
  Verification checks signature, `exp` (30 s leeway), `iss`, `aud`, `typ`.
  **Stateless**: no database read per request, so a revoked session's access
  token keeps working until it expires (≤ 1 h); revocation is immediate for
  refresh and for `/live` streams (C.7). This replaces the per-request GoTrue
  call and its egress.
- **Refresh token**: 32 bytes from `secrets.token_urlsafe(32)`; only its
  SHA-256 is stored. Delivered **only** in a cookie (B.7), never in a body.
- **Rotation** (one transaction, row locked):
  1. Look up `token_hash`. Missing → `401 invalid_grant`.
  2. Session revoked → 401. Session idle longer than 30 days
     (`refreshed_at`) → revoke (`expired`), 401. (Today hosted GoTrue's
     inactivity timeout is UNKNOWN, see B.1; 30 days is the proposal, change
     it to match Q0's reading if Toni prefers.)
  3. `rotated_at IS NULL` → set it, insert a child (`parent_id`), set the
     cookie to the child, return a new access token.
  4. `rotated_at` within the last **10 s** (today's
     `refresh_token_reuse_interval`) → a concurrent refresh already rotated
     it (two tabs, or a retry): return a new access token and **do not touch
     the cookie** (the other response set the child; the browser's jar keeps
     it). This works only because the token is in a shared cookie jar.
  5. `rotated_at` older than 10 s → reuse of a spent token: revoke the whole
     session (`reuse_detected`), clear the cookie, `401 invalid_grant`.
  Known edge (same as GoTrue): a refresh whose response is lost and retried
  more than 10 s later signs that device out.

### B.5 Password and account rules

- Minimum 6 characters (today's `minimum_password_length` and the register
  page check, `register/+page.svelte:24`) — not raised, so no existing
  password is refused. Maximum **72 bytes UTF-8** (bcrypt's limit; Go's bcrypt,
  which GoTrue uses, rejects longer, so no stored password exceeds it) →
  `422 WEAK_PASSWORD` "Password must be at most 72 bytes".
- Email: trimmed, lowercased, `^[^@\s]+@[^@\s]+\.[^@\s]+$`, ≤ 254 chars.
- Unknown email on sign-in: bcrypt-verify against a fixed dummy hash so the
  response time does not reveal whether the account exists; one message for
  both cases: "Invalid login credentials" (GoTrue's text, which the login page
  shows verbatim and `routes/login/__tests__/page.test.js:121-130` pins).
- `disabled_at` set → same 400 as wrong password (no account-state oracle).
- **Sign-up confirmation**: local config has confirmations off; production is
  UNKNOWN (Q0, `mailer_autoconfirm`). Plan for both:
  - off (expected): `POST /auth/signup` creates the account, sets
    `email_confirmed_at = now()`, returns 201; the register page keeps showing
    its success message and the sign-in link (unchanged UI).
  - on: the account is created unconfirmed, a one-time token (random, SHA-256
    stored, 24 h) is mailed through Resend (`ResendOperationalNotifier`,
    `services/email_sync_health.py:59`, already the API's mailer), and one more
    endpoint `GET /auth/confirm?token=…` sets `email_confirmed_at` and
    redirects to `/login?confirmed=1`; sign-in refuses unconfirmed accounts
    with `400 email_not_confirmed` (a message `errors.js:40` already maps).
- No password reset or change exists in the web today (no route for it);
  none is added here. Recovery stays operator-only, as it effectively is now.

### B.6 Server dependency

`get_current_user` (`deps.py:38`) becomes: parse `Authorization: Bearer`, verify
the Selko JWT locally, return `CurrentUser(id=sub, email, token, session_id=sid)`
— same dataclass plus `session_id`, so every existing route keeps working.
Missing/invalid → `401 UNAUTHORIZED` with `WWW-Authenticate: Bearer` (unchanged).

**Transition (Q5 only):** a token whose `iss` is not `"selko"` falls back to
today's `auth.get_user` path, so tabs still running the old web build keep
working. The fallback is removed 7 days after the new web build is live.
Prerequisite: no route may still use `get_authenticated_client` (a Selko token
is meaningless to PostgREST). Q1 builds the new endpoints without it; **Q3
moves the existing users (`routes/emails.py`, `routes/events.py`,
`routes/integrations.py`; 25 call sites of `get_authenticated_client` /
`get_service_role_client` in `backend/selko`) to the shared service client
with explicit `user_id` filters and deletes `get_authenticated_client`.** The
`reprocess_email` RPC already takes `p_user_id` (`emails.py:55-58`).

`get_user_id_or_ip` (`app.py:44`) verifies the token with `SELKO_JWT_SECRET`
before using `sub`; an unverifiable token is keyed by IP.

### B.7 Where the web keeps tokens (decision)

**Access token in memory (a module variable in the new client), refresh token
in an `HttpOnly; Secure; SameSite=Strict; Path=/auth` cookie set by the API**
(name `selko_refresh`, host-only — no `Domain` attribute — on
`api.selkoapp.com`; `Secure` off only when `config.environment ==
"development"`, so http://localhost works in Safari too).

Reasons:
- An XSS can read `localStorage`; with today's storage it walks away with a
  refresh token that renews forever. With this split it gets at most a 1 h
  access token while the page is open. The app has no CSP today (none in
  `frontend/src/app.html` or `static/`), so this is the only containment.
- The 10 s reuse window (B.4 step 4) is only safe with a shared cookie jar:
  with `localStorage` two tabs race on the same stored token and whichever
  loses writes a stale one back.
- `Path=/auth` means the cookie is never sent to data endpoints, so those stay
  pure Bearer and immune to CSRF.
- It survives the cutover unchanged: `selkoapp.com` and `api.selkoapp.com` are
  the same *site*, so `SameSite=Strict` cookies are sent on
  `fetch(…, {credentials:'include'})`; local dev (`localhost:5173` →
  `localhost:8000`) is same-site too. CORS already has `allow_credentials=True`
  with an explicit origin list (`app.py:265-271`).
- Cost: one refresh request on every page load (B.9), and a reload while
  offline cannot restore the session until the network is back.

Rejected: tokens in `localStorage` (as today; XSS-exfiltrable, races between
tabs); both tokens in cookies (would make every data endpoint
CSRF-sensitive and need CSRF tokens everywhere).

### B.8 CSRF and CORS

- Data endpoints: Bearer only, no cookie → no CSRF.
- Cookie-reading endpoints (`/auth/token` refresh grant, `/auth/logout`) and
  cookie-setting ones (`/auth/token` password grant, `/auth/signup`): require
  `Origin` ∈ `config.allowed_origins` (403 otherwise, including a missing
  `Origin`), and `Content-Type: application/json` (forces a CORS preflight for
  cross-origin callers). `SameSite=Strict` is the third layer. The `Origin`
  check on the password grant also blocks login CSRF (an attacker signing the
  victim into the attacker's account).
- `allow_headers` (`app.py:270`) already includes `Authorization`,
  `Content-Type`, `Accept`; nothing else is needed. Production
  `ALLOWED_ORIGINS` must contain `https://selkoapp.com` (verify the Render
  value in Q5; UNKNOWN from the repo).

### B.9 Endpoints

All under `routes/auth.py`, `prefix="/auth"`.

**E20. `POST /auth/signup`**
- Body `{email, password}`. Origin check.
- `201 {user: {id, email, created_at}, confirmation_required: bool}`. No tokens
  (the register page sends the user to sign in, as today).
- `409 USER_ALREADY_EXISTS` "User already registered" (GoTrue's text when
  confirmations are off; with confirmations on, answer 201 regardless, as GoTrue
  does, to avoid enumeration). `422 WEAK_PASSWORD` / `INVALID_REQUEST`.
- Rate limit: `5/hour` per IP.

**E21. `POST /auth/token`**
- Body `{grant_type: "password", email, password}` or `{grant_type: "refresh_token"}` (token read from the cookie only). Origin check.
- `200 {access_token, token_type: "bearer", expires_in: 3600, expires_at: <unix>, user: {id, email}}`; password grant creates an `auth_sessions` row and sets the cookie (`Max-Age` 30 days, refreshed on rotation); updates `accounts.last_sign_in_at`.
- Password grant errors: `400 INVALID_CREDENTIALS` "Invalid login credentials", `400 email_not_confirmed` (only if confirmations on). Refresh grant: `401 INVALID_GRANT` (and `Set-Cookie` clearing it).
- Rate limits: password grant `10/minute` per IP **and** `5/minute` per email (second `@limiter.limit` with a key function reading the body's email); refresh `30/minute` per IP (GoTrue: 150 per 5 min).

**E22. `POST /auth/logout`**
- Body `{scope: "local" | "global"}` (default `"global"`, matching supabase-js
  `signOut()`'s default today — so "Log out" keeps signing out every device;
  switching to `local` is a one-word product choice). Origin check.
- Session = the access token's `sid` if a valid Bearer is sent, else the
  cookie's session. `local` revokes that session; `global` every active session
  of the user (`logout_global`). Publishes `session_revoked` on the bus (C.7).
- `204`, `Set-Cookie: selko_refresh=; Max-Age=0; Path=/auth`. Idempotent: with
  no valid session it still clears the cookie and answers 204.
- Rate limit: default.

**E23. `GET /auth/user`**
- Bearer. `200 {id, email, created_at, last_sign_in_at}`. `401`.
- Rate limit: default. (Used by tests and the e2e setup; the web gets the user
  from E21.)

(Conditional, only if Q0 finds confirmations on: `GET /auth/confirm?token=` → 302.)

**Account deletion:** no endpoint (no UI asks for it; the policy promises an
operator process). Replacement for `services/users.delete_user`:
`selko.services.accounts.delete_account(user_id)` deletes the `accounts` row
(cascade to `public.users` and every owned table, and to sessions) and, from
Q6, removes `attachments/<user_id>/`. Run as an operator command inside the
image (`python -m selko.admin delete-account <uuid>`), confirmed by an exact
uuid argument; in Q5 also delete the `auth.users` row (the mirror is one-way).

**`services/users.py` and `services/auth.py` after Q5:** `create_user(config,
email, password, display_name=None, auto_confirm=False)` keeps its signature
and return value but writes `accounts` + `public.users` (bcrypt) instead of
`auth.admin.create_user`, so `scripts/seed_screenshot_data.py`,
`scripts/verify.sh` and the integration conftest keep working; `list_users`,
`get_user`, `delete_user` read/write `accounts`. `services/auth.py`'s
`get_authenticated_client` (test user sign-in) and `get_current_user_id` are
deleted with the last test that uses them; `scripts/seed_test_tokens.py:139`
switches to `list_users`.

### B.10 Session restore, refresh, sign-out in the web

- Boot (`initAuth`, replacing `stores.js:31`): `loading=true`; `POST /auth/token
  {grant_type:'refresh_token'}` with `credentials:'include'`. 200 → keep the
  access token in memory, `user.set(response.user)`; 401 → `user.set(null)`
  (the app layout then redirects to `/login?next=…`, `routes/app/+layout.svelte:20-34`);
  network failure → keep `loading` false, `user` null **and** set an
  `authUnavailable` store so the layout shows "Can't reach Selko" with Retry
  instead of bouncing a signed-in user to the login page.
- Proactive refresh: a timer at `expires_at - 60 s`; also on any `401` from
  an API call, one single-flight refresh then one retry of that request.
- Auth events replace `onAuthStateChange`: the auth module exposes
  `onAuthChange(cb)` with `SIGNED_IN`, `TOKEN_REFRESHED`, `SIGNED_OUT`;
  live-updates reconnects on `TOKEN_REFRESHED` (C.5).
- Other tabs: a `BroadcastChannel('selko-auth')` message on sign-in/out makes
  every tab refresh or drop its in-memory token at once (instead of failing on
  their next request).
- Sign-out (`app/+layout.svelte:72-76`, `settings/+page.svelte:355-358`):
  `liveUpdates.stop()`, `POST /auth/logout`, drop the token, broadcast,
  `goto('/login')`.

---

## C. Live updates

### C.1 Today (read in full)

`frontend/src/lib/live-updates.js` (249 lines):
- One private Broadcast channel per signed-in user, topic
  `user:<uid>:selko-changes`, event `invalidate` (lines 162–167), authorised by
  `realtime.setAuth(access_token)` (154–160) and re-authorised on token refresh
  (`refreshAuth`, 39–46, called from `stores.js:39`).
- `handleInvalidate` (125–136) accepts the wrapped (`{payload:{…}}`) or bare
  form, drops anything whose `resource` is not in `events, event_sources,
  event_change_proposals, calendar_work_items, emails, integrations`.
- Per-resource debounce 350 ms with trailing coalescing and an in-flight guard
  (`scheduleRefresh`, 79–108).
- `catchUp()` (115–123) emits a synthetic `CATCHUP` invalidation for every
  subscribed resource; called on `SUBSCRIBED` (172–175) and by the app layout on
  visibility, focus and online (`routes/app/+layout.svelte:50-60`).
- Reconnect: on `CHANNEL_ERROR`/`TIMED_OUT`/`CLOSED` (unless `intentionalStop`)
  `delay = min(1000·2^attempts, 60000)` with the counter at module scope
  (21–24, 177–198; the scope is pinned by `live-updates.test.js`).
- Subscribers: `routes/app/+page.svelte:258-263` (events, event_sources,
  event_change_proposals, calendar_work_items, integrations),
  `routes/app/history/+page.svelte:107-126` (events, event_sources,
  event_change_proposals, calendar_work_items, emails). `integration_recoveries`
  is polled instead (`ConnectionRecovery.svelte:95-96`).

Server side, final definitions:
- `public.broadcast_user_ui_change(p_user_id, p_resource, p_operation, p_entity_id)`
  (`20260811000001_broadcast_fanout_collapse.sql:7-44`): returns if user is
  NULL; a transaction-local GUC `selko.bc_<uid>_<resource>` makes it fire
  **once per (transaction, user, resource)**; payload `{resource, operation,
  occurred_at: (now() AT TIME ZONE 'utc')::text}` — `entity_id` deliberately
  omitted; `realtime.send(payload, 'invalidate', topic, true)`.
- Triggers calling it:

| Trigger | Table / event | Defined |
|---|---|---|
| `trg_events_broadcast_ins/upd/del` | events: INSERT; UPDATE OF review_status, title, start_datetime, end_datetime (body re-checks IS DISTINCT FROM); DELETE | `20260829000001_delete_events_status.sql:523-546` |
| `trg_event_sources_broadcast_ins` | event_sources INSERT (user from `events`) | `20260809000003_live_ui_broadcast.sql:104-107`, function replaced at `20260826000001_remove_legacy_event_state.sql:711-722` |
| `trg_event_sources_broadcast_upd` | event_sources UPDATE OF source_origin | `20260826000001…:724-726` |
| `trg_emails_broadcast_upd` | emails UPDATE OF processing_status, processing_error | `20260809000003…:114-129` |
| `trg_integrations_broadcast_upd` | integrations UPDATE OF status | `20260809000003…:131-145` |
| `trg_event_change_proposals_broadcast` | proposals INSERT/UPDATE/DELETE | `20260829000001…:548-573` |
| `trg_calendar_work_items_broadcast` | work items INSERT/UPDATE/DELETE | `20260829000001…:559-577` |

- RLS on `realtime.messages`: `live_ui_broadcast_select_own_topic`
  (`20260809000003…:148-163`).
- There is no `pg_notify` for UI today; `pg_notify('selko_work', <type>)` is
  worker wake-up only, consumed by `WorkListener` (`services/pg.py:141`,
  channel `selko_work`, payloads `email_pending, event_approved, item_pending,
  attachment_pending, heartbeat`).

### C.2 E24. `GET /live` — authentication (decision)

**Streaming `fetch` with the normal `Authorization: Bearer` header**, parsed as
SSE by ~40 lines in the client; not `EventSource`, not a ticket.

Reasons: the same `get_current_user` dependency as every other route (one auth
path, covered by Q3's cross-user test); no token in a URL, where it would land in
proxy/access logs and browser history; no ticket table, ticket TTL or second
round trip. `fetch` streaming (`response.body.getReader()`) is supported by every
browser the app supports. What `EventSource` would have given for free —
reconnect and `Last-Event-ID` — is replaced by today's own backoff and
`catchUp()` (C.5), which the app already relies on.

Rejected: short-lived ticket (`POST /live/ticket` → `?ticket=`): extra endpoint
and state, token-in-URL problem shifted to the ticket, and a second
failure point on every reconnect.

### C.3 Wire format

```
HTTP/1.1 200
Content-Type: text/event-stream; charset=utf-8
Cache-Control: no-cache, no-transform
X-Accel-Buffering: no
Connection: keep-alive

event: ready
data: {"user_id":"<uuid>","heartbeat_seconds":25}

event: invalidate
data: {"resource":"events","operation":"UPDATE","occurred_at":"2026-11-25T18:04:05.123456+00:00"}

: ping

```
- `invalidate` data is exactly today's inner payload: `resource`,
  `operation` (`INSERT|UPDATE|DELETE`), `occurred_at`; no `entity_id` (as
  today since `20260811000001`). `occurred_at` changes from Postgres's
  `YYYY-MM-DD HH:MM:SS.ffffff` text to ISO 8601 with offset — no consumer reads
  it except a `console.debug`.
- `resource` ∈ the six names above (the client keeps its allowlist).
- `ready` is sent first; the client treats it as today's `SUBSCRIBED`.
- Heartbeat: an SSE comment `: ping` every 25 s (under the 60 s / 100 s idle
  timeouts of common proxies; Render's and Cloudflare's included).
- `event: reauth` (no data) just before the server closes a stream at the
  access token's `exp`, and `event: revoked` when the session is signed out.

### C.4 Server

- `selko/services/live_bus.py` (new): `LiveBus` with `subscribe(user_id,
  session_id) -> Subscription` (an `asyncio.Queue(maxsize=64)` plus a pending
  set), `publish(user_id, resource, operation)` (non-blocking, from any task;
  from a thread via `loop.call_soon_threadsafe`), `revoke_session(session_id)`,
  `close_all()`. Per-user filtering is by construction: a subscription
  receives only its own `user_id`'s publishes; the user is the verified token
  subject, never a client-chosen topic.
- Coalescing: each subscription keeps a pending set of resources; a burst of
  N publishes for one resource becomes one `invalidate` (the per-transaction
  guard of `broadcast_user_ui_change`, kept in Postgres in Q2, does the same at
  the source).
- Overflow: if the queue is full, the subscription is marked overflowed and the
  next write is one `invalidate` per allowed resource with `operation:
  "CATCHUP"` (the client already handles `CATCHUP`), then normal flow resumes.
  Nothing blocks a publisher.
- Route (`routes/live.py`): `StreamingResponse` over an async generator that
  awaits `queue.get()` with a 25 s timeout (timeout → `: ping`), ends at token
  `exp` (`reauth`) or on `revoke_session` (`revoked`), and unsubscribes in
  `finally` (Starlette cancels the generator on client disconnect).
- Limits: 5 concurrent streams per user (a 6th answers `429`; the client
  falls back to focus/visibility catch-up); 200 per process (`503`); stream
  lifetime ≤ the token's remaining validity. Rate limit `30/minute` per user
  (reconnects are backoff-bounded). Memory per stream: one task + a ≤ 64-item
  queue, a few KB.
- Shutdown: lifespan calls `live_bus.close_all()` first so open streams end
  and uvicorn's graceful shutdown does not wait on them.
- CORS: preflight passes today's config (Authorization is allowed).

**Source of publishes:**
- **Q2 (today's database):** migration `2026112xxxxxxx_live_ui_pg_notify.sql`
  changes `broadcast_user_ui_change` to call **both** `realtime.send(…)` (old
  web builds still subscribed) and `pg_notify('selko_ui',
  json_build_object('u', p_user_id, 'r', p_resource, 'o',
  p_operation)::text)`, keeping the GUC guard. A `UiListener` in
  `services/pg.py` (its own connection, like `WorkListener`, same
  session-mode assertion, heartbeat and reconnect) LISTENs on `selko_ui` and
  calls `live_bus.publish`. It starts in the lifespan **whenever
  `SUPABASE_DB_URL` is set, independent of `ENABLE_BACKGROUND_PROCESSING`**
  (live updates are an API feature, not a worker one). After the new web has
  served for 7 days with no Realtime connections (Supabase dashboard → Realtime
  → connections; UNKNOWN whether the Management API exposes the count), a
  second migration drops the `realtime.send` call and the
  `live_ui_broadcast_select_own_topic` policy.
- **Q6 (SQLite):** the data layer publishes after commit for exactly the
  table/column sets of the trigger table in C.1 (a test enumerates that table
  against the data-layer publish sites, so a new writer cannot forget it), and
  `UiListener` and the 11 broadcast/notify triggers go away.

### C.5 Client

`frontend/src/lib/live-updates.js` keeps its public API (`start(uid)`, `stop()`,
`subscribe`, `catchUp`, `getStatus`, `__resetForTests`) and its debounce,
allowlist and module-scope `rejoinAttempts`. Changes:
- `start(uid)`: `AbortController`; `fetch(API + '/live', {headers:
  {Authorization: 'Bearer ' + getAccessToken()}, signal})`; read the body
  stream, split on blank lines, parse `event:`/`data:` fields, ignore comments
  except to reset a 60 s silence watchdog.
- `ready` → `rejoinAttempts = 0; catchUp()` (today's `SUBSCRIBED`).
- `invalidate` → `handleInvalidate(JSON.parse(data))`.
- End of stream, network error, watchdog, `reauth` → unless `intentionalStop`,
  reconnect after `min(1000·2^attempts, 60000)` ms + 0–20 % jitter.
- `401` → `auth.refresh()` then reconnect; refresh failure → stop (auth module
  signs out). `revoked` → stop. `429`/`503` → backoff as above.
- `refreshAuth(token)` (called on `TOKEN_REFRESHED`) aborts and restarts the
  stream so the server's lifetime bound follows the new token.
- No server-side replay: on every (re)connect the client catches up from the
  API, as today; the database stays the source of truth and the stream a hint.

---

## D. Web client changes

### D.1 New modules

- `frontend/src/lib/api/client.js` (replaces `$lib/supabase.js` and the
  private `getAccessToken`/`apiRequest` of `lib/api/backend.js:14-67`):
  `getApiBaseUrl()`, `apiFetch(path, {method, body, query, signal})`
  (Bearer, JSON, 30 s timeout as today, 401 → single-flight refresh + one retry,
  returns `{data, error}` with `error = {message, status, code}` via the moved
  `parseApiError`), `getAccessToken()`.
  In D.4 step 2 its token still comes from `supabase.auth.getSession()`; step 4
  swaps that one function to the in-memory token.
- `frontend/src/lib/auth.js` (new, step 4): `signIn(email, password)`,
  `signUp(email, password)`, `signOut()`, `restoreSession()`, `refresh()`,
  `onAuthChange(cb)`, the expiry timer and the `BroadcastChannel`.

### D.2 Every file that changes

| File | Change | Step |
|---|---|---|
| `src/lib/api/backend.js` | import `apiFetch`/`getApiBaseUrl` from `client.js`; delete local `getAccessToken`, `apiRequest`, `parseApiError` (moved); `startOAuthRedirect` (line 516) uses `getAccessToken` from `client.js` | 2 |
| `src/lib/services/events.js` | `fetchPendingEventsWithSources` → E1; `fetchActivityEvents` → E2 (clamp limit 500, map `{items,total}` → `{data,count}`); `getEvent` → E3; `updateEvent` → E4; `updateEventStatus` → E5/E6. Delete `fetchPendingEvents`, `fetchEvents`, `deriveEventStatus`, `withDeliveryStatus`, `latestCalendarWorkItem`. Keep `pendingEventProposal`, `isNewReviewEvent`, `isChangeReviewEvent`, `isHistoryEvent` (pure helpers used by pages) | 2 |
| `src/lib/services/event-sources.js` | delete | 2 |
| `src/lib/services/email-history.js` | `fetchEmailHistory` → E7, `fetchEmailProcessingState` → E9 | 2 |
| `src/lib/services/emails.js` | `getEmail` → E8; delete `fetchEmails`, `updateEmailReadStatus` | 2 |
| `src/lib/services/attachments.js` | `fetchAttachments` → E10; delete `getAttachment`, `downloadAttachment`, `getAttachmentUrl` | 2 |
| `src/lib/services/integrations.js` | `fetchIntegrations` → E11 (`count: data.length`), `disconnectIntegrations` → E12, `fetchCalendarRecovery` → E13 (`data = body.recovery`); delete the four DEAD functions | 2 |
| `src/lib/services/email-folders.js` | `fetchEmailFolders` delegates to `backend.fetchEmailFolders`; drop the supabase import and the `typeof supabase.from` guard | 2 |
| `src/lib/services/sender-rules.js` | `fetchSenderRules` → E14, `createSenderRule` → E15 (no `getUser`, no `user_id`), `deleteSenderRule` → E16, `ignoreSenderRetroactive` → E17; delete `findMatchingRule` | 2 |
| `src/lib/services/calendar-settings.js` | `getCalendarSettings` → E18 (`data = body.settings`), `updateCalendarSettings` → E19 (no `getUser`, no `updated_at`) | 2 |
| `src/lib/services/index.js` | drop re-exports of deleted functions; fix the header comment ("handle direct Supabase queries") | 2 |
| `src/lib/errors.js` | step 2: unchanged (wrappers return API errors already in `{message, code}` form); step 5: rename `SupabaseError`/`parseSupabaseError` to `AppError`/`toAppError`, drop the Postgres/PGRST codes, keep the auth codes | 2, 5 |
| `src/lib/live-updates.js` | SSE client (C.5) | 3 |
| `src/lib/stores.js` | `initAuth` → `auth.restoreSession()` + `onAuthChange`; add `authUnavailable` store; drop the supabase import and JSDoc type (use `{id: string, email: string}` typedef in `types.js`) | 4 |
| `src/routes/login/+page.svelte` | `auth.signIn`; show `error.message` | 4 |
| `src/routes/register/+page.svelte` | `auth.signUp`; drop `emailRedirectTo` | 4 |
| `src/routes/app/+layout.svelte` | `auth.signOut()`; show the `authUnavailable` retry state | 4 |
| `src/routes/app/settings/+page.svelte` | line 6 import and line 356 → `auth.signOut()`; line 16 import unchanged (module internals changed) | 4 |
| `src/routes/+page.svelte` | JSDoc type only | 4 |
| `src/lib/supabase.js` | delete | 5 |
| `package.json` | remove `@supabase/supabase-js` (line 41) and lockfile entries | 5 |
| `.env.example`, `frontend/.env` (generated) | remove `VITE_SUPABASE_URL`, `VITE_SUPABASE_ANON_KEY`; keep `VITE_API_URL` | 5 |
| `vitest.config.js:23-24` | remove the two env stubs | 5 |
| `.github/workflows/frontend-tests.yml:70-71` | stop writing the placeholders | 5 |
| `scripts/cloud-setup.sh:317-318` | stop writing them into `frontend/.env` | 5 |
| `docs/screenshot-guide.md:28` | update | 5 |
| Render web service env (dashboard) | remove the two variables after step 5 deploys | 5 |

No Svelte component other than the five above changes: every page consumes the
service modules, whose names and `{data, error, count}` returns stay the same.

### D.3 Tests

Tests that mock `$lib/supabase.js` (10 files; the spec's figure of 13 is not
reproducible by grep — UNKNOWN how it was counted, possibly including
`Navbar.test.js`, which only mentions Supabase in a comment at line 23, and the
event-detail page test, which mocks the DEAD `event-sources.js`):

| Test file | Stubs today | Must stub instead |
|---|---|---|
| `src/lib/services/__tests__/events.test.js` (537 lines) | chained `supabase.from(...).select/eq/in/or/order/range/single`, `rpc` | `globalThis.fetch` (or `vi.mock('$lib/api/client.js')` `apiFetch`); assert method, path, query (`limit`, `offset`) and body; drop the `deriveEventStatus` cases (moved to `backend/tests/test_events.py`) |
| `src/lib/services/__tests__/integrations.test.js` (262) | `from('integrations'/'integration_recoveries')` | `apiFetch` for E11–E13; drop tests of deleted functions |
| `src/lib/services/__tests__/emails.test.js` (247) | `from('emails')` | `apiFetch` for E8; drop `fetchEmails`/`updateEmailReadStatus` tests |
| `src/lib/__tests__/email-history.test.js` (39) | `mockSupabase` + `$lib/api/backend.js` | `apiFetch` for E7/E9; keep the backend mock for reprocess |
| `src/lib/__tests__/services.test.js` (341) | `mockSupabase` across services | `apiFetch` per service (sender rules E14–E17, settings E18–E19, attachments E10) |
| `src/lib/__tests__/backend-api.test.js` (374) | `supabase.auth.getSession` for the token | `vi.mock('$lib/api/client.js')` `getAccessToken` (step 2), later the auth module; `fetch` stays mocked as today |
| `src/lib/__tests__/live-updates.test.js` (164) | `supabase.channel/removeChannel/realtime.setAuth` | a `fetch` mock returning a `ReadableStream` of SSE frames; keep assertions on backoff doubling with module-scope attempts, no rejoin after `stop()`, `catchUp` on `ready`, re-auth reconnect on `refreshAuth` |
| `src/routes/app/__tests__/layout.test.js` (162) | `supabase.auth.signOut/getSession`, realtime | `vi.mock('$lib/auth.js')` `signOut`; `vi.mock('$lib/live-updates.js')` |
| `src/routes/app/settings/__tests__/page.test.js` (543) | `supabase.auth.signOut` (+ service mocks) | `vi.mock('$lib/auth.js')`; the `email-folders.js` mock stays |
| `src/routes/login/__tests__/page.test.js` (190) | `supabase.auth.signInWithPassword` | `vi.mock('$lib/auth.js')` `signIn`, same assertions (`'Invalid login credentials'`, `next` redirect) |

Also: `src/routes/app/events/[id]/__tests__/page.test.js` mocks
`$lib/services/event-sources.js` — remove that mock when the file is deleted.
`tests/fixtures/mock-supabase.js` (95 lines) is imported by nothing — delete.
Tests that mock only service modules (`routes/app/__tests__/page.test.js`,
`history/__tests__/page.test.js`, `SenderRulesPanel.test.js`,
`ConnectionRecovery.test.js`, `Navbar.test.js`) need no change. New: a
`register` page test (none exists), `client.js` tests (refresh single-flight,
401 retry once, timeout), `auth.js` tests (restore 200/401/network,
BroadcastChannel), and the "no supabase in src" guard (A.6).
E2E `tests/e2e/auth.setup.ts` signs in through the UI; `storageState` captures
the refresh cookie as it captured `localStorage`, so it keeps working. The e2e
user `test@selko.local` (`scripts/cloud-setup.sh:275`) is created through
`services/users.create_user`, which B.9 keeps working.

### D.4 Order — each step ships to today's production first

1. **Backend Q1** — E1–E19 + the `ignore_sender` migration, on hosted
   Supabase through the shared service client, each with an integration test.
   Web unchanged. Verify on production: each new route answers for the owner and
   404s for another user (the Q3 test runs in Tier 1). Deploy.
2. **Web Q1** — `client.js` (token still from `supabase.auth.getSession`),
   every service module switched, dead code deleted, tests updated. supabase-js
   remains only for auth and Realtime. Deploy; confirm in production logs
   (`request_metrics` routes) that the new routes carry the traffic and Supabase
   egress for `events`/`emails` PostgREST paths from browsers drops to zero.
   7 days later: drop the old 2-arg `ignore_sender_and_reject_pending`.
3. **Q2 live** — migration (dual `realtime.send` + `pg_notify`), `UiListener`,
   `LiveBus`, `/live` (backend deploy); then the web SSE client (web deploy).
   7 days later: migration removing `realtime.send` and the Realtime policy.
4. **Q3 then Q5 auth** — Q3: existing routes off `get_authenticated_client`,
   403 → 404. Q5: `bcrypt` + `pyjwt` dependencies, `accounts`/sessions
   migration with backfill + mirror trigger + FK repoint, `/auth/*`,
   dual-issuer `get_current_user`, `SELKO_JWT_SECRET` set on Render (backend
   deploy, verify `POST /auth/token` with an existing password against a
   throwaway account that the test then deletes). Then the web: `auth.js`,
   stores, login/register/layout/settings (web deploy). Every signed-in user
   signs in once with the same password. 7 days later: remove the GoTrue
   fallback in `get_current_user`.
5. **Cleanup** — delete `supabase.js`, the npm dependency, env vars, CI/setup
   lines; rename the error class. After this the web bundle contains no
   Supabase code and talks only to `VITE_API_URL`.

Because the web only ever sees Selko's endpoints from step 2 on, Q6 (SQLite
under `client_data.py`, `accounts`, `LiveBus`) changes nothing the browser can
observe; the route tests and the response-shape pins are what prove that.

---

## E. Attachments

### E.1 Today

- Web: `downloadAttachment` / `getAttachmentUrl`
  (`frontend/src/lib/services/attachments.js:65-95`) call Storage directly, but
  **nothing calls them** — the event page lists attachment filenames only
  (`events/[id]/+page.svelte:271-310`). No user can download an attachment
  today.
- Backend: bucket `attachments` (`config.storage_bucket_attachments`), private,
  50 MiB per object (`supabase/config.toml:110`); key
  `{user_id}/{12 hex}_{ascii-sanitised filename}` (`services/attachments.py:175-197`);
  `attachments.storage_path`, `mime_type`, `size_bytes`, `ingestion_status`
  (`pending|processing|stored|unsupported|retry|dead_letter`,
  `20260801000001_polling_email_ingestion_v2.sql:140`). The worker reads bytes
  back in `services/event_processing.py:459-478`.

### E.2 Decision

The dead client functions are deleted in D.4 step 2 (no endpoint is needed to
keep today's behaviour). The endpoint below is specified so Q6 can serve files
from `attachments/` with the same contract; ship it **when** the UI gets a
download link (a product decision for Toni), not before — an unused route is
untested surface.

### E.3 E25. `GET /attachments/{attachment_id}/content`

- Auth: Bearer (the link is fetched with `apiFetch` and saved through
  `URL.createObjectURL(blob)` + a temporary `<a download>`, so no token goes in a
  URL and no signed-URL machinery is needed).
- Ownership: `SELECT … FROM attachments WHERE id = :id AND user_id = :uid`;
  missing or not owned → `404 ATTACHMENT_NOT_FOUND`. `ingestion_status <>
  'stored'` or `storage_path IS NULL` → `409 ATTACHMENT_NOT_STORED`.
- Q1–Q5 (Supabase Storage): stream the object with the shared service client's
  Storage download — supabase-py returns bytes in memory, so cap at the 50 MiB
  bucket limit and accept the copy; Q6: `FileResponse` over
  `attachments/<user_id>/<attachment_id>` after resolving the path and
  checking it stays under `attachments/<user_id>/` (no traversal through a
  crafted `storage_path`), streamed in 64 KiB chunks.
- Headers: `Content-Type` = stored `mime_type` if it is in the worker's
  allowlist (`20261019000001_attachment_bucket_allowlist_matches_worker.sql`),
  else `application/octet-stream`; `Content-Disposition: attachment;
  filename="<ascii fallback>"; filename*=UTF-8''<percent-encoded original
  filename>` (always `attachment`, never `inline`, so an HTML or SVG attachment
  can't run in Selko's origin); `X-Content-Type-Options: nosniff`;
  `Content-Security-Policy: sandbox`; `Content-Length` = `size_bytes` when known;
  `Cache-Control: private, no-store` (email content; no shared or disk cache);
  `ETag: "<content_hash>"` when present, honouring `If-None-Match` → `304`.
- Rate limit: `30/minute` per user. Errors: 401, 404, 409, 500 (storage
  read failed; logged with the attachment id only).
- Egress: Q1–Q5 downloads are attributed by the existing Supabase egress hook
  on the shared client.

---

## Endpoint count

25 new endpoints: 19 data (E1–E19), 4 auth (E20–E23; plus a conditional 26th,
`GET /auth/confirm`, only if Q0 finds email confirmation on), 1 live (E24), 1
attachment download (E25, deferred until a UI link exists). One existing route
(`GET /integrations/{provider}/folders`) is reused instead of duplicated.
