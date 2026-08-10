# Live UI Updates Across Web, iOS, and Android

**Status:** Implemented — web #270, iOS #271, Android #272 (private Broadcast `user:<uid>:selko-changes`, `realtime.send` triggers + `realtime.messages` policy, coordinators with 350ms debounce/inFlight+trailing/SUBSCRIBED synthetic, lifecycle catch-up), hardened by the remediation plan C6 #284 and C7 #285:

- **Auth refresh (C6):** all three clients re-authorize the realtime socket on
  token rotation (`TOKEN_REFRESHED` / `sessionStatus`), or the private channel
  went deaf ~1h after sign-in.
- **Lifecycle catch-up (C6):** web visibility/focus/online and mobile
  scene-active now call `catchUp()` (a synthetic invalidation per subscribed
  resource) — the previous calls to `start()` short-circuited when the channel
  existed, so they were no-ops. iOS and Android `start()` are now actually
  wired from the auth flow (they previously had zero callers).
- **Terminal-channel rejoin (C6):** CHANNEL_ERROR/TIMED_OUT/CLOSED (or
  subscribe errors) rejoin with capped exponential backoff; the database
  snapshot on success is the source of truth.
- **Fan-out collapse (C7):** `realtime.send` does not deduplicate like
  `pg_notify`; a transaction-local GUC guard in `broadcast_user_ui_change`
  collapses N rows to one message per (transaction, user, resource), and the
  events UPDATE trigger only fires on the user-visible columns.

## Outcome

New suggestions, status transitions, email-processing outcomes, and connection
recovery progress appear while the user is looking at Selko. A manual refresh
must not be required.

The design uses Realtime as a low-latency invalidation signal and the existing
RLS-protected Supabase queries as the source of truth. It does not merge
database row payloads directly into UI state.

## Current-state findings

- Web Review loads integrations once, then fetches pending events once.
- Web History loads once. Its only polling is a narrow 750 ms loop after the
  user explicitly requests email reprocessing.
- iOS Review and History load in `.task` and support pull-to-refresh, but do not
  observe background changes.
- Android Review and History load through ViewModels and support
  pull-to-refresh, but do not observe background changes.
- All clients already share the same Supabase session and canonical nested
  event query:
  `events(*, event_sources(*, emails(...)))`.
- Backend event creation inserts the `events` row before its `event_sources`
  rows. A raw event insert payload is therefore not a complete Review card.
- Android currently installs Supabase Auth and PostgREST, but not the Realtime
  plugin. The full Supabase Swift product already includes Realtime.
- No application tables are currently configured for Realtime changes.

## Decision: private Broadcast invalidations

Use database-triggered Supabase Broadcast on one private per-user topic:

`user:<auth.uid()>:selko-changes`

Supabase recommends Broadcast over Postgres Changes for database notifications
because it scales better and supports private-channel authorization. Selko also
needs a deliberately tiny payload: broadcasting full `integrations` or `emails`
rows could expose OAuth tokens or message content and retain that content in
Realtime storage.

Each message contains only:

```json
{
  "resource": "events",
  "operation": "UPDATE",
  "entity_id": "uuid",
  "occurred_at": "2026-07-29T00:00:00Z"
}
```

Allowed resources are `events`, `event_sources`, `emails`, and `integrations`.
The payload is an invalidation hint, never authoritative data.

Do not add page-wide interval polling. Polling creates requests while nothing
changes, delays updates by its interval, and still needs lifecycle catch-up.
Targeted bounded polling may remain temporarily for an explicit operation such
as email reprocessing until its Realtime completion path ships.

## Alternatives considered

| Option | Decision |
|---|---|
| Fixed-interval polling on every client | Reject. It spends requests while idle, has interval latency, multiplies with active screens, and still needs resume reconciliation. |
| Postgres Changes | Reject for the product path. It is simpler, but Supabase recommends Broadcast for scalable, secure database notifications; per-subscriber row authorization also scales less efficiently. |
| Private database Broadcast | Choose. It gives one small per-user invalidation channel and avoids exposing raw table rows. |
| APNs/FCM data pushes | Not the consistency mechanism. Native operating systems suspend background sockets and may delay silent push. Push can later notify a user, but foreground/resume snapshot fetches remain authoritative. |
| Redis, Kafka, or another event bus | Reject at current scale. PostgreSQL already commits the durable state, and database Broadcast can signal all clients after commit. |

Native clients provide live updates while foregrounded. They do not attempt to
keep an unrestricted WebSocket alive in the background. On resume they
resubscribe and fetch, so the first visible frame converges even when the
operating system suspended the app.

## Known consumer to migrate (hardening 7d)

`frontend/src/lib/components/ConnectionRecovery.svelte` currently polls `fetchCalendarRecovery()` every 5s via `setTimeout`. This is the only consumer not yet on Realtime invalidation. It is left as polling for now because the recovery table is service-role-only (no Realtime auth) and the catch-up UI is progress-only (no missed-event risk). Recorded here so it is not forgotten when the Broadcast auth for `integration_recoveries` is added.

## Implementation map

| Area | Primary files |
|---|---|
| Broadcast triggers and authorization | `supabase/migrations/<timestamp>_live_ui_broadcast.sql` |
| Web coordinator | `frontend/src/lib/live-updates.js`, `frontend/src/routes/app/+layout.svelte` |
| Web consumers | `frontend/src/routes/app/+page.svelte`, `frontend/src/routes/app/history/+page.svelte` |
| iOS coordinator | `ios/Selko/Core/LiveUpdates/LiveUpdateService.swift`, `ios/Selko/Core/DI/DependencyContainer.swift` |
| iOS consumers | `ios/Selko/Features/Review/ViewModels/ReviewQueueViewModel.swift`, `ios/Selko/Features/History/ViewModels/HistoryViewModel.swift` |
| Android dependency/client | `android/gradle/libs.versions.toml`, `android/app/build.gradle.kts`, `android/app/src/main/java/net/melisma/selko/data/api/SupabaseClientFactory.kt` |
| Android coordinator/consumers | `android/app/src/main/java/net/melisma/selko/data/repository/LiveUpdateRepository.kt`, Review and History ViewModels |

## Reliability model

Realtime delivery is not the durability boundary. PostgreSQL is.

Every client follows this sequence:

1. Establish the authenticated private channel.
2. Register handlers before subscribing.
3. When subscription reaches `SUBSCRIBED`, fetch a canonical snapshot.
4. Debounce incoming invalidations and refetch affected resources.
5. On socket resubscription, network recovery, app foreground, or visible-tab
   return, fetch again.
6. Remove the channel when the user signs out and suspend it while a native app
   is backgrounded.

Subscribing before the initial fetch closes the load/subscribe race: a change
during the fetch schedules a trailing refresh. Resume and resubscribe fetches
repair any missed messages without requiring message replay or a durable client
cursor.

## 1. Database migration

Add a `SECURITY DEFINER SET search_path = ''` helper:

`public.broadcast_user_ui_change(user_id, resource, operation, entity_id)`

It calls `realtime.send()` with:

- the minimal JSON payload above;
- event name `invalidate`;
- topic `user:<user_id>:selko-changes`; and
- `private = true`.

Never call `realtime.broadcast_changes()` with raw Selko rows.

Add narrow triggers:

| Table | Emit when | User resolution |
|---|---|---|
| `events` | insert/delete, or displayed fields/status/sync state change | `NEW/OLD.user_id` |
| `event_sources` | insert, `is_undone`, `change_set`, or source attribution change | join `events` by `event_id` |
| `emails` | processing status/outcome/error/timestamp change | `NEW/OLD.user_id` |
| `integrations` | status or recovery projection change | `NEW/OLD.user_id` |

An `event_sources` delete caused by an event cascade does not need its own
message; the event delete trigger invalidates the resource.

Add one `SELECT` policy on `realtime.messages`:

```sql
using (
  realtime.messages.extension = 'broadcast'
  and (select realtime.topic()) =
      'user:' || (select auth.uid())::text || ':selko-changes'
)
```

Do not grant authenticated users `INSERT` on `realtime.messages`; clients only
receive database broadcasts.

Because Broadcast uses its own `realtime.messages` publication, do not add
Selko tables to `supabase_realtime`.

## 2. Shared client contract

Each platform exposes a single authenticated `LiveUpdateCoordinator` rather
than opening a channel per screen.

The coordinator emits a small domain event:

```text
LiveInvalidation(resource, entityId?, operation)
```

Required behavior:

- exactly one channel per signed-in user/process;
- idempotent `start(userId)` and `stop()`;
- session-token refresh before private-channel join;
- connection status for diagnostics;
- 250–500 ms debounce per resource;
- one in-flight refresh per resource with one trailing refresh if another
  invalidation arrives;
- no retries in a tight loop;
- no user-facing error for a transient socket disconnect when snapshot fetching
  still works; and
- structured logs for join, drop, resubscribe, invalidation, and catch-up.

## 3. Web

Add a coordinator beside `frontend/src/lib/supabase.js`.

At the authenticated app layout:

- start it after the Supabase session resolves;
- stop it on sign-out/unmount;
- call `supabase.realtime.setAuth()` before joining the private channel;
- listen for `visibilitychange`, `focus`, and `online`;
- refresh the visible route on each transition back to active/online; and
- remove the channel explicitly during cleanup.

Review subscribes to `events`, `event_sources`, and `integrations`
invalidations. It calls the existing `loadIntegrations()` /
`fetchPendingEventsWithSources()` path; it does not append broadcast payloads.
Preserve optimistic removals by ignoring a snapshot result for event IDs still
in `processingEvents`, then apply one trailing refresh after the mutation ends.

History subscribes to `events`, `event_sources`, and `emails`. On invalidation:

- refetch the first `max(20, events.length)` activity rows so pagination does
  not collapse;
- do the same for loaded email History;
- deduplicate by ID; and
- preserve contextual errors and active local operations.

When email processing Realtime coverage is proven, replace the 750 ms
reprocessing loop with invalidation-driven state fetch plus a slow bounded
fallback deadline.

## 4. iOS

Add `LiveUpdateService` to `DependencyContainer` using the existing
`SupabaseClient`.

- Use one private channel returned by the current Supabase Swift client.
- Convert `broadcastStream(event: "invalidate")` to an `AsyncStream` of typed
  invalidations.
- `ReviewQueueViewModel` and `HistoryViewModel` consume the shared stream in
  cancellable tasks and call their existing load methods.
- Observe SwiftUI `scenePhase`. On `.active`, ensure subscription and perform a
  snapshot refresh. On background, cancel collectors and remove/suspend the
  channel.
- Retain `.refreshable` as a user-controlled recovery gesture.

Do not mutate `CalendarEvent` from the broadcast payload. The nested source
model must continue to come from `EventService`.

## 5. Android

Add the Supabase Realtime module to the version catalog and install the plugin
in `createSupabaseClient()`.

Add an application-scoped `LiveUpdateRepository` in Koin:

- one private channel per authenticated user;
- deserialize `invalidate` to a small serializable model;
- expose a shared `Flow<LiveInvalidation>`;
- subscribe while the process has a started foreground lifecycle; and
- unsubscribe on sign-out/background.

Collect in ViewModels with lifecycle-aware ownership. `ReviewQueueViewModel`
and `HistoryViewModel` debounce by resource and reuse their repository fetches.
Compose screens should use `collectAsStateWithLifecycle()` for UI state.

Retain pull-to-refresh. It is useful recovery affordance, not the normal update
mechanism.

## 6. UX behavior

- New Review cards appear without taking focus or moving the user's current
  scroll position unexpectedly.
- If the user is editing a card, show a quiet **Updated information available**
  affordance rather than overwriting fields mid-edit.
- A new sender group appends predictably; do not reorder groups already on
  screen until a deliberate refresh boundary.
- Status changes made on another client remove or move the affected card after
  the debounced snapshot.
- History prepends newly terminal actions while preserving the current loaded
  depth.
- Connection recovery progress updates in place beside that connection.
- Accessibility announcements are concise: for example,
  **1 new suggestion available**. Do not announce every database transition.

## 7. Failure handling

- Subscription timeout/error: log it, schedule SDK reconnect, and keep the UI
  usable from snapshots.
- App returns after an unknown offline duration: snapshot immediately.
- Burst of worker writes: coalesce by resource; never issue one query per row.
- Refresh fails: retain current data and show a contextual retry only on the
  affected surface.
- Sign-out/session switch: remove the old channel before starting the new
  user's topic.
- Duplicate/out-of-order broadcasts: harmless because messages only invalidate.

## 8. Verification

### Database/security

- A user can subscribe only to their exact UUID topic.
- Another user's trigger produces no received message.
- Clients cannot publish to the topic.
- Payloads contain no token, email body, attachment, extracted data, or event
  description.
- Trigger bursts commit without blocking the originating write materially.

### Web

- A database-created pending event appears without reload.
- A following `event_sources` insert refreshes the complete sender attribution.
- Burst inserts result in one debounced fetch.
- Visibility and online recovery fetch missed state.
- Optimistic approval does not flash the removed card back into the queue.
- Channels are removed on sign-out/unmount.

### iOS

- Foreground insert updates Review.
- Background changes appear on activation.
- Repeated foreground transitions do not duplicate channels or collectors.
- Editing state is not overwritten.

### Android

- Foreground insert updates Review through the shared Flow.
- STOPPED/STARTED lifecycle transitions unsubscribe/resubscribe and catch up.
- Recomposition does not create channels.
- Editing and optimistic action state remain stable.

### Cross-client

- Approving on web removes the card from active iOS and Android sessions.
- An email processed by a worker appears once with complete source attribution.
- OAuth recovery counters advance on every active client.
- Offline for several minutes, then reconnect, converges to the same canonical
  snapshot on all platforms.

Run each platform's scoped unit tests and screenshot command. Add a local
multi-session integration test for Realtime authorization and a staging smoke
test against hosted Realtime before production rollout.

## 9. Rollout and observability

1. Ship trigger/policy migration disabled behind client feature flags.
2. Enable web for internal users and observe connection count, join failures,
   invalidations per minute, coalescing ratio, refetch count, and update latency.
3. Enable iOS and Android after their lifecycle tests pass.
4. Alert on sustained channel join failure and p95 invalidation-to-refresh
   latency, not individual transient disconnects.
5. Keep manual refresh everywhere.
6. Roll back by disabling client subscriptions; database triggers can remain
   harmless or be disabled separately.

## Sources

- [Supabase: subscribing to database changes](https://supabase.com/docs/guides/realtime/subscribing-to-database-changes)
- [Supabase: Realtime authorization](https://supabase.com/docs/guides/realtime/authorization)
- [Supabase: Broadcast](https://supabase.com/docs/guides/realtime/broadcast)
- [Supabase Swift channel subscriptions](https://supabase.com/docs/reference/swift/subscribe)
- [Supabase Kotlin channel subscriptions](https://supabase.com/docs/reference/kotlin/subscribe)

## Definition of done

- Active web, iOS, and Android sessions converge without manual refresh.
- Resume/reconnect always performs a canonical catch-up fetch.
- There is one private channel per authenticated client process.
- Broadcast payloads are minimal, per-user authorized, and content-free.
- Bursts are coalesced and local optimistic/edit state is preserved.
- Page-wide polling is absent; manual refresh remains available.
