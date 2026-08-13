# Review Queue Integrity

**Status:** Partially implemented, and partly superseded. Corrected 2026-08-12
after reviewing what PRs #305–#312 actually delivered. Per increment:

| Increment | Status | Where it lives now |
|---|---|---|
| **R1** — stable animated web queue | **Partially implemented** (#305). Ordering helper, lane state and disposition wrapper are real. Eight defects, two of them high severity, and eight of the fourteen required tests are missing. | Repaired by [`stub-rollback-and-gate-repair.md`](stub-rollback-and-gate-repair.md) **G5** (defects D-R1.1 … D-R1.8). |
| **R2** — staged, fenced event resolution | **Not implemented.** #306–#308 merged three tables, six RPCs and a worker that nothing instantiates. The duplicate-event race this plan exists to fix is untouched. Objects dropped by G1. | **Superseded by** [`parallel-extraction-fenced-commit.md`](parallel-extraction-fenced-commit.md). |
| **R3** — identity-aware correlation | **Not implemented.** #309 merged two permanently empty tables. No canonicalizer, no provider parsing, no ladder. Objects dropped by G1. | **Superseded by** [`calendar-identity-and-cancellation.md`](calendar-identity-and-cancellation.md) C1–C2. |
| **R4** — automatic cancellation | **Not implemented.** #310 merged 50 lines of DDL and no behaviour, and truncated two live CHECK constraints (repaired by #312). | **Superseded by** [`calendar-identity-and-cancellation.md`](calendar-identity-and-cancellation.md) C3. |
| **R5** — reviewed data repair | **Not implemented.** #311 merged a script that opens no database connection and exits 0 from `--apply`. Deleted by G1. | **Superseded by** [`parallel-extraction-fenced-commit.md`](parallel-extraction-fenced-commit.md) P4. |

**This document remains normative for its requirements.** §1 (outcomes), §3
(decisions), §5 (web Review), §7 (identity), §8 (cancellation) and §9 (repair)
are correct and are the requirement text the successor plans build against.
**Decisions 6 and 7 in particular are upheld, not overridden** — extraction
stays parallel and every resolution write stays fenced.

What changed is only the §6 *mechanism*. Fenced per-user lanes — three tables,
six RPCs, a second queue and a second worker — are replaced by optimistic
concurrency on the read-modify-write window that actually needs it: the commit
re-checks the `(user_id, local_day)` candidate set it was computed against, and
recomputes if it changed. See `parallel-extraction-fenced-commit.md` §2.

**Scope:** Web Review stability and disposition animation, durable email-to-event
resolution, duplicate prevention, cancellation handling, and a one-time repair
of the known production rows.

**Evidence date:** 2026-08-11. Production observations in this document are
privacy-safe summaries. Do not copy names, subjects, bodies, provider IDs,
meeting links, or tokenized scheduling URLs into source control, fixtures, or
logs.

## 1. Outcome

The Review page must behave like a stable work queue:

1. The first successful snapshot establishes the visible order for the mounted
   browser session.
2. Accepting, rejecting, undoing, or receiving a Realtime invalidation does not
   reshuffle surviving cards or replace the page with a loading skeleton.
3. A disposition gives immediate, accessible visual feedback and then removes
   the card without a navigation or page reload.
4. Two emails about the same event cannot race through independent snapshots
   and create two events.
5. A cancellation never creates a new event. When it can be correlated safely,
   it automatically removes the event from Review and records an auditable
   terminal outcome.
6. Existing duplicates and known cancelled suggestions are repaired only by a
   dry-run-first, preconditioned production command. Ambiguous rows are never
   guessed.

The UI repair is frontend-only. Duplicate prevention and cancellation
correctness are backend/database work and cannot honestly be solved in the
browser.

## 2. Why the current system behaves this way

### 2.1 Review reshuffling

`frontend/src/lib/services/events.js::fetchPendingEventsWithSources()` returns
all New and Changes rows ordered by `start_datetime ASC`. The page then groups
those rows by the first occurrence of each sender.

`frontend/src/routes/app/+page.svelte::loadEvents()` currently does three things
on every load, including every Realtime invalidation:

- sets `isLoadingEvents=true`, which replaces the entire Review surface with a
  skeleton;
- rebuilds `newSenderOrder` and `changeSenderOrder` from the new server
  snapshot; and
- replaces `events` wholesale.

The optimistic action itself removes only the clicked card. The subsequent
Realtime fetch reconstructs all group positions from the remaining oldest
event for each sender, so the list appears to reshuffle. The existing test,
`keeps a sender group in place when its earliest event is rejected`, covers the
optimistic removal but not the post-mutation Realtime snapshot. It therefore
passes while the user-visible bug remains.

This also conflicts with the live-update contract approved and shipped in
#270–#272: new cards must not move the user's current content, and a new sender
group must append without reordering existing groups until a deliberate refresh
boundary.

### 2.2 Duplicate events

The production evidence contains two pairs of duplicates. Within each pair,
the two source emails were processed concurrently. Both workers:

1. extracted an event;
2. queried the same pre-insert candidate snapshot;
3. correctly received “no match” from the comparison; and
4. inserted separate rows milliseconds apart.

Later retries matched an existing row correctly, but there is no mechanism to
collapse duplicate rows already created by the original race.

The race is enabled by the current architecture:

- `backend/selko/workers/pool.py` deliberately fans LLM work out eight-wide;
- `claim_unprocessed_email()` claims the oldest ready email globally with
  `FOR UPDATE SKIP LOCKED`, without serializing event resolution per user;
- `backend/selko/workers/email_process.py` runs the synchronous extraction,
  comparison, proposal, and persistence bundle in `asyncio.to_thread()`; and
- `save_extracted_events()` performs candidate reads and separate PostgREST
  writes without a fenced commit boundary.

There is a second soft spot: `asyncio.wait_for()` can cancel the coroutine that
is awaiting `to_thread()`, but it cannot stop the underlying Python thread.
The pool currently releases or fails the email after the timeout. A retry can
therefore start while the original thread is still capable of writing.

### 2.3 Missed cancellations

The current ingestion path intentionally suppresses calendar messages:

- Gmail parsing reduces recognized iCalendar methods to
  `is_calendar_invite=true` and pre-skips the email.
- Outlook parsing reduces all Graph `eventMessage` subtypes to the same
  boolean.
- `process_email_for_events()` skips every method in `INVITE_METHODS`, including
  `CANCEL`.

That behavior came from the review-list quality work shipped through #194, which
assumed the user's calendar would be the source of truth for invite updates and
cancellations. The production examples disprove that assumption for Selko
suggestions still in Review: a pending Selko row has not been written to Google
Calendar, so calendar read-back cannot remove it.

There is also a latent state bug. `apply_pending_change()` detects a
`source_type='cancellation'`, prefixes the title, and then unconditionally
writes `status='approved'`. `calendars.cancel_calendar_event()` writes Google
Calendar inline and is not part of the single-owner calendar worker path. The
new implementation must not call it from email processing.

### 2.4 Production evidence that affects the design

- The two exact duplicate pairs share strong within-pair evidence such as the
  same call location and time.
- A privacy-safe hash comparison also found a stable scheduling-management
  link shared across the two different time slots. That is useful supporting
  evidence for a reschedule, but it may be a portal-wide link and is not safe
  as a unique key by itself.
- The known hiring-manager suggestion received a later reschedule email.
  Matching worked, but persistence failed repeatedly on a known schema trigger
  defect.
  No cancellation email is currently present in Selko's production database,
  so repair must use the user's explicit instruction rather than pretend
  ingestion saw one.
- One of the two paired interview time slots is cancelled, but the evidence
  available to this plan does not identify which one. The repair command must
  refuse to apply until the operator supplies that mapping explicitly.

## 3. Locked product and architecture decisions

1. **Session-stable order, server-canonical membership.** The server decides
   which rows belong in Review. The mounted client decides where already-seen
   rows remain within that session.
2. **Oldest-first only seeds a session.** Initial order remains
   `start_datetime ASC`. Removing the oldest card does not promote another
   sender group. Reloading or remounting is the deliberate boundary that
   reseeds chronological order.
3. **No new ordering column.** This is transient presentation state, not user
   data. Do not write ranks to Supabase, local storage, or a cookie.
4. **No page reload after a disposition.** Use the existing optimistic client
   mutation and Realtime invalidation path.
5. **No animation dependency.** Use Svelte keyed blocks, transitions, and FLIP.
6. **Parallel extraction, serialized resolution.** LLM/media extraction may
   remain concurrent. Candidate matching and event persistence use one durable
   lane per user.
7. **Every resolution write is fenced.** A worker must present the current lane
   generation to a database RPC for every event mutation. An expired or
   superseded worker may finish computation but cannot write.
8. **No long database transaction across an LLM call.** Do not hold a row lock,
   advisory lock, or pooled connection while waiting on a provider.
9. **Identity is evidence, not one universal fingerprint.** Structured
   iCalendar identity is authoritative. Thread, meeting, sender, and scheduling
   link hints have explicit strengths and must be combined; no weak hint alone
   may merge or cancel an event.
10. **Cancellation cannot create.** An unmatched cancellation is an audited
    email outcome, never a New card.
11. **Calendar writes remain worker-owned.** Email processing may queue a
    cancellation intent but must not call Google Calendar directly.
12. **No production content in tests.** Build anonymized fixtures that preserve
    the relationships, not names, URLs, or wording.

Decision 10 supersedes only the cancellation portion of #194's “Interaction with
existing events” trade-off — the assumption that Google Calendar read-back can
remove a suggestion Selko never wrote there.
REQUEST, REPLY, COUNTER, and DECLINECOUNTER remain skipped unless a later,
separately approved plan changes them.

### 3.1 Alternatives considered and rejected

| Option | Decision | Reason |
|---|---|---|
| Re-sort from the server after every action | Rejected | It is the present bug: membership stays correct but the user's spatial context is lost. |
| Persist Review ranks in the database or browser storage | Rejected | Session order is presentation state. Persistence creates cross-device conflict and stale ranks without product value. |
| Reduce the entire email worker to concurrency 1 | Rejected | Correct but serializes expensive extraction and discards measured backlog throughput. |
| Use an in-process mutex keyed by user | Rejected | It does not coordinate another API replica, a standalone worker, restart, or expired task. |
| Hold a PostgreSQL row/advisory lock across the LLM call | Rejected | It ties up a Supavisor session/transaction during unbounded external I/O and remains fragile around thread timeout. |
| Add a per-user lease without a generation fence | Rejected | An expired owner can keep running and write after a replacement claims the lane. This is especially real with `to_thread()`. |
| Add one semantic fingerprint unique index | Rejected | Permanent meeting rooms, portal links, and similar same-day interviews can collide; a false merge is worse than a visible duplicate. |
| Add a periodic duplicate cleanup sweep | Rejected | It repairs symptoms after users see them, cannot safely infer all fuzzy duplicates, and adds idle work. |
| Parallel extraction plus fenced per-user resolution | Selected | It preserves throughput, gives each user a serial event history, survives replicas/restarts, and makes stale workers harmless. |

## 4. Non-goals

- Persisting Review order between browser sessions or across devices.
- Reordering History.
- A general-purpose distributed workflow engine.
- Treating title/time similarity as a database uniqueness constraint.
- Automatically deleting a Google Calendar event directly from email code.
- Reprocessing all historical calendar invites.
- Copying production email content into an eval.
- Guessing which ambiguous production event is cancelled.
- Changing iOS or Android Review behavior in this workstream.

## 5. Workstream A — stable, animated web Review

### 5.1 State model

Extract ordering/reconciliation into
`frontend/src/lib/review-queue-order.js`. Keep DOM/focus concerns in the page.

Use one state object per lane (`pending_review` and `pending_change`):

```js
/** @typedef {{
 *   senderRank: Map<string, number>,
 *   eventRank: Map<string, number>,
 *   nextSenderRank: number,
 *   nextEventRank: number
 * }} LaneOrder */
```

Ranks increase monotonically for the mounted session. Never renumber after
removal. Retain the rank of a removed event until unmount so Undo can restore
the exact position.

Required pure helpers:

```js
createLaneOrder()
seedLaneOrder(events, senderForEvent)
reconcileLaneOrder(order, previousEvents, loadedEvents, senderForEvent)
sortLaneEvents(events, order, senderForEvent)
```

`reconcileLaneOrder` follows these rules:

1. An ID already in `eventRank` keeps its event rank.
2. A sender already in `senderRank` keeps its group rank, even if its earliest
   event disappeared.
3. A new card for an existing sender appends after that sender's known cards.
4. A previously unseen sender appends after all known sender groups.
5. A card moving between New and Changes appends in the destination lane.
6. Missing cards leave membership but remain in rank maps for Undo.
7. Ties and missing dates use server array index only during initial seeding;
   never compare `Date` values during reconciliation.

The page derives groups only after stable-rank sorting. Within each group, sort
on `eventRank`, not `start_datetime`.

### 5.2 Initial load versus background refresh

Replace `isLoadingEvents` with:

```js
let hasEventSnapshot = $state(false);
let isInitialEventsLoad = $state(false);
let isRefreshingEvents = $state(false);
let refreshError = $state('');
let refreshSequence = $state(0);
let refreshQueued = $state(false);
```

- Show the skeleton only before the first successful snapshot.
- A Realtime, focus, reconnect, post-action, or Undo refresh keeps the current
  list mounted and sets `aria-busy` on the Review container.
- A background failure keeps stale cards visible and shows a contextual,
  dismissible retry. It must not enter the full-page error branch.
- Increment `refreshSequence` before each request. Apply a response only if its
  sequence is current, preventing a slower old response replacing a newer one.
- Coalesce invalidations during actions. When the last action settles, run one
  trailing refresh.

Track optimistic removals explicitly:

```js
/** @type {Map<string, { event: any, kind: 'accept'|'reject', lane: string }>} */
let dispositions = $state(new Map());
```

A background snapshot must not reinsert a dispositioned ID while its request
is unresolved. On success, retain the tombstone until a successful snapshot
confirms absence. On failure, remove the tombstone, restore the card at its
retained rank, and display the per-card error.

### 5.3 Motion design

Create `frontend/src/lib/components/DispositionedCard.svelte`, used around both
`EventCard` and `ChangeCard`.

- **Accept:** semantic success wash, check icon and “Accepted” text, then fade
  and collapse.
- **Reject:** semantic destructive wash, X icon and “Rejected” text, a subtle
  horizontal offset, then fade and collapse.
- Start feedback immediately; run the request concurrently.
- Target 180–240 ms total. Do not block the request on animation.
- Use DaisyUI/theme semantic colors only, never raw Tailwind colors.
- With reduced motion, keep icon/text feedback but set translation, FLIP, and
  transition durations to zero.

Svelte constraints:

- sender groups and cards remain keyed;
- `animate:flip` sits on an immediate child of a keyed `{#each}`;
- use a transition for add/remove because FLIP animates only reordering;
- wrapper keys equal `event.id`, never array index; and
- do not key the whole surface, which would recreate every card.

### 5.4 Focus and announcements

Before keyboard-triggered removal, capture the next card in current global DOM
order; if none, capture the previous card. After outro:

1. focus that wrapper with `focus({preventScroll: true})` and `tabindex="-1"`;
2. otherwise focus the next section heading; or
3. if empty, focus the “All caught up” heading.

Do not move focus when Realtime merely adds or updates data.

Bulk disposition is one interaction: animate affected cards without moving
focus card-by-card, then focus the next surviving group/section or empty-state
heading and announce one aggregate result. Do not emit one live-region message
per row.

Add one visually hidden `role="status" aria-live="polite" aria-atomic="true"`
region. Announce once, for example “Interview accepted. 4 suggestions
remaining.” Do not announce animation and network completion separately. Use
`role="alert"` for action failure.

### 5.5 Frontend tests

Add pure helper tests plus component/page coverage for:

- initial server order seeding;
- reject then Realtime refetch without sender movement;
- accept then Realtime refetch without movement;
- new card for an existing sender appending within that sender;
- new sender appending even when its event is older;
- Undo restoring original rank;
- ignoring an out-of-order older fetch response;
- background refresh retaining content and avoiding skeleton;
- failure restoring card/rank with an alert;
- one trailing fetch after invalidation during mutation;
- distinct semantic accept/reject feedback;
- zero-duration reduced motion;
- next/previous/empty focus targets; and
- one concise live-region announcement.

Do not test animation with real sleeps. Inject/export duration and use fake
timers plus `outroend` or a test callback.

## 6. Workstream B — durable extraction and fenced resolution

> **SUPERSEDED — do not build this section.** The *outcome* (§1.4: two emails
> about the same event cannot create two events) still stands. The *mechanism*
> below — `email_event_resolutions`, `email_event_resolution_items`,
> `event_resolution_lanes` and their six RPCs — was built in #306–#308, wired to
> nothing, and dropped again by `stub-rollback-and-gate-repair.md` G1.
>
> Build [`parallel-extraction-fenced-commit.md`](parallel-extraction-fenced-commit.md)
> instead. **§6.1's goal is right and is kept**: extraction stays parallel and
> resolution is serialized. What §6.2–§6.4 get wrong is the granularity. The
> section serializes *the whole email* behind a per-user lane, when the only
> region that must be atomic is the read-modify-write inside
> `find_matching_event → create_event` — one `(user_id, local_day)` candidate
> band, per extracted event.
>
> Because that region contains an LLM call, it cannot be locked (§3.1 is right
> about that). It can, however, be committed *optimistically*: read and compute
> unlocked, then commit only if the candidate band is unchanged, and recompute
> if it is not. That needs no staging table, no lane, no second worker, and no
> queue — and unlike a lane it does not serialize two emails about different
> days.
>
> §6.5 (timeout and shutdown) survives intact as
> `parallel-extraction-fenced-commit.md` §2.4 and P1.

### 6.1 Why two stages

The race is not an LLM quality failure. Both comparisons were correct for the
snapshots they saw. All event decisions for one user need a serial history.

Serializing the entire current email worker per user would also serialize
expensive extraction. The code documents a real backlog difference: one-wide
processing took about 29 minutes where eight-wide took about 6. Keep extraction
parallel and serialize only candidate resolution/persistence.

### 6.2 Database objects

Create one migration with the next timestamp at implementation time. These
shapes are contracts; add comments, indexes, RLS, and explicit grants.

#### `email_event_resolutions`

```sql
CREATE TABLE public.email_event_resolutions (
    email_id uuid PRIMARY KEY REFERENCES public.emails(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    extraction jsonb NOT NULL,
    extraction_hash text NOT NULL,
    extraction_origin text NOT NULL
        CHECK (extraction_origin IN ('llm', 'ics')),
    initial_event_status text NOT NULL
        CHECK (initial_event_status IN ('pending_review', 'approved')),
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    attempts integer NOT NULL DEFAULT 0,
    max_attempts integer NOT NULL DEFAULT 3,
    next_retry_at timestamptz,
    last_error_code text,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
```

`extraction` stores validated source-normalized events, not raw email body,
model chain-of-thought, or full provider responses. Keep source quotes only to
the extent already required by `event_sources.extracted_data`.

This is service worker state. Enable RLS in the same migration, revoke
authenticated mutation, grant service-role access, and index ready work by age
and `(user_id,status)`.

#### `email_event_resolution_items`

```sql
CREATE TABLE public.email_event_resolution_items (
    resolution_email_id uuid NOT NULL
        REFERENCES public.email_event_resolutions(email_id) ON DELETE CASCADE,
    item_index integer NOT NULL CHECK (item_index >= 0),
    status text NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'completed')),
    resolved_event_id uuid REFERENCES public.events(id) ON DELETE SET NULL,
    resolution_action text CHECK (resolution_action IN (
        'created', 'matched', 'updated', 'skipped'
    )),
    completed_at timestamptz,
    PRIMARY KEY (resolution_email_id, item_index)
);
```

This makes multi-event email recovery item-idempotent. Enable RLS in the same
migration and keep it service-only.

#### `event_resolution_lanes`

```sql
CREATE TABLE public.event_resolution_lanes (
    user_id uuid PRIMARY KEY REFERENCES public.users(id) ON DELETE CASCADE,
    active_email_id uuid REFERENCES public.email_event_resolutions(email_id)
        ON DELETE RESTRICT,
    lease_owner text,
    lease_generation bigint NOT NULL DEFAULT 0,
    lease_expires_at timestamptz,
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        (active_email_id IS NULL AND lease_owner IS NULL AND lease_expires_at IS NULL)
        OR
        (active_email_id IS NOT NULL AND lease_owner IS NOT NULL AND lease_expires_at IS NOT NULL)
    )
);
```

Enable RLS and keep it service-only. Provision existing users in migration and
future users in the same creation path/trigger as other durable worker state.

Extend `emails.processing_status` with `resolving`. An email remains in
progress until serialized resolution completes; extraction alone is not
`processed`.

### 6.3 Required RPCs

Every function uses `SECURITY DEFINER SET search_path=public`, revokes `PUBLIC`,
grants only `service_role`, and is added to
`backend/tests/integration/test_schema_contract.py`.

#### `enqueue_email_event_resolution(...)`

In one transaction:

1. verify the email remains owned by the extraction worker;
2. validate a bounded event array;
3. insert/upsert resolution and one item per event;
4. set the email to `resolving`; and
5. clear its extraction lock.

Same email plus same extraction hash is idempotent. A different extraction for
existing non-failed work raises a typed conflict.

Do not enqueue an empty resolution. Sender-ignore, still-suppressed invite
methods, and “no event found” finish the email through one terminal worker RPC
with their existing safe outcomes. A structured cancellation is non-empty even
when it has no dates because its resolution item carries cancellation identity.

#### `claim_email_event_resolution(worker, lease_seconds)`

Claim lane rows, not only job rows:

1. identify lanes with ready pending resolution;
2. exclude nonexpired active lanes;
3. `FOR UPDATE OF lane SKIP LOCKED` one lane;
4. recheck readiness after locking;
5. choose oldest `email.date_sent`, then resolution `created_at`;
6. increment generation;
7. set active email, owner, and expiry;
8. mark resolution processing/increment attempts; and
9. return resolution/items/owner/generation/expiry.

Do not use `NOT EXISTS(processing)` without locking the user lane. Two
transactions can both observe no active row and claim different emails.

#### `heartbeat_email_event_resolution(...)`

Extend only where user, active email, owner, generation, and nonexpired lease
all match. Return true for one updated row. False means ownership is lost; the
worker may finish computation but cannot persist.

#### `commit_email_event_resolution_item(...)`

Arguments include user/email/item, owner/generation, decision JSON, and matched
event expected `updated_at` (or a dedicated version).

In one transaction:

1. lock/validate lane including `lease_expires_at > now()`;
2. lock the item;
3. return prior result when already completed;
4. lock/version-check a matched event;
5. apply one validated create/noop/update decision;
6. mutate event and sources atomically;
7. store item result; and
8. when all items finish, mark resolution/email terminal, release lane, and
   return safe counts/outcome.

The RPC generates new event IDs and returns them. A retry never invents another
ID. An event version conflict returns typed `resolution_conflict` without a
mutation; reload and recompute while holding the lane, with a bounded retry cap.

#### `fail_email_event_resolution(...)`

Validate the same fence. Release and retry with backoff or terminally fail by
attempt count. Update the email outcome consistently. A stale worker cannot
fail or release a newer owner's job.

### 6.4 Python split and wiring

Refactor `backend/selko/services/events.py` into:

```python
extract_email_events(...) -> EmailEventExtractionEnvelope
resolve_extracted_event(...) -> EventResolutionDecision
```

- Extraction handles sender rules, invite routing, ICS/LLM extraction, and
  normalization independent of current candidates.
- Resolution loads current local/Google candidates, applies identity rules,
  invokes compare/propose as needed, and returns a decision without mutation.
- The worker commits through the fenced RPC.
- Delete direct mutation branches from `save_extracted_events()` after all
  call sites use the staged path. Do not keep a fallback.

Add `backend/selko/workers/event_resolution.py` and wire it into the existing
single scheduler with its own semaphore and work notification. Do not add an
independent polling loop. Extraction completion nudges the scheduler.

### 6.5 Timeout and shutdown

- Set provider/network timeouts inside synchronous operations.
- Never let `wait_for()` release semaphore/lease while `to_thread()` continues.
- Heartbeat no more often than one third of lease duration.
- If heartbeat ownership is lost, do not call commit.
- The commit fence makes a delayed old thread harmless.
- On shutdown, stop claiming, await bounded in-flight work, and let unfinished
  leases expire. Never reset another owner.

### 6.6 Resolution integration tests

Use real local Postgres and mocked LLMs:

- concurrent same-user claims yield one resolution;
- different users resolve concurrently;
- next same-user email is oldest-first after completion;
- expired lane reclaims with larger generation;
- old generation cannot commit/fail/heartbeat/release;
- delayed old thread cannot create after new owner commits;
- simultaneous same-event emails produce one event and two sources;
- crash after item 0 of two resumes item 1 without duplicate;
- event version conflict recomputes rather than overwrites;
- extraction remains eight-wide while resolution is one-wide per user;
- attachment readiness still blocks extraction;
- email becomes processed only after all items terminate; and
- notification wakes scheduler without adding idle polling.

Mocks may verify payload construction; concurrency guarantees require real DB.

## 7. Workstream C — identity-aware matching

### 7.1 Provider-neutral calendar components

Create `email_calendar_components`:

```sql
CREATE TABLE public.email_calendar_components (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email_id uuid NOT NULL REFERENCES public.emails(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    component_index integer NOT NULL CHECK (component_index >= 0),
    method text NOT NULL,
    uid_hash text,
    recurrence_id text,
    recurrence_range text,
    sequence integer,
    dtstamp timestamptz,
    component_status text,
    start_datetime timestamptz,
    end_datetime timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (email_id, component_index)
);
```

Store lowercase hex SHA-256 of trimmed UID, not raw UID. Normalize
`recurrence_id` to UTC or canonical DATE without losing value type. Treat a
missing SEQUENCE as zero and validate range as null or `THISANDFUTURE`. Enable
RLS in the same migration and keep the table service-only; no current UI needs
these opaque correlation records.

Extend `save_email_with_attachment_descriptors(...)` with
`p_calendar_components jsonb` and write email, descriptors, and components
atomically. Replace the old signature; do not leave two callable variants.

Gmail:

- parse every `text/calendar`, including inline;
- preserve each VEVENT METHOD, UID, RECURRENCE-ID/RANGE, SEQUENCE, DTSTAMP,
  STATUS, DTSTART, and DTEND; and
- malformed components log safe telemetry and fall back to invite
  classification without failing acquisition.

Outlook:

- preserve `meetingMessageType`, especially `meetingCancelled`;
- expand/fetch the associated event and map `iCalUId` and dates;
- when list/delta lacks navigation data, issue the documented bounded GET,
  meter its egress, and obey Graph retries; and
- missing associated event becomes structured cancellation without UID and
  uses conservative fallback matching, never creation.

### 7.2 Event identity hints

Create `event_identity_hints`:

```sql
CREATE TABLE public.event_identity_hints (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
    event_id uuid NOT NULL REFERENCES public.events(id) ON DELETE CASCADE,
    source_email_id uuid REFERENCES public.emails(id) ON DELETE SET NULL,
    kind text NOT NULL CHECK (kind IN (
        'ical_uid', 'provider_thread', 'join_url', 'management_url'
    )),
    value_hash text NOT NULL,
    recurrence_id text NOT NULL DEFAULT '',
    strength text NOT NULL CHECK (strength IN ('authoritative', 'supporting')),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (event_id, kind, value_hash, recurrence_id)
);
```

Enable RLS and keep the table service-only. Index lookup by
`(user_id,kind,value_hash,recurrence_id)`.

Canonicalization belongs in `backend/selko/services/event_identity.py`:

- `ical_uid`: normalized UID hash; authoritative with recurrence identity;
- `provider_thread`: hash provider + thread ID; supporting only;
- `join_url`: lowercase host, remove fragment/tracking parameters, preserve
  meeting identity fields, then hash; supporting because rooms can recur; and
- `management_url`: normalize/hash the full opaque identity-bearing URL, never
  log/store raw tokenized URL; supporting because portals may be reused.

Log only kind and match presence, never raw values or hashes.

### 7.3 Matching ladder

1. **Authoritative:** exact user + UID + recurrence. Larger SEQUENCE wins;
   equal sequence uses later DTSTAMP; stale input is audited no-op.
2. **Deterministic exact duplicate:** one candidate has same normalized join
   URL plus materially equal start/end, or another approved two-signal rule.
3. **Strong correlated set:** at least two independent supporting signals,
   e.g. management URL + organizer/domain or thread + join URL. Pass only this
   bounded set and boolean hint labels to the LLM.
4. **Local-day fallback:** retain current local-day LLM comparison for ordinary
   emails.
5. **No match:** create only when input is not cancellation.

Never merge/cancel from title similarity, one management URL, one thread, or
one join URL. Never expose opaque hashes to the model. On commit, attach all
validated new hints to the survivor in the fenced transaction.

### 7.4 Evals and tests

Add anonymized coverage for:

- two independently worded confirmations for one slot;
- original slot, reschedule sharing safe supporting identity, cancellation;
- two distinct meetings sharing a permanent room/portal (must not merge); and
- stale SEQUENCE/equal-SEQUENCE-later-DTSTAMP deterministic tests.

Hand-write expected output. Run individual fixtures first. If compare/proposal
prompts change, run the full default-model all-operation suite before and after
and save reports per `docs/evals-process.md`.

## 8. Workstream D — cancellation state machine

### 8.1 Classification

1. **Structured authoritative:** METHOD:CANCEL or Graph
   `meetingMessageType=meetingCancelled`, with usable identity.
2. **Unstructured strong:** model extracts cancellation and multi-signal matcher
   correlates exactly one event.
3. **Ambiguous/unmatched:** no unique safe target.

The first two auto-apply. Ambiguous/unmatched never create or mutate an event;
mark email processed with `cancellation_ambiguous` or
`cancellation_unmatched`, with a safe History reason.

In the R4 migration, extend `email_event_resolutions.extraction_origin` with
`structured_cancellation` and extend the resolution-item action constraint with
`cancelled`, `cancellation_unmatched`, and `cancellation_ambiguous`. Update the
existing fenced commit RPC in place so event, source, and R3 identity-hint
mutations remain one transaction. Do not add a cancellation-specific unfenced
write path.

### 8.2 Local Review behavior

| Existing event | Result |
|---|---|
| `pending_review`, never synced | Attach cancellation source, set `cancelled`, remove from Review. |
| `pending_change`, never synced | Undo active proposal, attach cancellation, set `cancelled`. |
| Already `cancelled` | Idempotent match; attach new source, remain cancelled. |
| `rejected` | Record matched source/outcome, remain rejected. |
| Calendar write may exist | Queue worker-owned cancellation below and remove from Review immediately. |

Do not prefix the title when terminal status and History already communicate
cancellation. Preserve the original title.

### 8.3 Worker-owned calendar cancellation

Extend events:

```sql
calendar_sync_action text NOT NULL DEFAULT 'upsert'
    CHECK (calendar_sync_action IN ('upsert', 'cancel')),
calendar_work_generation bigint NOT NULL DEFAULT 0
```

Extend status with `cancel_queued`.

- A possible Google event becomes `cancel_queued/cancel`, increments generation,
  clears retry/dead-letter fields, and leaves Review immediately.
- Replace `claim_approved_event` with `claim_calendar_work` for
  `approved/upsert` and `cancel_queued/cancel`.
- Worker branches on action. Keep the current cancellation representation
  unless product separately chooses provider deletion; this plan introduces no
  destructive hard delete.
- Complete/fail/defer/park updates include ID, owner, and generation. Zero rows
  means stale ownership and cannot overwrite newer cancellation.
- Cancellation during upsert invalidates its generation. If external upsert
  finishes, cancel follows. When local Google ID is absent, locate by Selko's
  private extended property before treating it absent.
- Success sets `cancelled`; retries/failures preserve action so recovery never
  turns cancellation into upsert.

Update OAuth recovery sets, History, API schemas, and tests for
`cancel_queued`. Review still queries only pending review/change.

### 8.4 Cancellation tests

- Gmail inline/attachment CANCEL persists components atomically.
- CANCEL + UID cancels pending event without LLM.
- whole-series and occurrence behavior follows RFC.
- lower SEQUENCE and older equal-sequence DTSTAMP are ignored.
- Outlook cancellation retains subtype and iCal identity.
- structured cancellation without match creates nothing and records unmatched.
- one weak hint cannot cancel; a unique strong combination can.
- pending cancellation becomes terminal transactionally and leaves snapshot.
- synced cancellation queues worker work; email code calls no provider.
- cancellation racing upsert wins; stale completion cannot reset it.
- retry/OAuth recovery preserve cancel action.
- History labels cancelled/unmatched/ambiguous/queued/failed accurately.

## 9. Workstream E — one-time production repair

Add `scripts/repair_review_queue_integrity.py`. Dry-run is default. Mutation
requires:

```text
--environment production
--manifest /absolute/path/to/untracked-manifest.json
--apply
--confirm-user <user-uuid>
```

The runtime manifest is never committed and contains event UUIDs/actions only.
No subjects, bodies, names, or URLs.

Actions:

- `merge_duplicate_group`: survivor plus duplicate IDs;
- `cancel_event`: exact ID and reason (`authoritative_user_report` here); and
- `mark_source_resolved`: optional cleanup after failed historical proposal.

Dry-run prints safe IDs/statuses/counts and every failed precondition. Apply is
one transaction, locking targets in deterministic UUID order.

Preconditions:

- targets belong to confirmed user;
- duplicates remain in allowed statuses;
- field hashes match manifest expectations;
- no target is actively worker-locked;
- sources can move without silently violating `UNIQUE(event_id,email_id)`;
- cancellation target is exact; and
- schema includes this spec's migrations.

Duplicate merge:

1. move non-conflicting sources and hints to survivor;
2. for same-email conflict, retain richer non-undone source and audit snapshot;
3. regenerate attribution;
4. write content-free audit with UUIDs/action/time/reason; and
5. delete duplicate only after dependents are accounted for.

Cancellation calls the same DB transition as resolution with repair authority;
do not reproduce state logic in script.

Incident safeguards:

- The hiring-manager suggestion may be cancelled from the user's authoritative
  report despite no cancellation email in production.
- The ambiguous interview cancellation remains unapplied until an exact time
  and event ID are supplied. “One of these” exits nonzero.
- Do not replay the stale failed reschedule before choosing canonical/cancelled
  rows.

Verify after apply:

- expected Review count removed;
- one survivor per duplicate group;
- source counts preserved;
- cancellations terminal or queued appropriately;
- no global processing reset; and
- fresh public Review query omits removed IDs.

Write redacted JSON to caller path, including reverse operations and pre-change
mapping. Never print credentials or email content.

## 10. Implementation increments

Every source increment performs the late-review audit required by `CLAUDE.md`,
uses its own worktree/branch/PR, includes regression tests, and merges with
`scripts/merge-and-cleanup.sh`. Do not inspect/claim old review comments during
this documentation increment.

### R1 — stable animated web queue

Branch: `fix/review-session-order`

- add ordering helper/tests;
- add `DispositionedCard.svelte`/tests;
- change Review page/page tests; and
- add strings in all locales.

Acceptance: Workstream A complete including post-Realtime regression, focus,
reduced motion, and screenshots. No backend/schema change.

### R2 — staged, fenced event resolution

Branch: `fix/fenced-event-resolution`

- resolution/lane migration and RPCs;
- events service phase split;
- resolution worker and pool/work-notification wiring;
- asyncpg ports/config;
- unit, real-DB concurrency, schema-contract, wiring tests; and
- shipped database/job/reference documentation updates.

Acceptance: Workstream B complete. One resolution implementation, all call
sites enqueue it, and no dormant table/fallback/unfenced write remains.

### R3 — identity-aware correlation

Branch: `feat/event-identity-hints`

- components/hints/acquisition migration;
- identity canonicalizer;
- Gmail/Outlook/acquisition/repository/resolution/commit changes;
- schema/egress contracts;
- deterministic tests and anonymized evals; and
- provider/database docs.

Acceptance: duplicate/reschedule fixtures pass and permanent-room negative
case remains separate.

### R4 — automatic cancellation

Branch: `feat/automatic-event-cancellation`

- cancellation status/action/generation migration;
- invite routing/resolution decisions;
- fenced calendar claim/complete/fail ports;
- calendar worker, OAuth recovery, schemas, History;
- remove/deprecate inline cancellation when unused;
- backend/integration/eval/frontend History tests; and
- state/calendar docs.

Acceptance: pending cancellation is automatic and provider writes remain
worker-owned.

### R5 — reviewed data repair

Branch: `fix/review-queue-production-repair`

- repair script/tests;
- content-free repair audit if no suitable table exists; and
- runbook with redacted manifest.

Acceptance: dry-run reviewed, ambiguous cancellation explicitly resolved,
staging rehearsed, and production apply separately approved. Implementing R5
does not authorize production mutation.

## 11. Verification and rollout

### R1 local gate

From `frontend/`:

```bash
npm run test:unit -- --reporter=json --outputFile=test-results.json
npm run check
```

From repository root:

```bash
./scripts/capture-all-screenshots.sh web
```

Review desktop/mobile, light/dark, populated, feedback, and empty state. Use
in-app browser only for focused animation/focus debugging.

### R2–R4 gates

Before each merge, repository root:

```bash
./scripts/verify.sh backend
```

After each merge:

```bash
./scripts/verify.sh staging
```

Local integration must call every new RPC/trigger against real Postgres.
Applying a migration without executing its SQL is not proof.

For prompt changes, before and after:

```bash
uv run python -m backend.tests.eval.run_eval --all --all-operations --plan
uv run python -m backend.tests.eval.run_eval --all --all-operations
uv run python -m backend.tests.eval.run_eval --report-md backend/tests/eval/reports/YYYY-MM-DD-review-queue-integrity.md
```

Run individual fixtures first per `backend/tests/eval/README.md`. If R4 changes
History UI, also run frontend unit/check and web screenshots.

### Staging fault drills

1. Pause after candidate load, reclaim lane, prove old generation cannot commit.
2. Kill after first item of two-event email and prove resume.
3. Process same-user duplicates concurrently: one event/two sources.
4. Process different users concurrently and confirm throughput.
5. Invalidate Realtime during web disposition: no reshuffle/skeleton.
6. Inject heartbeat failure: no unfenced persistence.
7. Race calendar upsert/cancellation: cancellation wins.
8. Fail OAuth on queued cancel: reconnect resumes cancel.

### Dependency and cutover order

- R1 is independent and may land first.
- R2 must land before R3; R3 must land before R4. Do not combine their staging
  fault drills into one late test pass.
- For each backend increment, apply the compatible migration before starting
  code that calls the new RPC. The additive R2/R3 schema is inert to old code;
  R4's new status is likewise not produced until new code runs.
- A red staging verification is the next increment and blocks later merges.
- R5 dry-run may be developed earlier, but production apply waits until R2–R4
  are deployed and verified in production, and still requires a separate
  explicit production-data approval.
- Nothing in this plan or its merge authorizes the production deployment or
  repair apply.

### Observability and acceptance

Add content-free metrics/log fields for extraction/resolution depth and oldest
age, active/reclaimed lanes, fence rejections, resolution conflicts, decisions
by action, cancellation outcomes, repair count, p50/p95 latency, and calendar
work by upsert/cancel.

First seven production days must show:

- zero concurrency duplicates in this regression class;
- zero successful stale-generation writes;
- no overlapping same-user lanes;
- no cancellation creates New;
- no known matched pending cancellation remains in Review;
- extraction throughput stays in current eight-wide order of magnitude; and
- no idle polling/egress regression.

## 12. Rollback

### R1

Revert frontend PR. Server state is unchanged; reload returns to chronological
grouping.

### R2

Do not drop rows while emails are `resolving`. Stop claims, drain/return leases,
and forward-migrate unresolved emails to pending only when no completed item
exists. Do not roll back to unfenced direct writes while concurrent ingestion
runs; disable background processing during coordinated code/schema rollback.

### R3

Hints are additive and may be ignored by rolled-back code, but retain tables
until verified. Restore acquisition RPC signature only with coordinated code;
never leave deployed callers with a missing signature.

### R4

Stop new classification but retain queued cancellations. Drain or park them
before rollback. Never coerce `cancel_queued` to `approved/upsert`, which could
recreate a cancelled event.

### R5

Use repair artifact pre-change mapping. Restore duplicates/sources in one
transaction only if no later user/worker changes touched survivor. Prefer
forward correction when later activity exists.

## 13. Definition of done

- [ ] R1–R5 implemented, merged, locally verified, and staging-verified by scope.
- [ ] Review order survives accept/reject/Undo/Realtime/focus refresh.
- [ ] Background refresh never replaces populated queue with skeleton.
- [ ] Motion, reduced motion, focus, and announcements pass checks.
- [ ] Extraction parallel; resolution single-lane per user.
- [ ] Every resolution mutation validates live generation transactionally.
- [ ] Timed-out/reclaimed worker cannot write/release newer work.
- [ ] Multi-event retries item-idempotent.
- [ ] Structured identity, weak combinations, negative collisions tested.
- [ ] Cancellation never creates and safe matches auto-disposition Review.
- [ ] Calendar cancel stays worker-owned through retry/OAuth recovery.
- [ ] New tables have same-migration RLS, grants, schema contracts.
- [ ] New SQL executed by real-DB integration tests.
- [ ] Anonymized evals and before/after reports exist for prompt changes.
- [ ] Repair dry-run reviewed, ambiguity resolved, apply separately approved.
- [ ] Durable docs and `CLAUDE.md` updated after implementation.

## 14. Research sources

- Svelte: FLIP only reorders existing keyed children; transitions handle
  insertion/removal: [animate](https://svelte.dev/docs/svelte/animate),
  [transitions](https://svelte.dev/docs/svelte/transition), and
  [keyed each](https://svelte.dev/docs/svelte/each).
- PostgreSQL: `SKIP LOCKED` suits queue consumers but is intentionally an
  inconsistent view, so ownership needs an explicit lane/recheck:
  [SELECT](https://www.postgresql.org/docs/current/sql-select.html),
  [explicit locking](https://www.postgresql.org/docs/current/explicit-locking.html),
  and [Read Committed](https://www.postgresql.org/docs/current/transaction-iso.html).
- Calendar identity/revision/cancellation semantics:
  [RFC 5546](https://www.rfc-editor.org/rfc/rfc5546.html) and
  [RFC 5545](https://www.rfc-editor.org/rfc/rfc5545.html).
- Graph cancellation subtype and associated-event expansion:
  [eventMessage](https://learn.microsoft.com/en-us/graph/api/resources/eventmessage?view=graph-rest-1.0) and
  [Get eventMessage](https://learn.microsoft.com/en-us/graph/api/eventmessage-get?view=graph-rest-1.0).
- Reduced motion, focus order, and programmatic status messages:
  [Media Queries Level 5](https://www.w3.org/TR/mediaqueries-5/#prefers-reduced-motion),
  [WCAG C39](https://www.w3.org/WAI/WCAG21/Techniques/css/C39.html),
  [WCAG focus order](https://www.w3.org/WAI/WCAG22/Understanding/focus-order.html),
  and [WCAG F103](https://www.w3.org/WAI/WCAG21/Techniques/failures/F103).
