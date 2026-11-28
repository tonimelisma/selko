# Requirements: Calendar delivery

How Selko delivers approved events to Google Calendar and Outlook Calendar through
`calendar_work_items`, routes each write to a provider, mirrors the user's calendars, detects drift,
recovers OAuth-blocked work after a reconnect, and stores the user's calendar settings.

## Work items and queueing

- **SEL-300** When calendar work is queued for an event, Selko shall, in one transaction, mark the
  event's `pending` or `processing` `calendar_work_items` row `superseded` and insert a new `pending`
  row whose `generation` is one more than the highest generation of any of the event's items, with
  `attempts` 0 and `max_attempts` 3. [verified]
- **SEL-301** Selko shall leave `events.review_status` unchanged when it queues calendar work.
  [verified]
- **SEL-302** If an `upsert` is queued for an event whose `review_status` is `rejected` or
  `cancelled`, then Selko shall refuse it and queue nothing, while a `cancel` for such an event shall
  still be queued. [verified]
- **SEL-303** If queued work has an action other than `upsert` or `cancel`, or an `upsert` has no
  `desired_event`, then Selko shall refuse it with an invalid-argument error. [verified]
- **SEL-304** If calendar work is queued for an event the given `user_id` does not own, then Selko
  shall refuse it and queue nothing, and the database shall reject any `calendar_work_items` row
  whose `user_id` differs from its event's owner. [verified]
- **SEL-305** When a calendar work item is committed, Selko shall wake the calendar workers with the
  `event_approved` signal, and shall send no signal when the enqueue rolls back. [verified]
- **SEL-306** When a user accepts an event (`POST /events/{id}/accept`) or applies its pending change
  proposal (`POST /events/{id}/apply-change`), Selko shall queue an `upsert` calendar work item for
  it. [verified]
- **SEL-307** When an event is undone, Selko shall set its `review_status` to `pending_review` and,
  when the undo carries calendar work (a `cancel`, with `force_overwrite` when the user forced it),
  queue that work in the same transaction. [verified]
- **SEL-308** When a cancellation is queued for an event, Selko shall first move a `pending_review`
  event to `active`, return `already_cancelled` without queueing for an already `cancelled` event,
  and refuse a `rejected` event or one with a `processing` item. [verified]
- **SEL-309** Selko shall derive an event's delivery status from its latest non-superseded work item
  (`approved`, `syncing`, `synced`, `sync_failed`, `cancel_queued`, `cancelled`), reporting an item
  blocked with `oauth_required` or `oauth_scope_required` as `approved`, not `sync_failed`.
  [verified]

## Claim and lease

- **SEL-310** When a calendar worker claims work, Selko shall take the oldest `pending` item (by
  `created_at`) with `attempts` below `max_attempts` and `next_retry_at` unset or past, set it
  `processing` with `locked_by`, `locked_until` = now + max(lease, 1) seconds, and `attempts` + 1.
  [verified]
- **SEL-311** If no `pending` item is claimable, then Selko shall reclaim a `processing` item whose
  lease has expired and which has attempts left, oldest `locked_until` first. [verified]
- **SEL-312** Selko shall never hand the same calendar work item to two concurrent claims.
  [verified]
- **SEL-313** Selko shall claim only items whose write provider has a writable integration for the
  owner and is in the claim's allowed provider list, skipping unwritable items without letting them
  block writable ones behind them. [verified]
- **SEL-314** When Selko claims an item, it shall stamp the routed provider on
  `calendar_work_items.provider`, and shall keep an already stamped provider when the item is
  reclaimed. [verified]
- **SEL-315** When the worker pool claims calendar work, Selko shall allow only the providers whose
  circuit breaker (`google_calendar` for Google, `outlook_calendar` for Outlook, from
  `BREAKER_KEYS`) is available, so an open Outlook circuit does not stop Google writes. [verified]

## Fenced transitions

- **SEL-320** If a complete, fail or defer call does not match the item's `status` `processing`,
  `locked_by` and `generation`, then Selko shall change nothing and report the call as fenced.
  [verified]
- **SEL-321** When an `upsert` item completes, Selko shall store the provider event id on
  `events.google_calendar_event_id` (keeping the existing id when none is returned), set
  `synced_at`, and mark the item `succeeded` with its lease cleared. [verified]
- **SEL-322** When a `cancel` item completes, Selko shall clear the event's
  `google_calendar_event_id` and `synced_at` and set `review_status` to `cancelled` only if it was
  `active`. [verified]
- **SEL-323** If a write fails retryably with attempts left, then Selko shall return the item to
  `pending` with `next_retry_at` = now + min(1800, max(60, 60 * 2^min(attempts - 1, 5))) seconds,
  storing `failure_code` cut to 100 characters and `failure_detail` cut to 500. [verified]
- **SEL-324** If a write fails retryably with its attempt budget spent, then Selko shall end the item
  `failed`; if it fails non-retryably, then Selko shall end it `blocked` with no `next_retry_at`.
  [verified]
- **SEL-325** If the user's `calendar_syncs` quota refuses a claimed write, then Selko shall return
  the item to `pending` with one attempt given back (never below 0), `failure_code`
  `calendar_quota` and `next_retry_at` set to the quota reset time. [verified]

## Provider writes

- **SEL-330** Selko shall write to a calendar provider only from the calendar worker, dispatched by
  the worker pool with the claimed work item's lease, never from an API request. [verified]
- **SEL-331** If a provider write fails, then Selko shall leave the `events` row and
  `calendar_sync_log` unchanged, leaving the failure to the fenced work-item transition. [verified]
- **SEL-332** When an `upsert` targets an event that already has a provider event id, Selko shall
  update that event in place, and if the provider answers 404, then Selko shall create a new event
  and log the action as `created`. [verified]
- **SEL-333** When an `upsert` targets an event with no provider event id, Selko shall first look
  for a provider event carrying the private `selko_event_id` and update it if found, creating a new
  event only when none exists. [verified]
- **SEL-334** When a `cancel` item runs, Selko shall do nothing remotely for an event with no
  provider id, delete the provider event when `delete_remote` is set, otherwise prefix its title with
  `CANCELLED: ` once, and treat a provider 404 as already done. [verified]
- **SEL-335** When a provider write succeeds, Selko shall append a `calendar_sync_log` row with the
  action and the body it wrote. [verified]
- **SEL-336** If a queued write carries `expected_provider_revision` and the live provider event's
  etag differs, then Selko shall refuse the write as diverged unless `force_overwrite` is set.
  unverified: no test exercises the revision check inside `sync_event_to_calendar` or
  `cancel_event_to_calendar`; checked only by code review.

## Providers and routing

- **SEL-340** Selko shall store Outlook calendar and event ids as `outlook:<graph id>` and Google ids
  bare. [verified]
- **SEL-341** Selko shall route a write (`selko.db.calendar_work.calendar_write_provider`) to the
  provider of the event's existing provider id when it has one, else to the provider of a non-empty
  `target_calendar_id`, else to Google if writable, else Outlook if writable, else Google.
  [verified]
- **SEL-342** When the calendar worker writes an event, Selko shall keep an event already in one
  provider's calendar in that provider even if the work item was stamped with another, and shall
  otherwise use the stamped provider or, failing that, the target calendar's provider. [verified]
- **SEL-343** Selko shall treat an Outlook integration as writable only when it is `active` and its
  scopes include one ending in `Calendars.ReadWrite` (case-insensitive), so a mail-only Outlook grant
  is never claimed and building its calendar adapter fails as `oauth_required`. [verified]
- **SEL-344** Selko shall write to the target calendar when it belongs to the routed provider and to
  that provider's `primary` calendar otherwise. [verified]
- **SEL-345** When Selko cancels an event in a calendar, it shall send the cancellation to the
  provider named by the event's stored provider id. [verified]
- **SEL-346** When Selko refreshes an Outlook token, it shall request only the scopes the stored
  grant holds, so a mail-only grant is refreshed without `Calendars.ReadWrite`. [verified]
- **SEL-347** If a Microsoft Graph `POST` fails with a server error, then Selko shall not retry it,
  since the event may already exist. [verified]

## Failure classification and recovery from OAuth errors

- **SEL-350** Selko shall classify calendar failures as `oauth_required` (missing credentials, HTTP
  401) and `oauth_scope_required` (Google insufficient-scope 403, Graph 403), both non-retryable and
  not counted toward the circuit breaker; `rate_limited` (429, Google rate-limit 403) and
  `provider_transient` (5xx), retryable and counted; and `invalid_event` (400), retryable and not
  counted. [verified]
- **SEL-351** If a calendar write fails with `oauth_required` or `oauth_scope_required`, then Selko
  shall park the item `blocked` with that failure code and record no circuit-breaker failure, and
  for any other failure shall fail the item normally and record a failure on the stamped provider's
  breaker key. [verified]
- **SEL-352** If a Google Calendar write or calendar list fails with `oauth_required` or
  `oauth_scope_required`, then Selko shall mark the user's `google_calendar` integration `expired`.
  [verified]
- **SEL-353** If an Outlook calendar operation fails with an OAuth error, then Selko shall leave the
  Outlook integration's status unchanged, because that row also carries mail. [verified]

## Explicit sync

- **SEL-360** When `POST /events/{id}/sync` is called for an event whose delivery status is
  `approved`, `syncing` or `synced`, Selko shall return the current status and queue nothing.
  [verified]
- **SEL-361** When `POST /events/{id}/sync` is called for a `sync_failed` event, Selko shall queue a
  new `upsert` generation with a fresh attempt budget and a `desired_event` built from the event's
  fields. [verified]
- **SEL-362** If `POST /events/{id}/sync` names an event in any other state, then Selko shall answer
  400, and if it names a missing event or another user's event, then Selko shall answer 404; neither
  queues anything. [verified]

## Calendar mirror, drift and late matches

- **SEL-370** Selko shall mirror every calendar of each active `google_calendar` integration and of
  each active Outlook integration with calendar scope into `calendar_entries`, never mirroring the
  `primary` alias beside its real id, and shall keep mirroring the other calendars when one fails.
  [verified]
- **SEL-371** Selko shall save each calendar's incremental sync token and use it on the next pass,
  and if the token has expired, then Selko shall take one full read over a window of 90 days back
  and 365 days ahead. [verified]
- **SEL-372** When a mirrored entry changes or is cancelled, Selko shall update its
  `calendar_entries` row in place on (integration, calendar, provider event id) and tombstone a
  cancelled entry with `deleted_at` rather than delete it. [verified]
- **SEL-373** Selko shall mark a mirrored entry `origin` `selko_created` when it carries the private
  `selko_event_id` and `external` otherwise. [verified]
- **SEL-374** Selko shall index mirrored entries into identity hints by iCalUID and join URL, and
  shall index any entry still lacking a hint on a later pass. [verified]
- **SEL-375** If a mirror write names an integration the user does not own, then Selko shall refuse
  it. [verified]
- **SEL-376** When a mirror pass brings in external, non-deleted entries, Selko shall compare each
  `pending_review` event that starts in the same minute with the entry and, on a match, set the
  event to `rejected` only if it is still `pending_review`, relabelling its email `event_matched`
  when that email produced no other event. [verified]
- **SEL-377** Selko shall judge a synced event diverged when its title, location, description
  (ignoring Selko's footer), start or end differs from the last snapshot Selko wrote, treating an
  explicit offset and its equivalent named zone as equal. [verified]
- **SEL-378** If an undo would change a synced event whose live calendar copy diverged from the
  latest `created` or `updated` snapshot, or no such snapshot exists, then Selko shall answer 409
  `CALENDAR_DIVERGED` with the differences and queue nothing, unless the undo is forced. [verified]

## Reconnect recovery

- **SEL-380** When a `google_calendar` grant, or an `outlook` grant that includes calendar scope, is
  saved, Selko shall supersede the integration's `pending`, `processing` and `waiting`
  `integration_recoveries` rows and create one `pending` row with reason `reauthorization`; a Gmail
  or mail-only Outlook grant creates none. [verified]
- **SEL-381** When a grant is saved for an existing integration, Selko shall set it `active` and
  replace its stored scopes with the new grant's. [verified]
- **SEL-382** When a recovery worker claims a recovery, Selko shall lease the oldest (by
  `requested_at`) `pending` or lease-expired `processing` row with attempts left and no future
  backoff, never a `waiting` row, and shall return expired leases to `pending` when unlocking.
  [verified]
- **SEL-383** When a recovery is requeued, Selko shall answer -1 unless the caller holds its
  unexpired lease, and otherwise return to `pending` (lease and backoff cleared, `attempts` capped at
  `max_attempts` - 1) each `failed` or `blocked` item with `oauth_required` or `oauth_scope_required`
  routed to the recovery's provider and with no newer active item, tag its event's `recovery_id`,
  and move the recovery to `waiting`. [verified]
- **SEL-384** When waiting recoveries are refreshed, Selko shall mark one whose tagged items are all
  finished `completed`, or `completed_with_errors` when any ended `failed` or `blocked`, and keep it
  `waiting` while any is `pending` or `processing`. [verified]
- **SEL-385** When `GET /integrations/recovery` is called, Selko shall return only the caller's
  newest recovery for the provider (default `google_calendar`) with the card columns, and no client
  route shall write `integration_recoveries`. [verified]

## Calendar settings and calendar list

- **SEL-390** When `PATCH /settings/calendar` is called, Selko shall merge only the sent fields into
  the caller's `user_calendar_settings` row, and if the time zone is not an IANA zone or a `custom`
  all-day window does not start before it ends, then Selko shall answer 422. [verified]
- **SEL-391** While a user has no settings row, Selko shall write events with time zone
  `America/New_York`, all-day mode `all_day` and no target calendar, and shall never read another
  user's settings. [verified]
- **SEL-392** When `GET /calendars` is called, Selko shall list the writable calendars of the
  caller's Google integration and calendar-capable Outlook integration with `provider` and
  `is_selected` (the target calendar), and if no calendar is connected, then Selko shall answer 404.
  [verified]
- **SEL-393** When a combined Google consent connects Calendar, Selko shall store the calendar's
  time zone in the user's `user_calendar_settings.timezone`. [verified]
