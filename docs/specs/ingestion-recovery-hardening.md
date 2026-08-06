# Ingestion & Recovery Hardening (top-up)

**Status:** Planned, not started. Written 2026-08-03.

This is the top-up plan for the review of PRs #229–#240 — durable polling email
ingestion v2 (#231–#235) and calendar OAuth reconnect recovery (#236–#240). It
covers every defect, smell, scalability cliff, evidence gap and process gap that
review found, sequenced into implementable increments.

**The architecture is not in question.** Database leases for single ownership,
discovery-before-acquisition, and the SQL attachment readiness gate are all
correct and stay. This plan fixes the execution gaps inside that design.

**Gating rule:** increments 1–4 are prerequisites for the production cutover
described in `polling-email-ingestion-v2.md` ("Production cutover runbook").
Increments 5–10 can land after cutover, but 5 should land close behind it
because it is what makes the cutover observable at all.

---

## Why this is needed

Review found four bugs. One of them permanently destroys user email, one
silently disables ingestion entirely, one is a race that degrades LLM output
non-deterministically, and one is currently red on `main`. None of them are
visible to the existing test suite, because all four live in the seams that
mocks cannot see: a substring classifier, an unsupervised asyncio task, a
two-round-trip write, and a module-scope side effect.

Underneath that is the real problem: **there is no runtime evidence.** No APM,
no metrics, and a `/health` endpoint that returns `ok` while every ingestion
loop is dead. The system's own state machine already records
`consecutive_failures`, dead-letter counts and run history, and nothing reads
them except a health evaluator that has the same fatal fragility as the workers
it watches.

---

## Increment 1 — Unbreak `main` and make frontend tests environment-independent

**Branch:** `fix/frontend-test-env` · **Scope:** `frontend/**` · **Size:** tiny

### Problem

`Frontend Tests` is failing on `main` (run `30792019849`, commit `6e57c713`):

```
FAIL src/lib/components/__tests__/ConnectionRecovery.test.js
Error: supabaseUrl is required.
 ❯ createClient node_modules/@supabase/supabase-js/src/index.ts:65:9
 ❯ src/lib/supabase.js:6:25
 ❯ src/lib/services/integrations.js:1:1
Test Files  1 failed | 27 passed (28)
```

PR #240 added `import { fetchCalendarRecovery } from '$lib/services/integrations.js'`
to `ConnectionRecovery.svelte`. That module imports `$lib/supabase.js`, which
calls `createClient(...)` at module scope. CI has no `frontend/.env`, so
`import.meta.env.VITE_SUPABASE_URL` is `undefined` and the import throws.

**This cannot be reproduced locally.** Vite loads the gitignored `frontend/.env`
for `import.meta.env` regardless of shell environment — verified:

```
env -u VITE_SUPABASE_URL npx vitest run ConnectionRecovery.test.js → 2 passed
```

24 source files import `$lib/supabase`. Any future component that reaches a
service module inherits the same trap. Because the merge policy is
deliberately "local tests are the gate, CI is a safety net", this class of
failure merges and then sits unnoticed on `main`.

### Change

`frontend/vitest.config.js` — pin test-time env so no test depends on a
gitignored file:

```js
test: {
    // ...
    env: {
        VITE_SUPABASE_URL: 'http://localhost:54321',
        VITE_SUPABASE_ANON_KEY: 'test-anon-key'
    },
```

Vitest populates both `process.env` and `import.meta.env` from `test.env`, so
all 24 importers are fixed at once and local runs match CI.

### Verify

- `npm run test:unit` passes with `frontend/.env` temporarily renamed away —
  this is the actual acceptance criterion, not a plain local pass.
- `npm run check` clean.
- No screenshots needed (no rendered-output change).

---

## Increment 2 — Structural provider-error classification

**Branch:** `fix/ingestion-error-classification` · **Scope:** `backend/**` ·
**Size:** medium · **Priority: P0 — data loss**

### Problem

`safe_error_code()` (`backend/selko/services/email_ingestion.py:61`) falls
through to substring matching on `str(exc).lower()`. `gmail.py` wraps every
`HttpError` into a `GmailError` that carries **no status code**, so the
status-code branch never fires for Gmail at all. Measured against realistic
exceptions:

| Exception | Classified as | Terminal? |
|---|---|---|
| `invalid_grant: Token has been expired or revoked.` | `parse_invalid` | **yes** |
| Gmail 401 `returned "Invalid Credentials"` | `parse_invalid` | **yes** |
| Gmail 403 rate limit | `unknown` | no |
| Gmail 500 backend error | `unknown` | no |
| PostgREST disconnect | `unknown` | no |

`"Invalid Credentials"` contains the substring `invalid`. `run_acquisition_once`
(`workers/email_ingestion.py:380`) passes
`terminal=safe_error_code(exc) == "parse_invalid"`, so the item goes to
`dead_letter` on its **first** attempt and is never retried — not even after the
user reconnects. **The email is permanently lost from the pipeline.**

Two aggravating consequences:

1. No Gmail error ever reaches `p_auth_failure=True`, so `fail_email_sync` never
   flips `integrations.status` to `expired`. The user is never prompted to
   reconnect, and the ConnectionRecovery card shipped in #240 never fires for
   Gmail.
2. `last_error_code` reads `parse_invalid`, pointing diagnosis at the parser
   rather than at auth.

The correct pattern already exists in this codebase — `classify_calendar_error`
(`services/calendars.py:101`) is typed, branches on Google's structured
`reason`, distinguishes 403-scope from 403-ratelimit, and returns explicit
`retryable` / `counts_toward_circuit_breaker` flags. The email path shipped
hours earlier and never got that treatment.

### Change

**2a. Give `GmailError` the same shape as `GraphHttpError`**
(`services/gmail.py:31`). Mirror `outlook.py:84`:

```python
class GmailError(Exception):
    """Raised when Gmail operations fail."""

    def __init__(self, message: str, *, status_code: int | None = None,
                 reason: str | None = None):
        super().__init__(message)
        self.status_code = status_code
        self.reason = reason
```

Every `except HttpError as e: raise GmailError(...)` site in `gmail.py`
(lines ~179, 351, 377, 401, 418, 447, 518, 543) passes
`status_code=getattr(e.resp, "status", None)` and `reason=` extracted with the
same best-effort JSON parse `calendars.py:79` (`_google_error_reason`) already
uses. Lift that helper into a shared module — suggested
`selko/services/google_errors.py` — and import it from both `calendars.py` and
`gmail.py` rather than duplicating it.

Add a distinct `GmailAuthError(GmailError)` raised where `RefreshError` is
caught, so auth is a **type**, not a string.

**2b. Rewrite `safe_error_code` to branch on structure only.** Delete every
`in text` test. New contract:

| Condition | Code | Retryable | Auth failure |
|---|---|---|---|
| `ProviderAuthenticationError` / `GmailAuthError` | `provider_auth_expired` | yes | **yes** |
| `ProviderMessageMissingError` | `provider_message_missing` | n/a (removed) | no |
| `status_code == 429`, or 403 with a rate-limit `reason` | `provider_rate_limited` | yes | no |
| `status_code == 401`, or 403 with a scope `reason` | `provider_auth_expired` | yes | **yes** |
| `status_code == 403` (other) | `provider_forbidden` | yes | no |
| `status_code in (500,502,503,504)` | `provider_transient` | yes | no |
| `httpx`/`requests`/`postgrest` transport exception types | `database_transient` | yes | no |
| anything else | `unknown` | yes | no |

Reuse the existing `_RATE_LIMIT_REASONS` / `_INSUFFICIENT_SCOPE_REASONS` sets
from `calendars.py` (move them alongside `_google_error_reason`).

**2c. Nothing is terminal on a code alone.** Delete the
`terminal=safe_error_code(exc) == "parse_invalid"` argument at
`workers/email_ingestion.py:380`. An item becomes `dead_letter` only by
exhausting `max_attempts` (already handled inside `fail_email_ingestion_item`)
or by an explicitly non-retryable classification. Introduce a
`ProviderPermanentError` for genuinely unparseable payloads and raise it
deliberately from the parsers — never infer permanence from a message.

**2d. Add a `retryable` field** to the classification so `fail_item` and
`fail_sync` take it from one place instead of each re-deriving it.

### Data repair

Existing `dead_letter` items misclassified by this bug must be revived. New
migration `20260803000001_revive_misclassified_dead_letters.sql`:

```sql
-- The pre-fix substring classifier dead-lettered any provider error whose
-- message contained "invalid" — including Gmail 401 "Invalid Credentials"
-- and invalid_grant — on the FIRST attempt. Those items were never retried.
UPDATE public.email_ingestion_items
SET acquisition_status = 'pending',
    attempts = 0,
    next_retry_at = NULL,
    last_error_code = NULL,
    updated_at = now()
WHERE acquisition_status = 'dead_letter'
  AND last_error_code = 'parse_invalid';
```

Scoped to `parse_invalid` specifically so genuine dead letters are untouched.
Run against staging first and record the affected row count in the PR body.

### Tests

`backend/tests/test_email_ingestion_v2.py` — a parametrized classification table
over **captured real exception strings**, asserting `(code, retryable,
auth_failure)`:

- Gmail 401 `Invalid Credentials`, 403 `userRateLimitExceeded`,
  403 `insufficientPermissions`, 429, 500, 404
- `RefreshError: invalid_grant`
- `GraphHttpError` 401 / 404 / 410 / 429 / 503
- `ProviderAuthenticationError`, `ProviderMessageMissingError`
- a raw PostgREST disconnect

Plus a regression test asserting no acquisition failure is terminal on the first
attempt, and one asserting a Gmail 401 during discovery sets
`integrations.status = 'expired'`.

---

## Increment 3 — Supervise every ingestion loop

**Branch:** `fix/ingestion-loop-supervision` · **Scope:** `backend/**` ·
**Size:** small · **Priority: P0 — silent total outage**

### Problem

`claim_due_sync` is called *outside* the `try` in `run_sync_once`
(`workers/email_ingestion.py:106`); same for `claim_due_reconciliation`
(`:129`) and `claim_item` (`:364`). `coordinator_loop` (`:483`) and
`_claim_loop` (`:504`) have no exception handling at all, and
`EmailSyncHealthEvaluator.run` (`services/email_sync_health.py:197`) calls
`await self.evaluate_once()` bare.

Proved:

```
coordinator task done? True
exception: RuntimeError('Server disconnected without sending a response')
claim attempts made: 1
```

**One transient Supabase error, one attempt, loop dead forever.**

It is completely silent: `IngestionRuntime` never inspects task state, and
`stop()` gathers with `return_exceptions=True`, so the traceback is swallowed at
shutdown and never logged. The health evaluator that would notice stale polling
runs in the same process and dies from the same blip.

This is a regression against a correct pattern already in the repo:
`WorkerPool._worker_loop` (`workers/pool.py:164–181`) wraps its whole body,
handles `CancelledError` separately, and backs off on error.

### Change

**3a.** In `EmailIngestionWorker`, wrap each `run_*_once` body — claim included —
so the loop can never propagate. Add a shared helper mirroring the pool's shape:

```python
async def _guarded(self, run_once) -> bool:
    try:
        return await run_once()
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("Ingestion loop iteration failed; backing off")
        await asyncio.sleep(self.config.email_worker_error_backoff_seconds)
        return True   # treated as work, so idle backoff does not compound
```

Apply in `coordinator_loop` and `_claim_loop`. Add
`email_worker_error_backoff_seconds: float = 5.0`
(`EMAIL_WORKER_ERROR_BACKOFF_SECONDS`) to `config.py` and `.env.example`.

**3b.** Same guard inside `EmailSyncHealthEvaluator.run`.

**3c. Add a watchdog to `IngestionRuntime`** (`workers/ingestion_runtime.py`).
Track `(name, factory, task)` per spawned loop. A supervisor task ticks every
`email_runtime_watchdog_seconds` (default 30) and, for any task that is `done()`
while `stop_event` is unset:

- `logger.exception("Ingestion task %s exited unexpectedly", name, exc_info=task.exception())`
- respawn it from its factory
- increment a restart counter exposed to increment 5

**3d.** Expose runtime state for the health endpoint:

```python
def status(self) -> dict[str, Any]:
    """Live task health, consumed by /health/ingestion."""
```

Returning per-task `{name, alive, restarts, last_exception_code}` plus
`instance_id`.

### Tests

`backend/tests/test_ingestion_runtime.py`:

- the exact proof above, inverted: a claim that raises once must leave the loop
  running and a second claim must be attempted
- a task killed mid-flight is respawned by the watchdog within one tick
- `stop()` still shuts down cleanly and does **not** respawn
- health evaluator survives an `evaluate_once` exception

---

## Increment 4 — Close the attachment-descriptor race

**Branch:** `fix/attachment-descriptor-race` · **Scope:** `backend/**`,
`supabase/**` · **Size:** medium · **Priority: P0 — silent quality loss**

### Problem

`acquire_item` (`workers/email_ingestion.py:395`) calls `save_emails(...)`,
which upserts the email row with `processing_status` defaulting to `pending`.
Only *afterwards* (`:429`) does it call `ensure_attachment_descriptors`, which
performs a **SELECT + INSERT per descriptor** in separate PostgREST round-trips
(`services/email_ingestion.py:249–281`).

The readiness gate in `claim_unprocessed_email`
(`20260801000001_polling_email_ingestion_v2.sql:459`) is:

```sql
AND NOT EXISTS (
    SELECT 1 FROM public.attachments a
    WHERE a.email_id = e.id
      AND a.ingestion_status IN ('pending', 'processing', 'retry')
)
```

Between the email upsert and the first descriptor insert that set is **empty**,
so the gate passes. Three pool workers poll every 1s; for a five-attachment
email the window is ten sequential round-trips wide.

The LLM then processes the body with no attachments. Because it is timing
dependent, it presents as flaky extraction quality rather than as a race — the
worst possible failure signature.

### Change

Make the email row and its descriptors a single transaction. New RPC in
`20260803000002_atomic_email_with_descriptors.sql`:

```sql
CREATE OR REPLACE FUNCTION public.save_email_with_attachment_descriptors(
    p_user_id uuid,
    p_email jsonb,
    p_descriptors jsonb
) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
```

Semantics:

- upsert the email on its existing conflict target
- insert any descriptor not already present for that `email_id`
  (`ON CONFLICT` on the existing partial unique index
  `attachments_email_provider_attachment_idx`), preserving the "do not reset
  stored rows" guarantee `ensure_attachment_descriptors` currently provides
- return the email id

Both writes commit together, so the gate is never observed in the gap.

`acquire_item` calls the RPC once instead of `save_emails` + N×(SELECT+INSERT).
Keep `EmailIngestionRepository.attachment_readiness` — it is a useful
diagnostic mirror — and keep `ensure_attachment_descriptors` only if repair
tooling still needs it; otherwise delete it.

Grants: `REVOKE ALL ... FROM PUBLIC`, `GRANT EXECUTE ... TO service_role`
(explicit, per increment 8b).

### Tests

- `backend/tests/integration/test_integration_email_ingestion_v2.py` — acquire
  an email with three attachment descriptors, then assert
  `claim_unprocessed_email` returns nothing until all three reach a terminal
  `ingestion_status`. This is the regression test; it must run against a real
  database because the bug is a transaction-boundary bug.
- Unit test asserting a re-acquired email does not duplicate descriptors or
  reset a `stored` row.

**Side benefit:** removes 2N PostgREST round-trips per email from the hot path.

---

## Increment 5 — Make ingestion observable

**Branch:** `feat/ingestion-observability` · **Scope:** `backend/**` ·
**Size:** medium · **Priority: P1 — land close behind cutover**

### Problem

`grep -rni "sentry\|prometheus\|statsd\|datadog\|opentelemetry" backend/` returns
nothing. `/health` returns `{"status": "ok"}` unconditionally and `/health/db`
only probes `users`. Render's health check stays green while every ingestion
loop is dead (increment 3). The state machine already records
`consecutive_failures`, `last_error_code`, run history and dead-letter counts —
nothing reads them except the health evaluator.

### Change

**5a. `GET /health/ingestion`** in `backend/selko/api/routes/health.py`.
Service-role read, no user data, safe codes only:

```json
{
  "status": "ok | degraded | down",
  "background_processing_enabled": true,
  "tasks": [{"name": "email-sync-coordinator", "alive": true, "restarts": 0}],
  "integrations_due": 2,
  "oldest_next_poll_seconds": 41,
  "leases_held": 1,
  "items_pending": 17,
  "items_dead_letter": 0,
  "attachments_dead_letter": 0,
  "open_incidents": 0
}
```

`down` when any task is not alive; `degraded` on non-zero dead letters, open
incidents, or `oldest_next_poll_seconds` beyond
`email_health_warning_seconds`. Consumes `IngestionRuntime.status()` from 3d.
Point the Render health check at this once it is stable.

**5b. Sentry.** Add `sentry-sdk[fastapi]` to `backend/pyproject.toml`, init in
`create_app()` behind `SENTRY_DSN` (unset = no-op, so local and CI are
unaffected). Set `environment=config.environment`. Explicitly capture from the
increment-3 watchdog — an unexpectedly exited task is exactly the event with no
other reporting path today.

**5c. Structured counters.** One `logger.info` per completed sync run with a
stable key/value shape (`run_kind`, `provider`, `duration_ms`,
`provider_ids_seen`, `items_inserted`, `items_existing`, `error_code`) so Render
log search can answer "is ingestion moving" without a metrics backend. Never log
subjects, addresses, message ids or tokens — the existing safe-payload
discipline in `email_sync_health.py` is the standard.

**5d. Decide the notifier.** `OPERATIONAL_NOTIFICATION_*` are unset because no
Resend account exists, so `operational_incidents` rows never reach a human.
Either provision Resend, or point `ResendOperationalNotifier` at an existing
channel. Until then `/health/ingestion` is the only alerting surface — say so
explicitly in `docs/ci-cd.md`.

---

## Increment 6 — Provider-call efficiency and idle cost

**Branch:** `perf/ingestion-provider-calls` · **Scope:** `backend/**` ·
**Size:** medium · **Priority: P1 — cliff, not a fire**

### Problems

**6a. Gmail discovery is serial and double-fetches.** `_discover_gmail`
(`workers/email_ingestion.py:203–218`) calls `get_message_metadata` once per
message in a plain `for` loop; acquisition later calls `get_full_message` for
the same message. Two API calls per message, no batching, no concurrency.

**6b. Reconciliation multiplies it.** `email_reconcile_weekly_days = 90` means
once a week, per user, discovery lists and fetches metadata for **every message
in a 90-day window**. On a 20k-message mailbox that is 20k serial round-trips
and ~100k Gmail quota units in one pass, held inside a 900s lease kept alive by
heartbeats. It will hit the per-user rate limit — and after increment 2 that
correctly classifies as `provider_rate_limited` and retries the whole pass.

**6c. A wasted Gmail call on every poll.** `email_ingestion.py:187` fetches
`get_user_profile` unconditionally, but `replacement_cursor` is only used when
there is no cursor, or when history expired — where it is re-fetched anyway
(`:198`). One wasted call per integration per 5-minute poll, forever.

**6d. Idle-cost regression in the old pool.** `_process_integration_recovery`
(`workers/pool.py:271`) runs on *every* idle tick of *every* worker:
`claim_integration_recovery` plus `refresh_waiting_calendar_recoveries`. At
`worker_pool_size=3` and `worker_idle_sleep_seconds=1.0` that is ~2 extra
RPCs/worker/second — roughly 500k no-op round-trips per day when nothing is
recovering. The new ingestion workers got geometric idle backoff
(`idle_backoff`, `email_ingestion.py:492`); the recovery additions to the old
pool did not.

**6e. Health evaluator is N+1 and globally scoped.** `evaluate_once`
(`services/email_sync_health.py:111`) loads every `email_sync_state` row, then
issues two `count="exact"` queries per row, then a select per expected incident
— every 300s. Fine at one user; 2000+ queries per cycle at 1000 integrations.
Worse, it resolves **any** open row in `operational_incidents` not in its own
`expected` set (`:183–187`). The table name is generic; the first non-email
subsystem to write there will have its incidents silently auto-resolved.

### Changes

- **6a** — use Gmail's batch endpoint for metadata (`BatchHttpRequest`, 100 per
  batch, matching the existing `_chunks(..., size=100)` page size), or run
  metadata fetches through a bounded `asyncio.Semaphore`. Batching is preferred:
  it is one HTTP request per 100 messages and materially reduces quota.
  Separately, evaluate skipping the metadata pass entirely for Outlook-style
  delta results where folder membership is already known.
- **6b** — bound reconciliation by *work*, not just window: cap identities per
  reconcile pass (new `email_reconcile_max_identities`, default ~2000) and
  resume from where it stopped on the next pass. A reconcile that cannot finish
  in one lease must make partial forward progress rather than restarting.
- **6c** — move the `get_user_profile` call inside the two branches that
  actually use it.
- **6d** — give `_process_integration_recovery` its own backoff: skip the
  refresh RPC unless at least `recovery_refresh_interval_seconds` (default 30)
  has elapsed since this worker last ran it. Track on the pool instance.
- **6e** — replace the per-state count queries with a single grouped aggregate
  (one query returning dead-letter counts by `integration_id`), and scope the
  resolution sweep with `.like("incident_key", "email-sync:%")` so it can only
  resolve incidents it owns.

### Tests

Unit tests asserting: batched metadata produces the same discovered set as the
serial path; `get_user_profile` is not called on the incremental happy path; the
recovery refresh is throttled; the incident sweep does not resolve a foreign
`incident_key`.

### As built

Landed in `perf/ingestion-provider-calls`. Three places where the
implementation deviates from the sketch above, all deliberate:

- **6b resumes by identity, not by offset.** A plain `identities[:cap]` is not
  resumable: `list_message_ids` returns the same window every pass, so the same
  prefix would be re-truncated forever and the tail of a large mailbox would
  never reconcile at all. The pass instead first drops identities already in
  `email_ingestion_items` (via `known_provider_message_ids`, chunked to keep the
  PostgREST request line bounded), then caps what remains. Because the work
  processed this pass is committed by `upsert_discovered`, the next pass sees a
  smaller undiscovered set and continues from there. On a healthy mailbox this
  also takes a reconcile to near-zero provider calls, which the window-only cap
  never did.
- **Outlook is deliberately not capped.** The quota cliff in 6b is Gmail-specific:
  Gmail costs an extra metadata round-trip *per message*, while Graph returns
  message metadata inline with the folder listing, so an Outlook reconcile is
  O(folders) rather than O(messages). Capping there would mean breaking out of
  the folder loop with folders unvisited, and the folder query has no `ORDER BY`,
  so *which* folders got skipped would be arbitrary — risking a folder going
  unreconciled indefinitely to solve a cost problem Outlook does not have.
  Per-message identity filtering is also unavailable for Outlook: a message in
  two folders must be seen under both so `upsert_discovered` can union its
  `provider_folder_ids`.
- **6d throttles both recovery RPCs, not just the refresh.** The Change above
  named only `refresh_waiting_calendar_recoveries`, but the Problem attributes
  the ~500k/day to that *plus* `claim_integration_recovery`, which also ran
  unthrottled on every idle tick. Throttling only the refresh would leave half
  the stated cost in place, so the gate covers the whole probe. It is released
  as soon as a pass finds real work, so an active catch-up still advances at
  full tick speed; the cost is up to one interval of latency before a new
  recovery is first noticed, which is immaterial for a progress indicator whose
  events retry through the normal claim path regardless.

6e also pages the dead-letter scan rather than issuing one unbounded select.
PostgREST caps a single response at 1000 rows, and a truncated dead-letter scan
would silently stop raising incidents for every integration past the cap — a
monitoring gap that reads exactly like a healthy deployment.

Fixed here as well (late review comment on the already-merged PR #242):
`safe_error_code` and `safe_error_detail` were each defined twice in
`services/email_ingestion.py`, with the old substring-based pair *after* the
classifier-backed pair. The later definitions won at import time, so
increment 2's structural classification was inert for every caller. The stale
pair is removed.

---

## Increment 7 — Recovery progress and UI correctness

**Branch:** `fix/recovery-progress-correctness` · **Scope:** `backend/**`,
`supabase/**`, `frontend/src/**` (+ iOS/Android if the same poll pattern is
mirrored) · **Size:** medium · **Priority: P2**

### Problems

**7a. Incomplete status vocabulary.** `refresh_waiting_calendar_recoveries`
(`20260802000005_calendar_recovery_worker.sql:104`) counts `synced` as
completed, `approved|syncing` as remaining, `sync_failed` as errored. But
`events.status` also allows `cancelled` and `rejected`
(`20260126000002_create_events.sql:22`). A tagged event the user rejects
mid-recovery counts as none of the three, so `remaining` drops and the recovery
finalizes with an undercounted `completed_count` — the UI renders
"Caught up — 3 of 5".

**7b. Spurious incident on every new connection.**
`email_sync_health.py:118` hardcodes `age = warning_seconds + 1` when
`last_success_at` is None but `last_started_at` is not. An integration whose
*first poll is still running* immediately opens a `stale_poll` warning and
resolves it seconds later. Once the notifier is configured (5d), every new user
connection generates an opened + resolved email pair.

**7c. The recovery card's poll chain dies on one blip.**
`ConnectionRecovery.svelte:83–96` self-reschedules with `setTimeout`, and
`fetchCalendarRecovery` never throws — it returns `{data: null, error}`. On a
single network error `recovery` becomes `null`, the chain stops, and the card
silently vanishes mid-catch-up until the component remounts.

**7d. Inconsistent with the established refresh pattern.** `CLAUDE.md` points at
`docs/specs/live-ui-updates.md` for cross-platform Realtime invalidation; this
new component uses a 5s `setTimeout` poll instead.

### Changes

- **7a** — count `cancelled`/`rejected` as terminal-not-errored so
  `completed_count + errored + withdrawn` reconciles against
  `discovered_count`. Add a `withdrawn_count` column, or fold them into
  `completed_count` with a comment; either is fine as long as the UI arithmetic
  closes. New migration.
- **7b** — treat "started but never succeeded" as within grace until
  `last_started_at` itself exceeds `email_health_warning_seconds`.
- **7c** — handle `error` in `loadRecovery`: keep the previous `recovery` value,
  do not null it, and reschedule with backoff so the card recovers on its own.
- **7d** — leave the poll in place for now, but record it in
  `live-ui-updates.md` as a known consumer to migrate, so it is not forgotten.
  Do not build a bespoke Realtime path here.

### Tests / DoD

Frontend unit test for the error path (previous state retained, poll continues).
Backend unit + integration tests for the status arithmetic and the grace period.
**Web screenshots required** (`./scripts/capture-all-screenshots.sh web`) —
7c changes rendered output. iOS/Android screenshots only if their equivalents
change.

---

## Increment 8 — Cleanups and defensive tightening

**Branch:** `chore/ingestion-cleanups` · **Scope:** `backend/**`,
`supabase/**` · **Size:** small · **Priority: P2**

**8a. Remove the dynamic-import hack.** `workers/email_ingestion.py:389` and
`:457`:

```python
__import__("selko.services.gmail", fromlist=["get_full_message"]).get_full_message(...)
```

This exists only so `patch("selko.services.gmail.get_full_message")` works. It
defeats static analysis and IDE navigation, and hides a real dependency. Import
normally and patch at the use site (`patch("selko.workers.email_ingestion.get_full_message")`),
or inject the provider adapter.

**8b. Replace the blanket grant.**
`20260801000001_polling_email_ingestion_v2.sql:425`:

```sql
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA public TO service_role;
```

follows eleven precise `REVOKE`s. It is a snapshot (future functions are not
covered) and it will silently re-grant anything later intended to be
restricted. Replace with eleven explicit `GRANT EXECUTE ON FUNCTION ... TO
service_role` statements in a new migration. Extend
`backend/tests/integration/test_integration_data_api_grants.py` to assert the
expected grant set rather than merely that calls succeed.

**8c. Disambiguate `get_credentials`.** Two functions with incompatible
signatures: `gmail.get_credentials(client, config, user_id=None)` and
`integrations.get_credentials(client, user_id, provider)`. The worker imports
the Gmail one. Passing the wrong one is a `TypeError` inside a background loop
that — before increment 3 — died silently. Rename the Gmail one to
`get_gmail_credentials` and update call sites.

**8d. Do not swallow secondary Outlook failures.** `_discover_outlook`
(`workers/email_ingestion.py:338–354`) collects failures and re-raises only
`failures[0]`; the generic `except Exception` at `:351` appends without logging.
Log every failure with its safe code before raising the first, and record the
count on the run row.

**8e. Record Graph failures during reconciliation.** `run_sync_once` calls
`record_graph_failure` on `GraphHttpError`; `run_reconciliation_once`
(`:128–138`) does not. Reconciliation is the pass most likely to hit Graph
throttling. Extract the shared failure-recording path.

**8f. Initialize `_outlook_access_token` in `__init__`.** It is created
implicitly in `_outlook_token` (`:227`); `_outlook_call` reads it (`:240`) and
would `AttributeError` if ever reached first. Set it to `None` in `__init__` and
raise a clear error if unset.

**8g. Retire `cli_backfill_email_ingestion_v2`.** The spec already flags it as
redundant now that the migration backfill plus the autoprovision trigger cover
the same ground. Remove it once production acceptance passes, and drop the
`docs/` reference with it.

---

## Increment 9 — Durability drills (the missing evidence)

**Branch:** `test/ingestion-durability-drills` · **Scope:** `backend/**`,
`scripts/**` · **Size:** medium · **Priority: P1**

### Problem

A system with a lease protocol, five retry state machines and independent
attachment work has been validated by 918 mock-heavy unit tests, a set of local
integration tests, and one **read-only** staging discovery pass. The core
promise — a worker dying mid-pass loses nothing and duplicates nothing — has
never been tested. From `polling-email-ingestion-v2.md` §"Not yet exercised":
the Outlook write path, mid-run termination, and the unsupported-attachment
fixture are all unexercised.

### Change

**9a. Scripted kill-mid-pass drill** — `scripts/drill-lease-recovery.sh`:
start the runtime against local Supabase with a faked slow provider, `SIGKILL`
mid-pass while a lease is held, start a second instance, and assert that the
lease is reclaimed after expiry, every discovered identity is acquired exactly
once, and `email_ingestion_items` has no duplicate `(integration_id,
provider_message_id)`.

**9b. Full-path integration test** — discovery → item → acquisition →
attachment → readiness gate → LLM claim, against local Supabase with a faked
provider. Must assert the gate blocks the LLM claim until attachments settle
(this is increment 4's regression test).

**9c. Outlook write-path fixture.** Staging has no Outlook integration, so the
first real write happens in production — the spec's own "largest residual risk".
Build a recorded-response fixture exercising the full Outlook acquisition path
including `itemAttachment` (unsupported) and `fileAttachment` (stored). Not a
substitute for a live run, but it converts an unknown into a known-shape test.

**9d. Unblock staging drills.** The staging Gmail refresh token has been dead
since 2026-02-12 (`invalid_grant`). Recovery requires an interactive browser
sign-in:

```bash
ENVIRONMENT=staging uv run python -m cli.cli_auth_gmail
```

**This is yours to run** — it cannot be worked around by copying credentials
(see "Environment separation" in `CLAUDE.md`). Steps 17–19 of
`polling-email-ingestion-v2.md` stay blocked until it happens.

---

## Increment 10 — Cutover verification

**Branch:** none (operational) · **Priority: after 1–4 merge**

Follow `polling-email-ingestion-v2.md` §"Production cutover runbook", with these
additions now that increments 1–5 exist:

1. Confirm `/health/ingestion` reports all tasks alive and
   `oldest_next_poll_seconds` inside the SLO, before and after deploy.
2. Confirm Sentry receives events from the new environment (trigger one
   synthetic error).
3. Run the increment-2 data repair against production and record the affected
   row count.
4. Watch `items_dead_letter` for 24h. Any non-zero value is a bug, not a
   backlog — the whole point of increment 2 is that nothing dead-letters on a
   first failure.
5. Complete spec step 19 acceptance: reconcile every included Outlook folder for
   30 days, confirm the discrepancy reaches zero from its measured 456, confirm
   Inbox and Archive read messages are included, confirm new mail arrives within
   the polling SLO over two intervals.

**Rollback note.** `email_fetch.py` was deleted in #234 before v2 ever ran in
production, so rollback is a `git revert` of five interdependent PRs including
four migrations. No v2 state is destroyed by reverting — tables, leases and
discovered identities persist, so a later re-cutover resumes rather than
restarts. Verify this claim on staging **before** the production cutover; it is
currently an assertion, not a tested property.

---

## Sequencing

```
1 (frontend, independent — land now)
2 ──┐
3 ──┼─→ 10 (cutover)      P0: required before production
4 ──┘
5 ──→ improves 10          P1: land close behind cutover
6, 9                       P1
7, 8                       P2
```

2, 3 and 4 touch different files and can proceed in parallel worktrees. 5
depends on 3 (`IngestionRuntime.status()`).

---

## Finding coverage

Every item from the review, mapped to where it is addressed.

| # | Finding | Severity | Increment |
|---|---|---|---|
| 1 | Gmail auth errors dead-letter mail permanently | 🔴 data loss | 2 |
| 2 | Transient DB error kills ingestion loops, silently | 🔴 outage | 3 |
| 3 | LLM can claim an email before attachment rows exist | 🟠 quality | 4 |
| 4 | `main` red; local gate structurally cannot catch it | 🟡 process | 1 |
| 5 | `__import__` hack in production code | smell | 8a |
| 6 | Two `get_credentials` with incompatible signatures | smell | 8c |
| 7 | Blanket `GRANT EXECUTE ON ALL FUNCTIONS` | smell | 8b |
| 8 | Recovery RPCs on every idle worker tick (~500k/day) | perf | 6d |
| 9 | Health evaluator N+1; resolves foreign incidents | perf / correctness | 6e |
| 10 | Spurious incident on every new connection | noise | 7b |
| 11 | Wasted `getProfile` call on every poll | perf | 6c |
| 12 | Recovery card poll chain dies on one error | UX | 7c |
| 13 | `refresh_waiting_calendar_recoveries` misses `cancelled`/`rejected` | correctness | 7a |
| 14 | `_discover_outlook` swallows secondary failures | observability | 8d |
| 15 | Reconciliation skips `record_graph_failure` | observability | 8e |
| 16 | `_outlook_access_token` created outside `__init__` | smell | 8f |
| 17 | Serial per-message metadata; 2 API calls per message | scalability | 6a |
| 18 | Weekly reconcile is O(all messages in 90 days) | scalability | 6b |
| 19 | No APM anywhere in the backend | evidence | 5b |
| 20 | `/health` green while ingestion is dead | evidence | 5a |
| 21 | State-machine counters recorded but never read | evidence | 5c |
| 22 | Notifier unconfigured; incidents reach nobody | evidence | 5d |
| 23 | No supervision regression test | test | 3 |
| 24 | No error-classification table test | test | 2 |
| 25 | No E2E through the durable path | test | 9b |
| 26 | No kill-mid-pass lease-recovery drill | test | 9a |
| 27 | Outlook write path never executed | test | 9c |
| 28 | Staging drills blocked by dead Gmail token | blocked | 9d |
| 29 | `cli_backfill_email_ingestion_v2` redundant | cleanup | 8g |
| 30 | Rollback path asserted but never tested | risk | 10 |
| 31 | Recovery card diverges from the Realtime pattern | consistency | 7d |

---

## What is deliberately **not** in scope

- **Re-architecting ingestion.** Leases, discovery-before-acquisition and the
  SQL readiness gate are correct and stay.
- **Restoring the legacy `email_fetch` poller.** It was removed in #234 and its
  stuck-timer failure mode is the reason this work exists.
- **Splitting ingestion into a separate Render service.** Measured headroom says
  in-process is fine, and ownership is enforced by leases, not topology. If
  increment 5 shows sustained memory or CPU pressure, revisit then — not now.
- **A metrics backend.** Increment 5c (structured log lines) plus Sentry is the
  right amount for a single-operator deployment. Prometheus/Grafana is YAGNI
  until there is someone to watch it.
