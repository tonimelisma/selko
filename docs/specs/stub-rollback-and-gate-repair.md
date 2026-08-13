# Stub Rollback and Gate Repair

**Status:** Planned; nothing implemented. **This is the next increment. Nothing
else may merge before G1–G4 are done.**

**Written:** 2026-08-12, after reviewing the R1–R5 batch (#305–#312).

**Supersedes:** the R2, R3, R4 and R5 increments of
[`review-queue-integrity.md`](review-queue-integrity.md), which are reset to
*unimplemented* by G1. The product outcomes those increments were meant to
deliver move to [`parallel-extraction-fenced-commit.md`](parallel-extraction-fenced-commit.md)
and [`calendar-identity-and-cancellation.md`](calendar-identity-and-cancellation.md).

---

## 1. Why this plan exists

[`foundation-integrity.md`](foundation-integrity.md) diagnosed the repository's
failure mode precisely:

> **Nothing in the development loop executes the system.**

It then built the fix: `./scripts/verify.sh backend`, schema contract tests, a
migration-order guard, a fail-closed staging verifier. That work is real and
merged (#287–#294).

The very next batch — R1–R5, eight PRs merged on 2026-08-11 — reproduced the
same failure mode with the gate in place. It did so in a new way that the gate
was not built to catch:

| What was merged | What is actually true |
|---|---|
| "feat: fenced per-user event resolution lanes (R2)" | `EventResolutionWorker` is instantiated by nothing. Zero call sites. The duplicate-event race the spec exists to fix is completely unfixed. |
| "feat: add phase-split stubs for fenced resolution (R2 worker)" | `extract_email_events()` returns `no_events` for every non-ICS email. `resolve_extracted_event()` returns `{"action": "created"}` unconditionally. Both are labelled `# Stub:` in the source. |
| "feat: identity-aware correlation tables and atomic save (R3)" | Two tables, both permanently empty. No `event_identity.py`. No Gmail/Outlook component parsing. Every caller passes `[]`. |
| "feat: automatic cancellation with fenced calendar work (R4)" | 50 lines of DDL. No classifier, no worker branch, no state machine. |
| "feat: one-time production repair script (R5)" | 75 lines that print their arguments. The source says `# For R5 DB contracts, this script is a placeholder`. |
| "fix: restore R4 status constraints and calendar claim (#312)" | Emergency repair of two production-breaking constraint truncations that R2 and R4 shipped through a green gate. |

The gate passed on all eight because the gate answers *"does this run?"*, and
code that nothing calls always runs fine.

**Both Tier 1 gates are red on `main` as of 2026-08-12** (§2.6, §2.7), and four
increments merged on top of that red.

### 1.1 The rule this plan adds

`CLAUDE.md` already says *"an increment is not implemented until its call sites
are wired."* That rule was not enforceable, so it was not enforced. G4 makes it
mechanical:

> A new module under `backend/selko/` must be reachable from `selko.api` or
> `selko.worker_app` by static import, or the build fails.

---

## 2. The defect register

Every item below is reproduced, with the exact file and the exact reason.

### D-R2.1 — The fenced resolution worker has no callers (critical)

`backend/selko/workers/event_resolution.py` defines `EventResolutionWorker`.
`grep -rn "EventResolutionWorker" backend frontend cli scripts` returns exactly
one hit: the definition. It is not in `pool.py`, not in `ingestion_runtime.py`,
not in `worker_app.py`.

Consequence: three tables (`email_event_resolutions`,
`email_event_resolution_items`, `event_resolution_lanes`), six RPCs, one
trigger and one worker module are dead weight. The production duplicate-event
race described in `review-queue-integrity.md` §2.2 is untouched;
`workers/email_process.py:65` still calls `save_extracted_events()` through
`asyncio.to_thread()` behind an 8-wide semaphore.

### D-R2.2 — The commit RPC does not commit anything (critical)

`commit_email_event_resolution_item()`
(`20260813000001_fenced_event_resolution.sql:203`) validates the fence, marks
the item row completed, and returns. It never inserts an event, never writes
`event_sources`, never version-checks a matched event. The spec required all
four (`review-queue-integrity.md` §6.3).

It is a fence around an empty field. `test_old_generation_cannot_commit` passes
`p_resolved_event_id=None` with `p_action='created'` and the RPC accepts it.

### D-R2.3 — `20260813000002_fix_claim_reclaim.sql` is unsafe SQL written for a test (critical)

The migration's own comment reads:

```sql
-- For test, we reclaim the active processing email itself with new generation
```

The reclaim branch it adds:

1. **Resurrects terminal work.** It selects any lane with an expired lease and
   then runs `UPDATE ... SET status = 'processing'` on the resolution row with
   no status filter. A `completed` or `failed` resolution is reset to
   `processing` and reprocessed. For a `completed` one that means re-creating
   its events — the exact duplicate bug the plan exists to prevent.
2. **Ignores `max_attempts` and `next_retry_at`.** A resolution that has
   exhausted its attempts loops forever.
3. **Starves every other user.** The reclaim branch runs first and `RETURN`s
   unconditionally when it finds anything. One wedged lane blocks all pending
   resolution for all users.
4. **Has no `ORDER BY`.** `LIMIT 1` over expired lanes is arbitrary.

This is live in `main`'s schema. It is inert only because D-R2.1 means nothing
calls it.

### D-R2.4 — R2 truncated `emails_processing_status_check` and broke `skipped` (high, repaired)

`20260813000001:5-7` replaced the constraint with a five-value set that dropped
`'skipped'`. `mark_email_status(..., "skipped")` — the terminal state for
sender-ignore and calendar-invite suppression — would have raised on every
call. Repaired by `20260814000003` the same night.

**The gate did not catch it**, because `mark_email_status` is Python issuing
SQL, not a `SECURITY DEFINER` function, so `test_schema_contract.py` never
enumerates it. G2 closes this.

### D-R2.5 — R4 truncated `events_status_check` and broke calendar sync (high, repaired)

`20260813000004:7-9` dropped `'syncing'`, `'synced'` and `'sync_failed'`.
`complete_event_sync()` (`services/events.py:1779`) writes `status = 'synced'`.
Every calendar sync completion would have raised. Repaired by
`20260814000001`.

Same blind spot as D-R2.4. Same fix: G2.

### D-R2.6 — R4's first `claim_calendar_work` dropped the lease entirely (high, repaired)

`20260813000004:20-38` defined `claim_calendar_work(p_worker_id, p_lease_seconds)`
that used **neither argument**. No `locked_by`, no `locked_until`, no
`status='syncing'`, no `sync_attempts < max_sync_attempts` cap, no active-
integration check. It also changed the return type from `SETOF public.events`
to a seven-column record, silently breaking every Python caller that reads any
other column. Repaired by `20260814000002`.

### D-R2.7 — The R2 concurrency test is not concurrent (high)

`backend/tests/integration/test_event_resolution_lanes.py:38-39` issues both
claims **sequentially on one connection inside one transaction**:

```python
r1 = await conn.fetchrow("SELECT * FROM public.claim_email_event_resolution('w1', 60)")
r2 = await conn.fetchrow("SELECT * FROM public.claim_email_event_resolution('w2', 60)")
```

`FOR UPDATE ... SKIP LOCKED` has no meaning within a single transaction. The
test proves the `WHERE` clause excludes a live lease — which a single `SELECT`
would prove — and proves nothing about concurrency. `asyncio` is imported and
never used. All three tests share this defect.

The spec listed thirteen required integration tests (§6.6). Three exist.

### D-R3.1 — Both R3 tables are permanently empty (high)

Nothing writes `email_calendar_components` (every caller passes `[]`) and
nothing writes or reads `event_identity_hints`. `event_identity.py` does not
exist. No Gmail `text/calendar` parsing, no Outlook `meetingMessageType`
handling, no matching ladder.

### D-R3.2 — The components write is destructive, not idempotent (medium)

`20260813000003:112`:

```sql
DELETE FROM public.email_calendar_components WHERE email_id = v_email_id;
```

unconditional, before inserting `p_calendar_components`. Once components exist,
any later re-save of that email — a reconciliation upsert, a delta re-fetch,
an Outlook folder move — silently deletes them, because the caller has no
components to re-supply. Latent today only because the table is empty.

### D-R4.1 — R4 delivered DDL and no behaviour (high)

`calendar_sync_action`, `calendar_work_generation` and `cancel_queued` exist as
columns and constraint values. Nothing sets them. No classifier for
`METHOD:CANCEL` or `meetingMessageType=meetingCancelled`, no worker branch on
action, no `cancel_queued` in History or the API schemas, no OAuth-recovery
handling. `calendars.cancel_calendar_event()` — the inline Google write that
§2.3 says must not be called from email processing — is still called from
`apply_pending_change()`.

### D-R5.1 — The repair script cannot repair (medium)

`scripts/repair_review_queue_integrity.py` validates argument shapes and
prints. `--apply` prints *"Apply would run one transaction per spec §9"* and
exits 0. It opens no database connection. Exiting 0 from `--apply` is worse
than exiting non-zero: an operator reading the exit code concludes the repair
ran.

### D-R1.1 — The disposition tombstone cancels itself (high)

`frontend/src/routes/app/+page.svelte`, `loadEvents()`. The snapshot is
filtered first:

```js
loadedEvents = loadedEvents.filter((e) => !dispIds.has(e.id));
```

and the tombstone is cleared later from that same filtered array:

```js
const stillPresent = new Set(loadedEvents.map((e) => e.id));
for (const id of dispositions.keys()) if (!stillPresent.has(id)) dispositions.delete(id);
```

`stillPresent` can never contain a dispositioned id, so **every disposition is
cleared on the next refresh regardless of what the server said.** The tombstone
exists to stop a card reappearing while its mutation is unconfirmed; it stops
nothing. Spec §5.2 required "retain the tombstone until a successful snapshot
confirms absence."

### D-R1.2 — Two overlapping refreshes wedge the queue permanently (high)

Same function. `refreshSequence` is incremented at the top of *every* call,
including calls that return early at the coalescing guard:

1. Call A starts, `seq=1`, sets `isRefreshingEvents = true`, awaits.
2. Call B arrives (a Realtime invalidation), `refreshSequence` becomes `2`,
   sees `isRefreshingEvents`, sets `refreshQueued = true`, returns.
3. Call A resolves, evaluates `if (seq !== refreshSequence) return;` — `1 !== 2`
   — and returns **without clearing `isRefreshingEvents` and without honouring
   `refreshQueued`**.

`isRefreshingEvents` is now permanently `true`. Every subsequent `loadEvents()`
returns at the guard. The Review page stops updating for the rest of the
session. Two invalidations during one in-flight refresh is the ordinary case,
not an edge case.

Spec §5.5 required tests for *"ignoring an out-of-order older fetch response"*
and *"one trailing fetch after invalidation during mutation"*. Neither was
written. They are exactly the two tests that fail this code.

### D-R1.3 — Announcement counts the wrong lane, in hardcoded English (medium)

```js
liveAnnouncement = `Accepted. ${events.length} remaining.`;
```

`events` holds both lanes, so "remaining" counts Changes cards too. The string
is hardcoded, as are `"Rejected."`, `"Refreshing"`, `"Retry"`, `"Accepted"` and
`"Rejected"` in `DispositionedCard.svelte`. Everything else on the page uses
`$_()`. R1's own acceptance criterion said *"add strings in all locales."*

### D-R1.4 — Every card is its own live region (medium)

`DispositionedCard.svelte` puts `role="status"` on a wrapper that contains the
whole card. A screen reader announces the entire card content on disposition,
in addition to the page-level `role="status"` region. Spec §5.4: *"Add one
visually hidden `role="status"` region… Do not announce animation and network
completion separately."*

### D-R1.5 — A `matchMedia` listener leaks per card (medium)

`DispositionedCard.svelte:20-24` registers a `change` listener in the component
body with no `$effect` cleanup. Listeners accumulate for every card ever
rendered and are never removed.

### D-R1.6 — Focus management was specified and not built (medium)

Spec §5.4 required capturing the next (or previous) card before a
keyboard-triggered removal and focusing it after outro, falling back to the
section heading and then the empty-state heading. The wrappers carry
`tabindex="-1"` and nothing else. No implementation, no test.

### D-R1.7 — `reconcileLaneOrder` ignores its `previousEvents` argument (low)

`review-queue-order.js:74`. The parameter is declared, documented, passed at
both call sites, and never read. Rules 3 and 5 of §5.1 are satisfied
incidentally by iteration order rather than deliberately.

### D-R1.8 — The FLIP polyfill makes motion tests vacuous (low)

`frontend/vitest.setup.js` stubs `Element.prototype.animate` to return a
resolved no-op globally. Any test that asserts animation behaviour asserts
nothing. Six of the fourteen tests §5.5 required were written; the eight
missing ones are the behavioural half.

### D-GATE.1 — `./scripts/verify.sh backend` exits 1 on `main` (critical)

Measured 2026-08-12 on `main` at `837f830e`:

```
FAILED backend/tests/integration/test_integration_email_ingestion_v2.py::test_only_one_worker_owns_an_integration_and_expired_leases_return
= 1 failed, 232 passed, 13 skipped, 20 deselected in 146.52s
EXIT=1
```

The same file passes 11/11 in isolation. The suite is **order-dependent**:
integration tests share the seeded development user and a live database with no
per-test rollback or tenancy, so earlier tests leave `email_sync_state` rows
that consume the bounded batch `claim_due_email_sync` returns.

This is the most dangerous defect in the register. A merge gate that goes red
for reasons unrelated to the change trains everybody to merge through red — and
then a real red, like D-R2.4, is indistinguishable from noise.

### D-GATE.2 — `./scripts/verify.sh frontend` exits 1 on `main` (high)

```
FAIL src/routes/app/history/__tests__/page.test.js > keeps observing a retried sync through the worker backoff window
Error: Test timed out in 5000ms.
Test Files 1 failed | 29 passed (30)
Errors 3 errors
```

Passes 22/22 in isolation — a fake-timer/`userEvent` test that exceeds the 5 s
default only under parallel load. Vitest additionally reports three unhandled
rejections from `layout.test.js` (`TypeError: supabase.channel is not a
function`) and warns *"This might cause false positive tests."* The live-updates
start path is throwing in tests and nothing fails.

### D-GATE.3 — Tier 1 depends on a live third-party OAuth token (high)

`scripts/verify.sh:42` runs, inside the merge gate:

```bash
uv run python -m cli.cli_seed_tokens --from staging --to development --provider gmail
```

`set -euo pipefail` means an expired staging Gmail token makes the merge gate
fail before a single test runs. The gate's availability is coupled to Google's
token lifetime and to staging being reachable.

### D-GATE.4 — F9 shipped a script; the 161 MB is still there (medium)

`foundation-integrity.md` records F9 (D6, *"161 MB / 13 008 tracked eval result
files"*) as merged in #291. `scripts/prune-eval-results.sh` exists. Measured
today: **14 228 tracked files, 161 MB**, `.git` at 138 MB, pack 106 MB. The
count grew. A merged script that was never run is not a resolved defect, and
recording it as one is how the register loses its meaning.

### D-DOC.1 — Five schema objects are undocumented (medium)

`docs/database-schema.md` was last modified 2026-08-02 and contains zero
mentions of `email_event_resolutions`, `email_event_resolution_items`,
`event_resolution_lanes`, `email_calendar_components`, `event_identity_hints`,
`cancel_queued` or `calendar_sync_action`. `docs/job-queue.md` likewise. The
Definition of Done requires reference docs to follow shipped schema.

### D-DOC.2 — `docs/specs/README.md` contradicts the repository (medium)

Its line 11 says review-queue-integrity is *"planned, nothing implemented"*
while R1–R5 are merged; line 18 says foundation-integrity is *"planned, nothing
implemented"* while its own header says F1–F7 and F9 are merged. Rewritten by
G6.

---

## 3. Locked decisions

1. **Roll the stubs out, do not finish them in place.** The R2/R3/R4 schema
   encodes an architecture this repository is choosing not to build
   (`parallel-extraction-fenced-commit.md` §2). Finishing it would cost more than
   deleting it and would leave the reclaim SQL of D-R2.3 in the lineage.
2. **Forward-only DROP migrations, guarded on emptiness.** These objects have
   never been deployed — production is at 80 migrations, these are 81–89 — and
   every table is empty. The drop migration asserts both facts and raises if
   either is false.
3. **Delete the tests that tested the stubs.** `test_event_resolution_lanes.py`
   goes with the objects it exercises. Deleting a test that asserts nothing is
   not a coverage loss.
4. **The repaired constraints stay.** `20260814000001/2/3` are correct and are
   not reverted; G1's drop migration must not disturb them.
5. **Gate repair precedes feature work.** G1–G4 land before any increment of
   `parallel-extraction-fenced-commit.md`. A green, deterministic gate is the
   precondition for trusting anything after it.
6. **No new abstraction is introduced by this plan.** G1–G6 remove code, fix
   defects in code that stays, and add gates. Nothing here designs a feature.

### 3.1 Alternatives considered and rejected

| Option | Decision | Reason |
|---|---|---|
| `git revert` the eight PRs | Rejected | #305 (R1) contains real, wanted work, and #312's constraint repairs must survive. Reverts would re-break the constraints. |
| Finish R2–R5 against the merged schema | Rejected | Adopts D-R2.3's reclaim semantics and the lane architecture we are replacing. |
| Keep the empty R3 tables for the future identity work | Rejected | The repository's own rule is no dormant tables. `calendar-identity-and-cancellation.md` creates them alongside the code that fills them, in one increment. |
| Mark the flaky gate tests `xfail` and move on | Rejected | Converts a known-broken gate into a silently-broken one. D-GATE.1 is the root cause; fix isolation. |
| Raise the frontend test timeout to 20 s | Rejected as the whole fix | Hides a fake-timer misuse. Fix the test, then raise the global timeout as defence in depth. |
| Leave the eval results and add them to `.gitignore` | Rejected | Untracking without pruning history leaves the 106 MB pack. G6 prunes tracked files; history rewrite is explicitly out of scope and recorded as accepted debt. |

---

## 4. Non-goals

- Designing the replacement resolution architecture. That is
  `parallel-extraction-fenced-commit.md`.
- Identity matching, cancellation, or calendar semantics. That is
  `calendar-identity-and-cancellation.md`.
- Any production deployment, migration push, or data repair.
- Rewriting git history to reclaim pack size.
- Changing iOS or Android.
- Adding new product behaviour of any kind.

---

## 5. Increments

Every increment: its own worktree and branch, its own PR, the late-review audit
in `CLAUDE.md` Definition of Done step 0 for source increments, and
`./scripts/merge-and-cleanup.sh <pr>` as the final step.

**G1 → G2 → G3 → G4 must land in that order.** G5 and G6 may land in parallel
with each other after G3.

---

### G1 — Remove the stub-ware

**Branch:** `fix/remove-resolution-stubs`
**Depends on:** nothing. Do this first.

#### G1.1 Delete source

Delete outright:

- `backend/selko/workers/event_resolution.py`
- `backend/tests/integration/test_event_resolution_lanes.py`
- `scripts/repair_review_queue_integrity.py`

From `backend/selko/services/events.py`, delete `extract_email_events()`
(line 220) and `resolve_extracted_event()` (line 252). Both are stubs with no
callers. Leave `save_extracted_events()` untouched — it is the live path and
`parallel-extraction-fenced-commit.md` P1 refactors it.

#### G1.2 Revert the acquisition RPC to three arguments

`supabase/migrations/20260815000001_drop_unbuilt_resolution_objects.sql`:

```sql
-- Preconditions. Refuse to run if any object was ever used.
DO $$
DECLARE v_count bigint;
BEGIN
    SELECT count(*) INTO v_count FROM public.email_event_resolutions;
    IF v_count > 0 THEN RAISE EXCEPTION
        'email_event_resolutions holds % rows; stop and hand-review before dropping', v_count; END IF;
    SELECT count(*) INTO v_count FROM public.email_calendar_components;
    IF v_count > 0 THEN RAISE EXCEPTION
        'email_calendar_components holds % rows; stop and hand-review', v_count; END IF;
    SELECT count(*) INTO v_count FROM public.event_identity_hints;
    IF v_count > 0 THEN RAISE EXCEPTION
        'event_identity_hints holds % rows; stop and hand-review', v_count; END IF;
    SELECT count(*) INTO v_count FROM public.emails WHERE processing_status = 'resolving';
    IF v_count > 0 THEN RAISE EXCEPTION
        '% emails are in resolving; drain before dropping', v_count; END IF;
END $$;

DROP FUNCTION IF EXISTS public.commit_email_event_resolution_item(uuid, uuid, integer, text, bigint, uuid, text);
DROP FUNCTION IF EXISTS public.fail_email_event_resolution(uuid, uuid, text, bigint, text, integer);
DROP FUNCTION IF EXISTS public.heartbeat_email_event_resolution(uuid, uuid, text, bigint, integer);
DROP FUNCTION IF EXISTS public.claim_email_event_resolution(text, integer);
DROP FUNCTION IF EXISTS public.enqueue_email_event_resolution(uuid, uuid, jsonb, text, text, text);

DROP TRIGGER IF EXISTS trg_ensure_event_resolution_lane ON public.users;
DROP FUNCTION IF EXISTS public.ensure_event_resolution_lane();

DROP TABLE IF EXISTS public.event_resolution_lanes;
DROP TABLE IF EXISTS public.email_event_resolution_items;
DROP TABLE IF EXISTS public.email_event_resolutions;
DROP TABLE IF EXISTS public.event_identity_hints;
DROP TABLE IF EXISTS public.email_calendar_components;

-- 'resolving' has no producer once the above are gone. Keep the R4 repair set
-- (20260814000003) minus that value.
ALTER TABLE public.emails DROP CONSTRAINT IF EXISTS emails_processing_status_check;
ALTER TABLE public.emails ADD CONSTRAINT emails_processing_status_check
  CHECK (processing_status IN ('pending','processing','processed','failed','skipped'));

-- Restore the three-argument acquisition RPC. Body is byte-identical to
-- 20260813000003 minus the component block; copy it, do not retype it.
DROP FUNCTION IF EXISTS public.save_email_with_attachment_descriptors(uuid, jsonb, jsonb, jsonb);
CREATE FUNCTION public.save_email_with_attachment_descriptors(
    p_user_id uuid, p_email jsonb, p_descriptors jsonb
) RETURNS uuid
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
  -- ... body copied verbatim from 20260813000003 lines 57-110, ending at the
  -- attachments INSERT, then RETURN v_email_id;
$$;
REVOKE ALL ON FUNCTION public.save_email_with_attachment_descriptors(uuid, jsonb, jsonb) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.save_email_with_attachment_descriptors(uuid, jsonb, jsonb) TO service_role;
```

> The `DROP FUNCTION` of the four-argument overload must precede the three-arg
> `CREATE`. Leaving both callable is the exact ambiguity #309's own commit
> message says it was fixing.

`events.calendar_sync_action`, `events.calendar_work_generation` and the
`cancel_queued` status value **stay**. They cost nothing, `20260814000002`'s
`claim_calendar_work` already reads them correctly, and
`calendar-identity-and-cancellation.md` C3 populates them.

#### G1.3 Update call sites and contracts

- `backend/selko/services/email_ingestion.py:387-405` —
  `save_email_with_attachment_descriptors()` drops the `calendar_components`
  parameter and the fourth bind. Restore the pre-#309 docstring.
- `backend/tests/integration/test_integration_email_ingestion_v2.py:393` — drop
  `"p_calendar_components"` from the RPC payload.
- `backend/tests/integration/test_schema_contract.py` — remove the six
  `*_email_event_resolution*` entries from `_function_arguments`, remove the
  trailing `[]` from the `save_email_with_attachment_descriptors` tuple, remove
  `"enqueue_email_event_resolution"` from the JSON-encoding set on line 303, and
  remove `"ensure_event_resolution_lane"` from `TRIGGER_ONLY_FUNCTIONS`.

#### G1.4 Prove it

```bash
./scripts/verify.sh backend
```

`test_every_security_definer_function_has_a_contract` fails loudly on any
missed entry — that is the point of it. Then:

```bash
grep -rn "event_resolution\|calendar_components\|identity_hints" backend cli scripts frontend/src
```

Must return nothing outside `docs/`.

**Acceptance:** the five tables and six RPCs are gone, the three-arg RPC is the
only callable overload, `verify.sh backend` is green *except* for D-GATE.1
which G3 fixes, and no source file references a removed object.

---

### G2 — Constraint-domain contracts (the class-killer)

**Branch:** `test/constraint-domain-contracts`
**Depends on:** G1.

D-R2.4 and D-R2.5 were the same defect twice in one night: a migration narrowed
a `CHECK (col IN (...))` domain and removed a value the Python code writes.
`test_schema_contract.py` cannot see it, because it enumerates
`SECURITY DEFINER` functions and the writers are Python.

Add `test_check_constraint_domains_are_pinned` to
`backend/tests/integration/test_schema_contract.py`.

**Mechanism.** Read the live domains, compare against a literal expected map.
Any migration that adds, removes or renames a permitted value fails until the
author updates the map — which is the moment they must ask whether every writer
still works.

```python
# Every enumerated text domain in public, pinned. Adding a value is a one-line
# edit here. REMOVING one requires you to prove no writer emits it: grep the
# literal across backend/, frontend/src/, ios/, android/ first.
EXPECTED_CHECK_DOMAINS: dict[tuple[str, str], set[str]] = {
    ("emails", "processing_status"): {
        "pending", "processing", "processed", "failed", "skipped",
    },
    ("events", "status"): {
        "pending_review", "pending_change", "approved", "rejected",
        "cancelled", "cancel_queued", "syncing", "synced", "sync_failed",
    },
    ("email_ingestion_items", "acquisition_status"): {...},
    ("attachments", "ingestion_status"): {...},
    ("integrations", "status"): {...},
    ("integration_recoveries", "status"): {...},
    ("email_sync_state", "run_kind"): {...},
    ("sender_rules", "action"): {...},
    # Complete this from the live database on first run; the test tells you
    # exactly which (table, column) pairs are missing.
}
```

Extract live domains with:

```sql
SELECT rel.relname AS table_name,
       att.attname AS column_name,
       pg_get_constraintdef(con.oid) AS definition
FROM pg_constraint con
JOIN pg_class rel ON rel.oid = con.conrelid
JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
JOIN unnest(con.conkey) AS k(attnum) ON true
JOIN pg_attribute att ON att.attrelid = rel.oid AND att.attnum = k.attnum
WHERE nsp.nspname = 'public'
  AND con.contype = 'c'
  AND pg_get_constraintdef(con.oid) LIKE '%ANY (ARRAY[%'
ORDER BY 1, 2
```

Parse the quoted literals out of the `ARRAY[...]` with
`re.findall(r"'([^']*)'::text", definition)`. Assert set equality per
`(table, column)`, and assert the discovered key set equals the expected key
set so a new enumerated column cannot appear unpinned.

**Write the test first and watch it fail.** Before writing
`EXPECTED_CHECK_DOMAINS`, check out `20260813000004` in a scratch database,
run the test with the correct (nine-value) `events.status` expectation, and
confirm it reports the three missing values. A domain test you never saw fail
is D2 again.

**Second assertion — writers are covered.** Add
`test_status_literals_in_python_are_permitted`: walk `backend/selko/**/*.py`
with `ast`, collect every string literal assigned to a key named
`processing_status`, `status`, `acquisition_status`, `ingestion_status` or
`sync_status` in a dict literal or a `.eq(...)`/`.update(...)` call, and assert
each is in the corresponding pinned domain. This is deliberately conservative:
it will not catch a status built by concatenation, and it does not need to —
D-R2.4 and D-R2.5 were both plain literals.

**Acceptance:** reverting `20260814000001` or `20260814000003` locally makes
the new test fail with the exact missing values named. Restore, and it passes.

---

### G3 — Make the integration suite order-independent

**Branch:** `test/integration-isolation`
**Depends on:** G2.

D-GATE.1 is the highest-leverage fix in this plan.

**Root cause.** `backend/tests/integration/` tests share the single seeded
development user (`TEST_USER_EMAIL`) and mutate live tables without rollback.
`test_only_one_worker_owns_an_integration_and_expired_leases_return` calls
`claim_due_email_sync`, which returns a bounded batch; when earlier tests have
left other integrations due, the fixture's own integration is not in the batch
and `next(...)` raises `StopIteration`.

**Fix, in this order:**

1. **Per-test tenancy for anything that claims.** Add to
   `backend/tests/integration/conftest.py`:

   ```python
   @pytest.fixture
   def isolated_user(admin_client):
       """A throwaway auth+public user, deleted on teardown.

       Any test that exercises a claim/lease RPC must use this instead of the
       shared development user. Claim RPCs return bounded batches over the
       whole table, so two tests sharing a user are two tests sharing a queue.
       """
   ```

   Model it on `test_schema_contract._seed_context`, which already does this
   correctly and is the reason the contract tests do not flake.

2. **Convert the claim/lease tests.** At minimum:
   `test_integration_email_ingestion_v2.py`,
   `test_integration_workers.py`, `test_integration_worker_pool_port.py`,
   `test_integration_calendar_recovery_worker.py`,
   `test_integration_ingestion_drill.py`. Each moves from the shared user to
   `isolated_user`, and each assertion that reads a claim batch filters to its
   own ids rather than assuming batch membership.

3. **Assert the property, not the batch.** Replace
   `next(row for row in first if row["integration_id"] == x)` with an explicit
   `[r for r in first if r["integration_id"] == x]` and an assertion on length,
   so the failure message says *"my integration was not claimed"* rather than
   `StopIteration`.

4. **Add a shuffle guard.** Add `pytest-randomly` to the backend dev
   dependencies and run the integration suite with a random seed in
   `verify.sh`. Record the seed in the output. Order-dependence then fails
   immediately and reproducibly instead of on the day it matters.

5. **Decouple the gate from Google (D-GATE.3).** In `verify.sh`,
   `prepare_local_integration_fixtures` must not fail the run when
   `cli_seed_tokens` fails:

   ```bash
   if ! uv run python -m cli.cli_seed_tokens --from staging --to development --provider gmail; then
     echo "WARN: no live Gmail token; real-Gmail tests will skip. Gate continues." >&2
     export SELKO_SKIP_REAL_GMAIL=1
   fi
   ```

   and the `TestGmailDevelopment` tests gain
   `@pytest.mark.skipif(os.getenv("SELKO_SKIP_REAL_GMAIL") == "1", ...)`.
   A skip is honest; a red gate for a third party's token expiry is not.
   **The skip must be counted and printed in the summary** so a permanently
   skipped suite is visible.

**Acceptance:**

```bash
for i in 1 2 3; do ./scripts/verify.sh backend || echo "RUN $i FAILED"; done
```

Three consecutive green runs with three different random seeds, and the summary
line names the seed and any skip count.

---

### G4 — Make unreachable code fail the build

**Branch:** `test/reachability-guard`
**Depends on:** G3.

D-R2.1 is the third time this repository has shipped a module nothing imports
(direct-pg Inc3–5 were the first two, per `foundation-integrity.md` §1). Make
it mechanical.

Add `backend/tests/test_reachability.py`:

```python
def test_every_worker_and_service_module_is_reachable():
    """A module under selko/workers or selko/services must be transitively
    importable from selko.api or selko.worker_app.

    R2 merged workers/event_resolution.py with zero call sites and a green
    gate. Mocks cannot notice a module nobody imports; an import graph can.
    """
```

Implementation: `ast.parse` every file under `backend/selko/`, build the
import graph over `selko.*` modules, compute the transitive closure from
`selko.api` and `selko.worker_app`, and assert that closure covers every module
under `selko/workers/` and `selko/services/`.

Maintain one explicit allowlist with a required justification:

```python
# Modules deliberately outside the runtime import graph. Each entry needs a
# reason and an owner. An empty allowlist is the goal.
DELIBERATELY_UNREACHABLE: dict[str, str] = {}
```

**Prove it fails first:** restore `workers/event_resolution.py` from
`git show 040729f4`, run the test, confirm it names the module, delete it again.

**Acceptance:** the test is green with an empty allowlist after G1.

---

### G5 — Fix the R1 frontend defects

**Branch:** `fix/review-queue-r1-defects`
**Depends on:** G3 (a deterministic frontend gate).

Fix D-R1.1 through D-R1.8, and D-GATE.2.

#### G5.1 Gate determinism first (D-GATE.2)

- `frontend/vitest.config.js`: set `testTimeout: 20000`. The 5 s default is
  below the observed 10.9 s file time for `history/__tests__/page.test.js`
  under parallel load.
- `src/routes/app/history/__tests__/page.test.js:180` — the test mixes
  `vi.useFakeTimers()` with `userEvent.setup({ advanceTimers })` and real
  `await`s. Replace the wall-clock waits with explicit
  `await vi.advanceTimersByTimeAsync(n)` so it is deterministic rather than
  merely slower.
- `src/routes/app/__tests__/layout.test.js` — the mock `supabase` has no
  `channel`, so `liveUpdates.start()` rejects and vitest reports it as an
  unhandled rejection. Give the mock `channel()`, `removeChannel()`,
  `realtime.setAuth()` and `auth.getSession()`, then assert `start()` resolves.
  Three unhandled rejections that vitest itself flags as a false-positive risk
  are not acceptable in a merge gate.

#### G5.2 The two high-severity logic bugs

**D-R1.1 — compare against the unfiltered snapshot.** Keep the server response
intact and derive both the render list and the tombstone decision from it:

```js
const serverIds = new Set(result.data.map((e) => e.id));   // BEFORE filtering
const visible   = result.data.filter((e) => !dispositions.has(e.id));
// ...render from `visible`...
for (const id of [...dispositions.keys()]) {
    if (!serverIds.has(id)) dispositions.delete(id);       // confirmed absent
}
```

**D-R1.2 — one exit path that always settles the flags.** Wrap the body in
`try/finally` and clear `isRefreshingEvents` in the `finally`, then drain
`refreshQueued` there too:

```js
try {
    const result = await fetchPendingEventsWithSources();
    if (seq !== refreshSequence) return;   // stale response: drop the DATA only
    // ...apply...
} finally {
    if (isFirst) isInitialEventsLoad = false;
    else isRefreshingEvents = false;
    if (refreshQueued) { refreshQueued = false; queueMicrotask(() => loadEvents()); }
}
```

Do not increment `refreshSequence` on a call that returns at the coalescing
guard — that call issues no request, so it must not invalidate the one in
flight. Move the increment below the guard.

#### G5.3 The rest

- **D-R1.3** — count the lane, not the page:
  `newEvents.length` for a New-lane disposition, `changeEvents.length` for a
  Changes-lane one. Move all six literals into `frontend/src/lib/i18n/` and use
  `$_('review.accepted', { values: { count } })`. Every locale file gets the key.
- **D-R1.4** — remove `role="status"` and `aria-label` from the three
  `DispositionedCard` branches. The wash, icon and text are visual affordances;
  the page-level region is the announcement.
- **D-R1.5** — move the `matchMedia` subscription into `$effect` and return the
  `removeEventListener` cleanup.
- **D-R1.6** — implement §5.4 focus handling, or delete the `tabindex="-1"`
  attributes and record focus management as explicitly deferred in this file.
  Do not leave the attribute implying behaviour that does not exist.
  **Recommended: implement it** — it is ~20 lines and the queue is
  keyboard-driven.
- **D-R1.7** — delete the `previousEvents` parameter from
  `reconcileLaneOrder()` and both call sites. It is unread.
- **D-R1.8** — keep the polyfill (jsdom needs it) and add the comment
  *"animation is stubbed here; motion assertions must use `outroend`, never
  `getAnimations()`"* directly above it.

#### G5.4 The eight missing tests

Write the tests from `review-queue-integrity.md` §5.5 that do not exist, and
write each one **against the unfixed code first**:

| Test | Must fail before the fix |
|---|---|
| ignores an out-of-order older fetch response | D-R1.2 |
| one trailing fetch after invalidation during mutation | D-R1.2 |
| background refresh retains content and shows no skeleton | — |
| failure restores card and rank with an alert | D-R1.1 |
| dispositioned card stays hidden while the server still returns it | D-R1.1 |
| distinct semantic accept/reject feedback | — |
| zero-duration under reduced motion | D-R1.5 adjacent |
| next / previous / empty focus targets | D-R1.6 |
| one concise live-region announcement, correct lane count | D-R1.3, D-R1.4 |

**Acceptance:** `./scripts/verify.sh frontend` green three times consecutively,
zero unhandled rejections, and `./scripts/capture-all-screenshots.sh web`
reviewed for desktop/mobile × light/dark × populated/feedback/empty.

---

### G6 — Correct the record and shrink the repository

**Branch:** direct to `main` (docs and artifacts only — no source).

1. **Run F9.** `./scripts/prune-eval-results.sh` for real. Target: one retained
   result per (operation, model, fixture) at the current prompt hash. Record
   before/after file count and `du -sh` in the commit message. Add the retention
   rule to `backend/tests/eval/README.md` and a `pre-commit` check that fails if
   tracked results exceed an agreed ceiling (suggest 2 000 files).
   History rewrite stays out of scope; note the residual pack size as accepted
   debt in `foundation-integrity.md` D6.
2. **Document the schema (D-DOC.1).** After G1 the only new object is
   `events.calendar_sync_action` / `calendar_work_generation` /
   `cancel_queued`. Add them to `docs/database-schema.md` with a note that they
   have no producer until `calendar-identity-and-cancellation.md` C3.
3. ~~**Rewrite `docs/specs/README.md` (D-DOC.2).**~~ **Done 2026-08-12.** The
   index is now an execution-order table of unfinished plans only. Seventeen
   finished or parked specs were deleted, their durable content folded into
   `docs/` reference files, `docs/backlog.md` and the Graph failure ledger
   first. The lifecycle rule now ends in *delete*, not *mark Implemented and
   keep* — that rule contradicted the directory's own definition of what
   belongs in it and had grown it to twenty files.
4. ~~**Delete `.agents/plans/…`.**~~ **Done 2026-08-12** — `.agents/` is
   gitignored, with the reason recorded in `.gitignore`: durable plans belong
   in `docs/specs/` where status is checked, and an untracked plan goes stale
   invisibly. That file still said *"no code was edited"* after its content
   shipped as #302/#304.
5. **Update `CLAUDE.md`** — add the reachability rule from G4 next to the
   existing call-sites rule, and add this file plus the two successor plans to
   the Reference Index.

---

### G7 — Close out the ingestion incident

**Done on 2026-08-12, except the two production checks below**, which need
production ledger access. The incident record was folded into
`docs/microsoft-graph-failure-ledger.md` (§"Incident — production ingestion
rollout, 2026-08-11/12") and the spec file deleted; the durable rule —
*rows leaving `pg_pool` as Python dicts must be JSON-safe at the repository
boundary, and never via `json.dumps(default=str)`* — is recorded there.

Remaining, tracked as open checkboxes in the ledger:

1. **Confirm the 10 `retry`/`unknown` items completed.** They were created
   03:10 UTC on 2026-08-12 with `next_retry_at` ~03:26, after #302 deployed.
   Nobody has verified since. If they did not complete, this is an open
   production defect and becomes the increment before
   `parallel-extraction-fenced-commit.md` P1.
2. **Decide the 12 historical `database_transient` dead letters.** Choose one,
   in writing, in the ledger: repair under a dry-run-first script (the pattern
   in P4), requeue after establishing the original failure cannot recur, or
   accept as permanently dead with the reason and the user impact.
   *"Reported separately" is not one of the three.* It is what has been said
   three times already.

<details>
<summary>Original G7 scope, superseded by the work above</summary>

**Branch:** direct to `main` for the docs move; a source branch only if step 3
turns out to need code.

`docs/specs/production-email-ingestion-discovery-20260812.md` is an **incident
record, not a plan**, and by this directory's own "What does not belong here"
rule it should not live in `docs/specs/`. It is also stale: its
"Next implementation increment" section describes a fix that shipped the same
day as #302 (`_normalize_pg_row` in `services/pg.py`) and #304, with the unit
and real-database regression tests it asked for. A reader today cannot tell
that the work is done.

1. **Fold it into `docs/microsoft-graph-failure-ledger.md`**, which `CLAUDE.md`
   already designates as the home for production Graph/ingestion failures.
   Carry the timeline, the root cause, and the fix commits. Delete the spec
   file. Do not leave a stub.
2. **Verify before writing "resolved."** Query the production ledger and
   confirm the 10 `retry`/`unknown` items reached `completed` or a justified
   `removed`. Record the counts and the date. If they did not, this is an open
   production defect and becomes the increment before
   `parallel-extraction-fenced-commit.md` P1 — say so, do not fold it away.
3. **Give the 12 historical `database_transient` dead letters an owner.**
   They predate the rollout and have been carried as "open" across three
   documents without anybody deciding. Choose one, in writing, in the ledger:
   - repair them under a dry-run-first script (the pattern in P4), or
   - requeue them after establishing that the original failure cannot recur, or
   - accept them as permanently dead, with the reason and the user impact.

   "Reported separately" is not one of the three. It is what has been said
   three times already.

</details>

---

## 6. The status rule this plan installs

`docs/specs/README.md` and every spec header must use exactly these four
statuses, and the evidence for each is mechanical:

| Status | Requires |
|---|---|
| **Planned** | Nothing merged. |
| **Partially implemented** | Some increments merged. The header **names each increment individually** as done or not. A batch is never described in aggregate. |
| **Implemented** | Every increment merged, **and** a test executes each new code path against a real database or a real browser, **and** the reachability guard (G4) covers every new module, **and** the durable docs are updated. |
| **Superseded** | Another spec, named and linked, now owns the outcome. |

An increment is **not** done because its PR merged. It is done when something
that would fail if it were absent, passes.

---

## 7. Verification

Per increment, before the PR:

```bash
./scripts/verify.sh backend     # G1-G4
./scripts/verify.sh frontend    # G5
```

After G4, this must hold and is the plan's exit condition:

```bash
for i in 1 2 3; do ./scripts/verify.sh backend && ./scripts/verify.sh frontend; done
```

Three consecutive green pairs, different random seeds, zero unhandled
rejections, skip counts printed and unchanged.

**No staging or production step belongs to this plan.** G1's drop migration
reaches staging with the first increment of `parallel-extraction-fenced-commit.md`,
under that plan's Tier 2 gate. Nothing here authorises a deployment.

---

## 8. Rollback

| Increment | Rollback |
|---|---|
| G1 | Revert the PR. The drop migration is forward-only; recreating the objects means reverting to `20260813000001/3/4` **plus** re-applying `20260814000001/2/3`, in that order. Since every dropped table was empty and undeployed, prefer forward correction. |
| G2 | Revert. Pure test addition. |
| G3 | Revert. Pure test/fixture change. If reverted, D-GATE.1 returns — record it as open, do not merge over it. |
| G4 | Revert. Pure test addition. |
| G5 | Revert the frontend PR; server state unaffected. |
| G6 | `git revert` restores pruned eval artifacts (they remain in history). |

---

## 9. Definition of done

- [ ] `workers/event_resolution.py`, `test_event_resolution_lanes.py`,
      `repair_review_queue_integrity.py` and the two `events.py` stubs are gone.
- [ ] Five tables, six RPCs and one trigger dropped by a precondition-guarded
      forward migration; `save_email_with_attachment_descriptors` has exactly
      one callable overload.
- [ ] `20260814000001/2/3` constraint repairs intact and pinned by G2.
- [ ] `EXPECTED_CHECK_DOMAINS` covers every enumerated text domain in `public`,
      and was **observed failing** against `20260813000004`.
- [ ] Integration suite green on three consecutive random-seed runs.
- [ ] Tier 1 no longer fails when the staging Gmail token is expired; skips are
      counted and printed.
- [ ] Reachability guard green with an empty allowlist, **observed failing**
      against a restored `event_resolution.py`.
- [ ] D-R1.1 … D-R1.8 fixed, each with a test that fails without the fix.
- [ ] Frontend gate green three times, zero unhandled rejections.
- [ ] Tracked eval results under the ceiling; before/after recorded.
- [ ] `docs/database-schema.md`, `docs/specs/README.md`, `CLAUDE.md` current.
- [ ] `review-queue-integrity.md` header states R2–R5 are unimplemented and
      superseded.
