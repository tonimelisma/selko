# State Ownership and Deterministic Recovery

**Status:** Planned.

**Written:** 2026-08-13, after repairing a production Changes card whose
`events.status = 'pending_change'` row had no active proposal, then auditing
email discovery, email processing, calendar delivery, leases, and health.

**Audience:** A developer new to this codebase. Every increment below names
the files to change, the database contract, the test to write first, the
deployment order, and the evidence required to call the increment complete.
If implementation reveals an undecided transition, stop and amend this plan;
do not invent a new state or compatibility path in code.

**Depends on:**

- [`parallel-extraction-fenced-commit.md`](parallel-extraction-fenced-commit.md)
  P1–P3. `commit_email_extraction` remains the only extraction commit.
- [`calendar-identity-and-cancellation.md`](calendar-identity-and-cancellation.md)
  C1–C3. Identity matching and worker-owned cancellation remain authoritative.
- `20260822000001_pending_change_invariant.sql`. Its deferred constraint and
  atomic apply/reject RPCs are the safety floor, not the final model.

**Does not authorize:** a production deploy, a broad replay of historical
failed emails, or a semantic production-data repair. Each production deploy
still needs the explicit approval required by `CLAUDE.md`.

---

## 1. Outcome

After this plan:

1. Each concern has one owner and one state machine:
   - `emails` owns LLM-processing work;
   - `email_sync_state` plus `email_sync_runs` owns provider discovery;
   - `event_change_proposals` owns proposed update/cancellation review;
   - `calendar_work_items` owns every Google Calendar write;
   - `events.review_status` owns the user's event decision only;
   - `event_sources` owns provenance, never proposal lifecycle; only the
     fenced extraction commit may insert or idempotently refresh it.
2. A row described as pending is claimable. Exhausted work is terminal. An
   expired lease is reclaimable without restarting the process.
3. A process crash closes the abandoned run when the next generation is
   claimed. There is at most one `running` sync run per integration.
4. A Changes card exists if and only if it has exactly one pending proposal
   with a change set and before-snapshot. The UI never reconstructs proposal
   state from `event_sources.is_undone`.
5. API requests never write to Google Calendar. They enqueue fenced calendar
   work; the calendar worker is the only provider writer, including History
   undo/redo compensation.
6. Health reports the same claimability predicates the workers use. It cannot
   return `ok` while work is old, exhausted-but-pending, stale-processing, or
   missing its proposal.
7. Retired mutators and test-only production helpers are deleted. AST guards
   prevent direct event, proposal, calendar-work, and email-state writes from
   returning.

This is not a periodic repair sweeper. Invalid new states are rejected at the
write boundary; deterministic crash states are reclaimed during the next
claim; ambiguous historical states are recorded for operator review.

---

## 2. Evidence and root causes

The production audit was content-free: identifiers, status, timestamps,
counts, safe error codes, and structural booleans only. It did not print email
bodies, subjects, addresses, OAuth tokens, or provider payloads.

| Finding | Production evidence | Root cause |
|---|---|---|
| Broken Changes card | `pending_change`, one complete update source, but that source had `is_undone=true` | Proposal lifecycle is inferred from a provenance boolean plus a second mutable event status. The later deferred constraint prevented new writes but did not backfill historical rows. |
| Four unclaimable emails | `processing_status='pending'` and `attempts=max_attempts`, no lease | The claim predicate requires `attempts < max_attempts`, while the replay RPC refuses all `pending` rows. Both states are locally valid but mutually dead. |
| Six recent Outlook failures | `Object of type UUID is not JSON serializable`, no event source written | A typed asyncpg UUID crossed a JSON boundary. The boundary fix had shipped, but terminal rows were never replayed automatically. |
| One stale sync run | `email_sync_runs.status='running'` for two days while hundreds of later runs completed | Lease recovery lives on `email_sync_state`; the append-only run row has no generation link and is not closed by the next claim. |
| False-green health | `/health` returned `ok` with four month-old pending emails | `/health` counts status labels, does not evaluate claimability, and hard-codes `status='ok'`. `/health/ingestion` does not count the LLM email queue. |
| Historical calendar failures | Three `sync_failed` events, all in the past; one had `end < start` | Review state and calendar delivery state share `events.status`; terminal historical delivery failures remain mixed into the event lifecycle. |

The ten safe email replays all completed after the production repair: three
created events, one matched an event, one updated an event, and five produced
`no_event`. That proves the rows were recoverable; it does not prove the
current state model will recover the next crash.

### 2.1 Confirmed dead and accidental paths

`backend/selko/services/events.py` currently contains:

- `create_event`, `create_event_from_gcal_match`,
  `create_pending_change_from_gcal`, and `update_event`: each raises
  `EventsError("... was removed; use commit_email_extraction")`, followed by
  unreachable former implementations.
- `propose_local_change`: a complete non-atomic mutator with no runtime caller.
- `undo_email_contribution` and `redo_email_contribution`: test-only
  multi-write mutators with no API caller.
- `undo_history_event`: performs Google Calendar reads and writes inline even
  though the worker is the declared sole provider writer.

`frontend/src/lib/services/event-sources.js` exports direct `is_undone`
mutators and an active-source counter used only by tests and the barrel export.

The module reachability test catches an unreachable module, not an unreachable
function inside a reachable module. That is why these paths pass the gate.

---

## 3. State ownership

### 3.1 The target model

| Concern | Authoritative storage | Valid states | Transition owner |
|---|---|---|---|
| Email LLM work | `emails.processing_status` | `pending`, `processing`, `processed`, `failed`, `skipped` | fenced email claim/complete/fail/reprocess RPCs |
| Provider discovery | `email_sync_state` + `email_sync_runs` | state lease plus `running`, `completed`, `failed`, `abandoned` run | sync claim/complete/fail RPCs |
| Event decision | `events.review_status` | `pending_review`, `active`, `rejected`, `cancelled` | event decision RPCs |
| Change review | `event_change_proposals.status` | `pending`, `applied`, `rejected`, `superseded`, `closed_legacy` | extraction commit plus proposal apply/reject/reopen RPCs |
| Calendar delivery | `calendar_work_items.status` | `pending`, `processing`, `succeeded`, `failed`, `blocked`, `superseded` | calendar enqueue/claim/complete/fail RPCs |
| Provenance | `event_sources` | source facts, no lifecycle state | extraction commit only |

`events.review_status` answers only: “What has the user decided about this
event?” It never means “the calendar worker is running.” A pending proposal
answers only: “Does this event belong in the Changes lane?” A calendar work row
answers only: “What provider write is outstanding?”

### 3.2 Required event transitions

| Action | Event review state | Proposal state | Calendar work |
|---|---|---|---|
| Extract new event | `pending_review` | none | none |
| Approve new event | `active` | none | enqueue `upsert` |
| Reject new event | `rejected` | none | none |
| Restore rejected event | `pending_review` | none | none |
| Extract material update | unchanged (`active`) | create `pending` | none |
| Apply update proposal | `active` | `applied` | enqueue `upsert` |
| Reject update proposal | unchanged | `rejected` | none |
| Extract cancellation | unchanged (`active`) | create `pending` | none |
| Apply cancellation | `cancelled` | `applied` | enqueue `cancel` if a provider event exists |
| Reject cancellation | unchanged | `rejected` | none |
| Undo applied update | `active` with pre-change fields restored | reopen proposal as `pending` | enqueue compensating `upsert` |
| Undo new-event approval | `pending_review` | none | enqueue `cancel` if a provider event exists |
| Redo a reopened proposal | same transition as apply | `applied` | enqueue `upsert` or `cancel` |

The API may read Google Calendar to perform the existing divergence check, but
it may not mutate Google Calendar. It passes the observed provider revision or
content hash into the enqueue RPC. The worker revalidates that fence immediately
before writing. A mismatch sets calendar work to `blocked` with safe failure
code `provider_diverged`; it never overwrites silently. `force=true` is an
explicit user action recorded on the work row.

### 3.3 Invariants

Implement these in PostgreSQL and execute them in integration tests:

1. `emails.processing_status='pending'` implies
   `attempts < max_attempts`, no owner, and no unexpired lock.
2. `emails.processing_status='processing'` implies an owner, an unexpired lock
   at claim time, and a positive `lock_generation`.
3. Only the current `(locked_by, lock_generation)` may complete or fail email
   work.
4. At most one `email_sync_runs.status='running'` row exists per integration.
5. A running sync row has the same lease generation as `email_sync_state`.
6. At most one pending proposal exists per event.
7. A pending proposal has `change_set`, `event_snapshot_before`, an update or
   cancellation source, and matching event/user ownership.
8. `event_sources` rows cannot be updated or deleted by `authenticated` users;
   only the fenced extraction commit may idempotently refresh source facts.
9. At most one active (`pending` or `processing`) calendar work item exists per
   event; succeeded/failed/blocked/superseded rows remain history.
10. Only the current calendar work generation may complete/fail a provider
    write.
11. No service or API route writes event/proposal/calendar/email lifecycle
    columns directly; only the named RPCs do.

### 3.4 Deterministic recovery versus semantic repair

Automatic recovery is allowed when the intended next state is mechanically
provable:

- expired processing lease → retry if attempts remain, otherwise fail;
- older running sync generation → abandoned when the next generation claims;
- older pending calendar generation → superseded by the new enqueue;
- retryable terminal email created by a now-fixed typed boundary → replay only
  through an explicit, fingerprinted operator manifest or user reprocess action.

Automatic recovery is forbidden when it would guess user intent:

- an orphaned historical change source must not be silently reactivated;
- a past invalid calendar event must not be silently shifted or recreated;
- ambiguous duplicate events must not be merged without the guarded repair
  manifest;
- `closed_legacy` proposals must not be relabelled applied/rejected without
  evidence.

Ambiguous cases open a content-free `operational_incidents` row and remain
visible in health.

---

## 4. Zero-downtime migration strategy

This plan uses **expand → migrate callers → contract**. Compatibility exists
only at the database boundary during the named increments and has a mandatory
deletion increment. There is never a Python `if new_path: ... else: ...`, no
second worker implementation, and no fallback after an error.

1. Expand the schema and replace existing RPC bodies while preserving their
   signatures. Old production code therefore continues to call the new single
   implementation during the migration-before-deploy window.
2. Backfill structural state in the same migration. Fail closed when a row
   cannot be classified; map ambiguous closed proposals to `closed_legacy`
   rather than guessing.
3. Deploy callers that read/write the new authority.
4. Observe staging, then production after approval.
5. In a later increment, after every deployed caller uses the new authority,
   drop compatibility columns/triggers and add AST guards.

Every migration that creates a table enables RLS in that same migration,
revokes `PUBLIC`/`anon`, grants only the documented roles, and is exercised
against real Postgres before merge.

---

## 5. Increment S1 — durable email work and truthful health

**Branch:** `fix/durable-email-state-machine`

**Files:**

- `supabase/migrations/20260823000001_durable_email_state_machine.sql`
- `backend/selko/services/emails.py`
- `backend/selko/services/events.py`
- `backend/selko/workers/pool.py`
- `backend/selko/workers/ingestion_runtime.py`
- `backend/selko/api/routes/health.py`
- `backend/selko/api/schemas/common.py`
- `backend/selko/services/email_sync_health.py`
- `backend/tests/integration/test_integration_email_state_machine.py` (new)
- `backend/tests/integration/test_integration_email_ingestion_v2.py`
- `backend/tests/integration/test_schema_contract.py`
- `backend/tests/test_ingestion_runtime.py`
- `backend/tests/test_api_routes.py`
- `docs/database-schema.md`
- `docs/job-queue.md`
- `CLAUDE.md`

### S1.1 Write the failing real-database tests first

Add `test_integration_email_state_machine.py` with these tests:

1. `test_expired_processing_email_is_reclaimed_without_restart`
   - insert a processing email with an expired lease and attempts remaining;
   - call `claim_unprocessed_email` directly;
   - assert the same row is returned with a new owner and generation.
2. `test_expired_processing_email_at_attempt_limit_becomes_failed`.
3. `test_pending_email_cannot_equal_max_attempts` (SQLSTATE `23514`).
4. `test_stale_email_worker_cannot_fail_new_generation`.
5. `test_failure_transition_is_atomic` for retry and terminal branches.
6. `test_reprocess_resets_any_unleased_terminal_or_legacy_pending_row` and
   refuses an actively leased row.
7. `test_next_sync_claim_abandons_previous_expired_run`.
8. `test_stale_sync_generation_cannot_complete_new_run`.
9. `test_health_degrades_on_unclaimable_or_stale_work`.
10. `test_health_counts_use_worker_claim_predicates`.

Do not mock the RPCs. Call them against the reset local Supabase database.

### S1.2 Replace split email transitions with fenced RPCs

In the migration:

1. Replace `claim_unprocessed_email(text, integer)` without changing its public
   signature or returned row shape.
2. First select one expired `processing` row `FOR UPDATE SKIP LOCKED`. Retry it
   when attempts remain; otherwise fail it with safe code
   `lease_expired_at_limit`.
3. Claim the oldest eligible pending row and increment `attempts` plus
   `lock_generation` exactly once.
4. Add fenced RPC:

```sql
fail_email_processing(
    p_email_id uuid,
    p_worker_id text,
    p_generation bigint,
    p_error_code text,
    p_error_detail text,
    p_retry_base_seconds integer,
    p_retry_max_seconds integer
) returns jsonb
```

It locks the row, validates owner+generation, chooses retry versus failed,
clears the lease, and returns `{fenced,status,attempts,next_retry_at}`. Never
branch on error text.

5. Replace `reprocess_email(uuid, uuid)` in place. It may reset any row without
   a live lease, including a legacy pending/exhausted row, and refuses a live
   processing lease. Preserve the owner/service-role check.
6. Repair historical rows before validating:

```sql
CHECK (
  processing_status <> 'pending'
  OR (attempts < max_attempts AND locked_by IS NULL AND locked_until IS NULL)
)
```

Historical pending/exhausted rows become failed with safe code
`legacy_attempts_exhausted`; do not replay them in the migration.

Replace the select-then-update Python failure path with the RPC and require
`worker_id` plus `lock_generation`. Successful extraction still terminates
through `commit_email_extraction`.

### S1.3 Generation-fence provider discovery runs

Add `lease_generation bigint NOT NULL DEFAULT 0` to `email_sync_state` and
`lease_generation bigint NOT NULL` to `email_sync_runs`.

Replace both sync claim RPCs in place: lock state, abandon any older running
row, increment generation, insert the new run with that generation, then
acquire and return the lease. Add:

```sql
CREATE UNIQUE INDEX email_sync_runs_one_running_per_integration
ON public.email_sync_runs(integration_id)
WHERE status = 'running';
```

Complete/fail/heartbeat validate integration, owner, unexpired lease, run id,
and generation. A stale completion returns `false` without mutation.

### S1.4 Make health authoritative

Replace split counting with one service-role RPC,
`health_work_state(p_warning_seconds integer)`, returning safe counts/ages:

- ready, processing, stale-processing, and unclaimable emails;
- stale sync runs;
- pending/dead-letter ingestion items and attachments;
- due integrations, oldest due age, and open incidents.

The ready/stale/unclaimable predicates must match the claim RPC and be pinned
in `test_schema_contract.py`. `IngestionRuntime.health_snapshot()` makes one
RPC call. `down` means a task is dead; `degraded` means unknown DB counts,
stale/unclaimable work, dead letters, stale runs, incidents, or exceeded SLO;
otherwise `ok`.

Make `/health` use the same roll-up instead of hard-coding `ok`.
`/health/ingestion` remains detailed. A reachable degraded service may return
HTTP 200; down or unavailable database returns 503. Add content-free incidents
for unclaimable email, stale processing, and stale sync runs. Do not add a
mutation sweeper; claim-time recovery owns mutation.

### S1.5 Definition of Done

- All ten tests fail before implementation and pass after it.
- Existing fenced-commit, worker-pool, and ingestion-v2 tests pass.
- `./scripts/verify.sh backend` passes locally.
- PR merged with `./scripts/merge-and-cleanup.sh`.
- `./scripts/verify.sh staging` passes after merge.
- A staging drill kills a worker after claim, waits past expiry without
  restarting, and proves reclaim plus stale-worker fencing.
- Health degrades during the drill and returns to ok after recovery.
- No email content or opaque provider identifier enters logs/incidents.

---

## 6. Increment S2 — worker-owned calendar delivery

**Branch:** `refactor/calendar-work-items`

**Files:**

- `supabase/migrations/20260824000001_calendar_work_items.sql`
- `backend/selko/services/calendars.py`
- `backend/selko/services/events.py`
- `backend/selko/workers/pool.py`
- `backend/selko/api/routes/events.py`
- `backend/tests/integration/test_integration_calendar_work_items.py` (new)
- `backend/tests/integration/test_schema_contract.py`
- `backend/tests/test_events_refactor.py`
- `backend/tests/test_workers.py`
- `docs/database-schema.md`
- `docs/job-queue.md`
- `CLAUDE.md`

### S2.1 Schema

Create `public.calendar_work_items`:

| Column | Contract |
|---|---|
| `id uuid primary key` | generated |
| `event_id uuid not null` | FK `events(id)` cascade |
| `user_id uuid not null` | FK `users(id)` cascade; must equal event owner |
| `action text not null` | `upsert` or `cancel` |
| `generation bigint not null` | monotonic per event |
| `status text not null` | `pending`, `processing`, `succeeded`, `failed`, `blocked`, `superseded` |
| `desired_event jsonb` | exact Selko fields for upsert; null for cancel |
| `provider_event_id text` | nullable until first successful upsert |
| `expected_provider_revision text` | optional divergence fence |
| `force_overwrite boolean not null default false` | explicit user override only |
| attempts/retry/lease fields | same bounded pattern as other queues |
| safe failure fields | code plus bounded detail |
| timestamps | created, updated, completed |

Enable RLS immediately. Owners may `SELECT`; only service role may mutate.
Add a partial unique index for one `pending`/`processing` item per event and a
claim index on `(status,next_retry_at,created_at)`.

Add `events.review_status` with domain
`pending_review|active|rejected|cancelled` and backfill from legacy status:

- pending_review → pending_review;
- rejected → rejected;
- cancelled → cancelled;
- approved, cancel_queued, syncing, synced, sync_failed, and pending_change →
  active.

Do not drop `events.status` yet.

### S2.2 One enqueue and one worker path

Add service-role RPCs:

- `enqueue_calendar_work(event,user,action,desired_event,expected_revision,force)`;
- `claim_calendar_work(worker,lease_seconds)`;
- `heartbeat_calendar_work(item,worker,generation,lease_seconds)`;
- `complete_calendar_work(item,worker,generation,provider_event_id,provider_revision)`;
- `fail_calendar_work(item,worker,generation,error_code,error_detail,retryable)`.

Enqueue locks the event, supersedes older pending work, increments the event's
calendar generation, and inserts one item. Claim and completion are generation
fenced. A stale worker cannot update the event or provider id.

For zero downtime, replace the existing event claim/complete/fail RPC bodies so
they delegate to `calendar_work_items` while preserving the response expected
by deployed workers. This is one database implementation, not two Python
paths. Add a temporary trigger that converts legacy
`events.status='approved'|'cancel_queued'` transitions into an enqueue only
until callers move to the enqueue RPC. Name it
`events_legacy_calendar_enqueue_compat` so S5 can delete it mechanically.

Update the worker to treat the work item as authoritative. It may read the
event for source fields, but completion/failure identifies item and generation.
Remove direct status updates from `services/calendars.py`.

### S2.3 Remove inline provider writes from History undo

Refactor `undo_history_event`:

1. Perform the provider divergence read outside a database transaction.
2. Call one atomic event/proposal transition RPC with observed provider
   revision and desired compensation.
3. The RPC restores Selko fields/review state and enqueues upsert or cancel.
4. Return after enqueue. Do not call
   `restore_calendar_event_from_selko_fields` or
   `delete_calendar_event_only` from the request.
5. The worker revalidates `expected_provider_revision` immediately before the
   write. Divergence becomes blocked and preserves the event/proposal state.

Add AST tests rejecting provider mutation calls from `backend/selko/api/**`
and event decision functions.

### S2.4 Required tests

- approving a new event enqueues one upsert;
- accepting update enqueues one upsert;
- accepting cancellation enqueues one cancel;
- undo applied update enqueues compensation and makes no provider call;
- undo new approval enqueues cancel and makes no provider call;
- newer enqueue supersedes older pending generation;
- expired processing work is reclaimed;
- stale generation completion is fenced;
- provider divergence blocks rather than overwrites;
- explicit force is recorded and permits the write;
- legacy event-status transition creates exactly one work item;
- RLS/function privilege contracts execute against real Postgres.

### S2.5 Definition of Done

- `./scripts/verify.sh backend` passes.
- No API/service decision path mutates Google Calendar.
- One worker owns upsert, cancel, restore, and delete semantics.
- PR merged/cleaned and `./scripts/verify.sh staging` passes.
- Staging drills cover upsert, cancellation, compensating undo, expired lease,
  stale generation, and divergence block.

---

## 7. Increment S3 — first-class change proposals

**Branch:** `refactor/event-change-proposals`

**Files:**

- `supabase/migrations/20260825000001_event_change_proposals.sql`
- `backend/selko/services/events.py`
- `backend/selko/api/routes/events.py`
- `backend/selko/api/schemas/events.py`
- `backend/tests/integration/test_integration_event_change_proposals.py` (new)
- `backend/tests/integration/test_integration_fenced_event_commit.py`
- `backend/tests/integration/test_schema_contract.py`
- `backend/tests/test_events_refactor.py`
- `scripts/repair_review_queue_integrity.py`
- `backend/tests/test_repair_review_queue_integrity.py`
- `docs/database-schema.md`
- `CLAUDE.md`

### S3.1 Schema

Create `public.event_change_proposals`:

| Column | Contract |
|---|---|
| `id uuid primary key` | generated |
| `event_id uuid not null` | FK event cascade |
| `user_id uuid not null` | FK user cascade; matches event owner |
| `source_id uuid not null unique` | FK `event_sources(id)` restrict |
| `kind text not null` | `material_update` or `cancellation` |
| `status text not null` | `pending`, `applied`, `rejected`, `superseded`, `closed_legacy` |
| `change_set jsonb not null` | validated field-diff envelope |
| `event_snapshot_before jsonb not null` | complete reversible Selko state |
| `resolution_reason text` | safe enum-like reason; null while pending |
| lifecycle timestamps | created, resolved, updated |

Enable RLS in the same migration. Owners may `SELECT`; only service role may
mutate. Add a partial unique index on `event_id WHERE status='pending'`.

Backfill without guessing:

1. Latest non-undone update/cancellation source on a legacy pending-change
   event → pending.
2. Non-undone proposal source on a non-pending-change event → applied.
3. Undone source with conclusive action-history evidence → rejected or
   superseded.
4. Any other structurally complete source → `closed_legacy` with reason
   `legacy_state_ambiguous`.
5. A legacy pending-change event without exactly one complete candidate aborts
   the migration and prints only counts/ids, never content.

Keep `event_sources.change_set`, `event_snapshot_before`, and `is_undone`
during S3/S4 for deployed-client compatibility. New RPCs treat proposals as
authoritative and mirror compatibility fields transactionally. There is no
read fallback from proposal to source.

### S3.2 Replace proposal transitions

Replace apply/reject RPC bodies in place and add reopen:

- apply locks event/proposal, requires pending, applies asserted fields, marks
  applied, updates review status, and enqueues calendar work;
- reject locks event/proposal, restores required Selko state, marks rejected,
  and enqueues only explicitly required compensation;
- reopen locks an applied proposal/event, restores the before-snapshot, marks
  pending, and enqueues compensation through S2.

Update `commit_email_extraction` in place. For a material update/cancellation:

1. preserve the email lease and candidate-band fences;
2. supersede the current pending proposal;
3. insert or idempotently refresh provenance through the commit RPC only;
4. insert one pending proposal with change set and snapshot;
5. keep `events.review_status='active'`;
6. mirror legacy fields only during S3/S4;
7. terminate the email in the same transaction.

Python may compute fields but may not write lifecycle state. Replace
`_latest_pending_change_source` with a typed proposal fetch. API routes resolve
the owned pending proposal and call RPCs with its id; concurrent replacement
returns conflict, never the wrong proposal.

Update the guarded repair CLI in the same increment. It may still merge exact
duplicate groups and queue exact cancellations. Replace the legacy
`mark_source_resolved` action—which flips `event_sources.is_undone`—with an
explicit proposal action requiring event id, proposal id, user id, expected
proposal hash, and an enumerated operator reason. The CLI calls a proposal RPC,
writes `event_repair_audit`, remains dry-run by default, and retains its
absolute-manifest/confirmed-user/reverse-artifact production gates.

### S3.3 Bidirectional deferred invariant

Replace `enforce_pending_change_proposal` with a transaction-end invariant:

- at most one pending proposal per event;
- source/event/user ownership matches;
- change set and snapshot are non-empty objects;
- during S3/S4, compatibility `events.status='pending_change'` exists exactly
  when a pending proposal exists;
- `events.review_status='active'` for update/cancellation proposals.

S5 removes only the compatibility clause.

### S3.4 Required tests

- extraction creates proposal + source + terminal email atomically;
- candidate/lease conflict writes neither proposal nor source;
- replacement supersedes the old pending proposal;
- apply/reject/reopen update event, proposal, and calendar work atomically;
- concurrent apply versus replacement returns serialization conflict;
- event deletion cascades proposals and source deletion is restricted;
- authenticated owner can select but cannot mutate proposals;
- malformed/missing snapshots and change sets fail closed;
- backfill fixtures cover every classification rule;
- repair CLI dry-run/apply use proposal ids and hashes, refuse stale manifests,
  and never update `event_sources.is_undone` directly.

### S3.5 Definition of Done

- `./scripts/verify.sh backend` passes.
- `commit_email_extraction` remains the only extraction persistence path.
- All proposal transitions execute against real Postgres.
- PR merged/cleaned and `./scripts/verify.sh staging` passes.
- Staging exercises render, apply, reject, supersede, and reopen once each.

---

## 8. Increment S4 — migrate web, iOS, and Android

**Branch:** `refactor/client-event-state-model`

This is one cross-platform contract increment. Do not migrate one client and
leave another reading legacy proposal state indefinitely.

### S4.1 Shared query shape

Every Review/History/event-detail query embeds:

```text
events(
  ...,
  event_sources(..., emails(...)),
  event_change_proposals(...),
  calendar_work_items(...)
)
```

Changes means a pending proposal, not `events.status='pending_change'`. New
means `events.review_status='pending_review'`. Calendar presentation uses the
latest non-superseded work item.

### S4.2 Web files

- `frontend/src/lib/services/events.js`
- `frontend/src/lib/services/email-history.js`
- `frontend/src/lib/services/event-sources.js`
- `frontend/src/lib/services/index.js`
- `frontend/src/lib/types.js`
- `frontend/src/lib/live-updates.js`
- `frontend/src/routes/app/+page.svelte`
- `frontend/src/routes/app/history/+page.svelte`
- `frontend/src/routes/app/events/[id]/+page.svelte`
- `frontend/src/lib/components/ChangeCard.svelte`
- corresponding `frontend/src/**/__tests__/` files

Add typed proposal/work definitions. Delete unused direct source
undo/redo/count exports and tests. Subscribe to proposals and calendar work;
keep source invalidation only for provenance/sender display.

`ChangeCard` receives a proposal explicitly. It does not search a source array
or fall back to any source containing `change_set`. Missing proposal data
remains fail-closed.

### S4.3 iOS files

- `ios/Selko/Features/Events/Models/CalendarEvent.swift`
- `ios/Selko/Features/Events/Models/EventSource.swift`
- new `EventChangeProposal.swift` and `CalendarWorkItem.swift`
- `ios/Selko/Features/Events/Services/EventService.swift`
- Review and History view models
- `ios/Selko/Core/LiveUpdates/LiveUpdateService.swift`
- corresponding `ios/SelkoTests/**`

### S4.4 Android files

- `android/app/src/main/java/net/melisma/selko/data/model/CalendarEvent.kt`
- `android/app/src/main/java/net/melisma/selko/data/model/EventSource.kt`
- new `EventChangeProposal.kt` and `CalendarWorkItem.kt`
- `android/app/src/main/java/net/melisma/selko/data/repository/EventRepository.kt`
- `android/app/src/main/java/net/melisma/selko/data/repository/LiveUpdateRepository.kt`
- Review/History view models and corresponding tests

### S4.5 Cross-platform acceptance matrix

Each platform proves:

- New renders from review status;
- pending update/cancellation renders from proposal;
- apply/reject targets only that proposal;
- superseded proposal never appears in Changes;
- `closed_legacy` appears only in History with neutral wording;
- delivery pending/processing/failed/blocked is distinct from review;
- proposal and work updates refresh the visible event;
- missing proposal fails closed;
- light/dark, desktop/mobile, and accessibility remain correct.

### S4.6 Definition of Done

- Frontend unit tests and `npm run check` pass.
- iOS tests pass with an isolated result bundle.
- Android unit tests pass.
- `./scripts/capture-all-screenshots.sh` passes; all web/iOS/Android images are
  reviewed.
- Backend contract tests pass for query/RLS shapes.
- PR merged/cleaned.
- `./scripts/verify.sh staging` passes because schema/query contracts changed.

---

## 9. Increment S5 — contract and delete dead architecture

**Branch:** `refactor/remove-legacy-event-state`

**Gate:** S4 must already be deployed and observed in staging. Search the
deployed revision and every client for the legacy fields/symbols below before
writing S5. Any caller blocks the increment.

### S5.1 Contract migration

`supabase/migrations/20260826000001_remove_legacy_event_state.sql`:

1. Assert no proposal/event invariant violations.
2. Assert every active delivery state has calendar work history.
3. Drop `events_legacy_calendar_enqueue_compat`.
4. Drop the old pending-change trigger/function.
5. Remove compatibility writes from extraction/apply/reject RPCs.
6. Drop `event_sources.change_set`, `event_snapshot_before`, and `is_undone`.
7. Revoke authenticated `UPDATE`/`DELETE` on `event_sources`; preserve the
   owner-scoped read contract and service-role extraction writes.
8. Drop legacy calendar queue columns after confirming no current reference
   doc/client query uses them.
9. Drop the overloaded `events.status` only through the already-deployed
   `review_status` contract. Do not add a compatibility view.
10. Update CHECK-domain pins in `test_schema_contract.py`.

If any legacy column has a separate valid purpose, amend this plan and name
the owner before coding. “Maybe a client still needs it” is not sufficient.

### S5.2 Delete retired code

From `backend/selko/services/events.py`, delete these functions and tests when
their replacement is live:

- `ensure_email_event_source` if no runtime caller remains;
- `create_event`;
- `create_event_from_gcal_match`;
- `create_pending_change_from_gcal`;
- `propose_local_change`;
- `update_event`;
- `undo_email_contribution`;
- `redo_email_contribution`;
- `_latest_pending_change_source`;
- direct reject/restore helpers replaced by decision RPCs.

Delete unreachable statements after unconditional raises, not only the raises.
Delete obsolete imports, mock-only tests, and unused web source mutations.

### S5.3 Architecture guards

Extend `backend/tests/test_reachability.py` or add
`backend/tests/test_state_ownership.py` with AST checks that reject:

- banned retired function definitions;
- event writes outside the approved persistence adapter;
- proposal/calendar-work/email lifecycle writes outside their RPC adapters;
- Google Calendar mutation helpers in API/event-decision code;
- statements after an unconditional function-level `raise`;
- compatibility triggers/names remaining after S5.

Keep allowlists explicit and minimal. Tests are not allowlisted because they
call old helpers; rewrite or delete them.

### S5.4 Documentation cleanup

Update:

- `CLAUDE.md`;
- `docs/database-schema.md`;
- `docs/job-queue.md`;
- `docs/api-workflow.md`;
- `docs/supabase-frontend-queries.md`;
- `docs/ui/02-screen-specs.md`;
- `docs/ui/03-patterns-and-components.md`;
- `docs/manual-email-to-calendar-walkthrough.md`;
- any spec that describes `pending_change`/`is_undone` as current architecture.

Run `rg` for removed symbols/columns. Historical migrations may contain them;
current source, tests, and reference docs may not.

### S5.5 Definition of Done

- `./scripts/verify.sh backend` passes.
- UI tests pass if contract cleanup touches checked-in models/queries.
- No production source depends on compatibility state.
- PR merged/cleaned and `./scripts/verify.sh staging` passes.
- Staging health shows zero unclaimable emails, stale runs, orphan proposals,
  and unfenced calendar work.
- After approved production deployment and verification, fold durable content
  into references and delete this completed spec per `docs/specs/README.md`.

---

## 10. Review-comment and worktree rules

Each implementation increment edits source, so run Definition of Done step 0
before creating its worktree: inspect the last ten merged PRs, claim actionable
unaddressed comments, fix them, and close the original loop.

Then follow `docs/parallel-agents.md`: one feature worktree, one branch, one PR,
local scoped verification before merge, merge-and-cleanup, then mandatory
staging verification for every backend/schema increment.

This document itself is docs-only. Its increment must not inspect, claim, or
absorb unrelated PR comments.

---

## 11. Global non-goals

- Changing calendar identity matching, candidate fingerprints, or prompts.
- Replaying every historical failed email.
- Automatically correcting semantic event data such as invalid times.
- Adding a second worker service or transport.
- Holding a transaction across provider or LLM I/O.
- A generic periodic sweeper that changes status by age alone.
- Keeping compatibility fields after S5.

---

## 12. Final acceptance drill

Run on staging after S5 and before requesting production deployment:

1. Claim one eligible email, kill its task, let the lease expire, and prove a
   new generation reclaims it without service restart.
2. Attempt old-generation completion and prove it is fenced.
3. Create two concurrent same-day updates; prove one event and one current
   proposal.
4. Supersede with a newer update; prove only the newer proposal is in Changes.
5. Apply it; prove one calendar upsert is queued and only the worker writes.
6. Undo it; prove compensation is queued and the proposal reopens without a
   provider write in the request.
7. Simulate provider divergence; prove blocked/no overwrite. Repeat with
   explicit force and prove the override is recorded.
8. Crash/reclaim provider discovery; prove prior run abandoned and only one
   run remains running.
9. During each fault, prove health degraded with safe counts; after recovery,
   prove health returns to ok.
10. Query zero counts for unclaimable email, expired processing, stale running
    sync, multiple/malformed pending proposals, multiple active calendar work,
    and drill-created open incidents.

Record commands, timestamps, safe counts, and HTTP responses. Never record
production content, tokens, provider ids, subjects, addresses, or raw errors.
