# Parallel Extraction, Fenced Commit

**Status:** P1 and P2 implemented in this increment; P3–P4 remain planned.

**Written:** 2026-08-12.

**Replaces:** the R2 increment of
[`review-queue-integrity.md`](review-queue-integrity.md). It delivers R2's
outcome — *"two emails about the same event cannot race through independent
snapshots and create two events"* — and **upholds R2's decision 6 (parallel
extraction, serialized resolution) and decision 7 (every resolution write is
fenced)**. What it discards is R2's *mechanism*: three tables, six RPCs, a
second queue and a second worker.

**Depends on:** [`stub-rollback-and-gate-repair.md`](stub-rollback-and-gate-repair.md)
G1–G4, which are merged and were green three times consecutively before P1.

---

## 1. The outcome

1. Email extraction stays parallel — within a user and across users. No claim
   predicate changes, no throughput regression, no backlog regression.
2. Two emails whose events fall on the same user's same local day cannot both
   create an event from the same candidate snapshot. The loser recomputes
   against the winner's write and matches it.
3. A worker whose processing thread outlived its lease cannot write. Rejected
   by the database, not by a Python guard.
4. One email's events commit atomically — all, or none. No partial write.
5. There is exactly one code path that persists extracted events.

---

## 2. The design

### 2.1 What actually needs serializing

`services/events.py::save_extracted_events()` loops per extracted event and
does this:

```
find_matching_event()          # reads candidates, then an LLM compare
  └─ SELECT * FROM events WHERE user_id = ? AND start_datetime >= t0 AND < t1
create_event()  |  propose_event_update() + update    # writes
```

The race is a plain **read-modify-write**: two workers read the same candidate
set, both correctly conclude "no match", both insert. The window that must be
atomic is *candidate read → event write*, and its scope is exactly
`(user_id, local_day)` — `find_matching_event` (`events.py:686-697`) computes
`local_day`, `time_min` and `time_max` and queries that one-day band.

Nothing else needs serializing. Extraction does not. Two emails about different
days do not. Two users never do.

### 2.2 Why not a lock

`review-queue-integrity.md` §3.1 rejects holding a row or advisory lock, on the
grounds that it *"ties up a Supavisor session/transaction during unbounded
external I/O."* That is correct and still binding — the window contains an LLM
compare, and a second LLM call in `propose_event_update`. A lock held across
those is unacceptable.

But a lock is not the only way to make a read-modify-write atomic. **Optimistic
concurrency** inverts it: read freely, compute freely, commit *conditionally*.
The expensive part stays unlocked and parallel; only the commit is a
transaction, and it is short.

### 2.3 The fence: a candidate-set fingerprint

The commit RPC re-runs `find_matching_event`'s own query and compares a
fingerprint of what it finds against what the worker saw:

```sql
SELECT md5(string_agg(id::text || ':' || updated_at::text, ',' ORDER BY id))
  FROM public.events
 WHERE user_id = p_user_id
   AND start_datetime >= p_window_start
   AND start_datetime <  p_window_end
```

Match → apply. Mismatch → return `{"conflict": true}`, mutate nothing, and the
worker re-reads candidates and recomputes.

This needs **no new table, no trigger, and no timezone arithmetic in SQL** —
the window bounds are already computed in Python and are passed as arguments.
That is the whole reason to fingerprint the query rather than version a day
row: `local_day` depends on the user's timezone, and timezone logic in a
trigger is a defect waiting to happen.

Worked example, the exact production case from §2.4 of the parent spec:

| | Worker A (email 1) | Worker B (email 2) |
|---|---|---|
| reads candidates | fingerprint `f0`, no match | fingerprint `f0`, no match |
| LLM compare | — | — |
| commit | `f0` matches → **creates event E** | `f0` ≠ current → **conflict** |
| retry | — | re-reads: candidates now `[E]` → matches → **updates E, adds source** |

One event, two sources. Correct by construction, with both extractions having
run in parallel.

### 2.4 The second fence: the email lease

The fingerprint stops the duplicate race. It does not stop the **zombie
thread**: `workers/pool.py:480` wraps `asyncio.wait_for()` around
`asyncio.to_thread(...)`. `wait_for` cancels the awaiting coroutine; it cannot
stop the OS thread. The pool then fails or releases the email, a replacement
claims it, and the original thread can still write.

`review-queue-integrity.md` §2.2 identifies this correctly. The fix is one
column on the lease that already exists:

```sql
ALTER TABLE public.emails ADD COLUMN lock_generation bigint NOT NULL DEFAULT 0;
```

`claim_unprocessed_email` increments it. The commit RPC rejects any write whose
`(locked_by, lock_generation)` does not match the current row.

The two checks are orthogonal and both cheap:

- **lease fence** — "am I still the owner of *this email*?" Prevents the same
  email being committed twice.
- **fingerprint fence** — "did *this day* change under me?" Prevents the
  duplicate race.

### 2.5 Cost, stated plainly

| Cost | Size | Notes |
|---|---|---|
| A conflict costs one recompute | one `find_matching_event`, i.e. one compare LLM call | Only when two of *one user's* emails touch the *same local day* concurrently. Different days never conflict. |
| Bounded retry loop | cap 3, then normal email retry | Prevents livelock. Commits serialize on the row lock, so a retrying worker always eventually wins. |
| Fingerprint covers local events only | Google Calendar candidates are not fingerprinted | They are not written by concurrent extraction workers. The duplicate race is local-insert vs local-insert and is fully covered. Recorded as a known limit, not silently ignored. |

### 2.6 Alternatives considered and rejected

| Option | Decision | Reason |
|---|---|---|
| R2's staged resolution with per-user lanes | Rejected | Three tables, six RPCs, a second worker and item-level idempotence, to serialize a one-day read-modify-write. It also inherits `20260813000002`'s reclaim semantics. |
| Serialize the claim: one in-flight email per user | **Considered and rejected** | It was this plan's first draft. It works, and it is six lines of SQL — but it discards intra-user extraction parallelism and puts a single mailbox's cold-start backlog back at ~29 minutes. Optimistic concurrency costs little more and gives up nothing. |
| In-process `asyncio.Lock` keyed by user | Rejected | Does not survive a second API replica, `worker_app`, or a restart. §3.1 rejects it and is right. |
| Advisory lock across the LLM call | Rejected | Holds a Supavisor session across unbounded external I/O. §3.1 rejects it and is right. |
| Per-`(user, day)` version table bumped by trigger | Rejected | Needs the user's timezone inside a trigger to derive `local_day`. Fingerprinting the query the worker already ran needs neither a table nor a trigger. |
| Unique index on a semantic fingerprint | Rejected | §3.1: recurring rooms and same-day interviews collide, and a false merge is worse than a visible duplicate. Still true. |
| Parallel extraction + fingerprint CAS + lease fence | **Selected** | Upholds decisions 6 and 7, removes the race by construction, keeps all parallelism, adds one column and one RPC. |

---

## 3. Non-goals

- Identity matching, iCalendar UID handling, cancellation — those are
  [`calendar-identity-and-cancellation.md`](calendar-identity-and-cancellation.md)
  and depend on P1–P3 landing first.
- Making the extraction path `async`. `asyncio.to_thread()` stays; P1 fences
  its writes rather than eliminating the thread.
- Changing `claim_unprocessed_email`'s selection predicate at all.
- Changing acquisition, attachments, calendar sync, or Realtime.
- Web, iOS or Android changes.

---

## 4. Increments

### P1 — One atomic, lease-fenced commit per email

**Branch:** `fix/atomic-fenced-event-commit`
**Depends on:** G1–G4 green.

Today `save_extracted_events()` interleaves reads and several separate
PostgREST writes with no commit boundary — an email that fails partway leaves
some of its events written. P1 collapses the write half into one transaction
and adds the lease fence. It does **not** yet add the fingerprint; keeping the
two apart means each is independently provable.

#### P1.1 Migration

`supabase/migrations/20260816000001_atomic_fenced_event_commit.sql`:

1. `ALTER TABLE public.emails ADD COLUMN IF NOT EXISTS lock_generation bigint NOT NULL DEFAULT 0;`
2. `CREATE OR REPLACE FUNCTION public.claim_unprocessed_email(...)` — body
   byte-identical to `20260801000001` **except** the `UPDATE` also sets
   `lock_generation = lock_generation + 1`. Change nothing in the `WHERE`
   clause; this increment must not alter which emails are claimable.
3. The commit RPC:

```sql
CREATE OR REPLACE FUNCTION public.commit_email_extraction(
    p_email_id   uuid,
    p_worker_id  text,
    p_generation bigint,
    p_decisions  jsonb,   -- see contract below
    p_terminal   text     -- 'processed' | 'skipped' | 'failed'
) RETURNS jsonb
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
```

Contract, in order:

1. `SELECT ... FOR UPDATE` the email row.
2. If `locked_by <> p_worker_id` **or** `lock_generation <> p_generation`,
   return `{"fenced": true, "applied": 0}` and mutate nothing.
3. Apply each decision — `create`, `update`, `noop` — inserting `events` and
   `event_sources`. Generate new event ids in the RPC and return them, so a
   retry never invents a second id.
4. Set `processing_status = p_terminal`; clear `locked_by` and `locked_until`.
5. Return `{"fenced": false, "applied": n, "event_ids": [...]}`.

`p_decisions` element shape — pin this in the migration comment and in
`docs/database-schema.md`:

```json
{ "action": "create|update|noop",
  "event_id": "uuid|null",
  "fields":   { },
  "source":   { "email_id": "uuid", "extracted_data": { } } }
```

Standard rules: `SET search_path = public`, `REVOKE ALL ... FROM PUBLIC`,
`GRANT EXECUTE ... TO service_role`, and an entry in
`test_schema_contract.py::_function_arguments`.

#### P1.2 Python

- `save_extracted_events()` keeps its whole matching and proposal loop, but
  **accumulates decisions instead of writing them**, and ends with one
  `commit_email_extraction` call. Delete every direct write in the loop —
  `create_event()`'s write path and the inline update — after the last caller
  moves. Do not keep a fallback.
- `workers/email_process.py` passes `locked_by` and `lock_generation` from the
  claimed row down to the save.
- `fenced: true` logs at `warning` with the email id and both generations, then
  returns. **A fenced write is a normal outcome, not an error and not a retry.**

#### P1.3 Tests

| Test | Level | Asserts |
|---|---|---|
| `test_stale_generation_cannot_write` | integration | Claim, expire the lease, re-claim, then commit with the old generation. Zero events, `fenced: true`. |
| `test_zombie_thread_after_timeout_writes_nothing` | integration | Drive the real worker with an extraction that sleeps past the timeout; the reclaiming worker's events are the only ones. |
| `test_multi_event_email_commits_all_or_nothing` | integration | Force a failure on decision 2 of 3; assert zero events and zero sources. |
| `test_fenced_write_is_logged_not_raised` | unit | The worker keeps running. |

**Acceptance:** `grep -rn 'table("events").insert' backend/selko/services/events.py`
returns nothing on the extraction path. One writer.

---

### P2 — The candidate fingerprint fence

**Branch:** `fix/candidate-fingerprint-cas`
**Depends on:** P1.

#### P2.1 Python — capture the fingerprint where the candidates are read

`find_matching_event()` (`events.py:671`) already computes `time_min`,
`time_max` and the candidate list. Return them alongside the match:

```python
@dataclass(frozen=True)
class CandidateWindow:
    """The exact band find_matching_event queried, and what it saw.

    The commit RPC re-runs this query and compares. If another worker wrote an
    event into this band while we were in the LLM, our decision was computed
    against a stale snapshot and must be recomputed. This is the whole
    duplicate-prevention mechanism; see parallel-extraction-fenced-commit.md §2.3.
    """
    window_start: str          # time_min, ISO-8601
    window_end: str            # time_max, ISO-8601
    fingerprint: str           # md5 over (id, updated_at) of local candidates
```

Compute the fingerprint in Python **with the identical rule the RPC uses** —
`md5` over `id:updated_at` joined by `,`, ordered by `id`, with UTC timestamps
rendered as `YYYY-MM-DDTHH:MM:SS.USZ`. The canonical Python formatter lives in
`services/resolution_fingerprint.py`; the SQL formatter is pinned in the
migration and guarded by an integration test.

> Fingerprint local `events` rows only. Google Calendar candidates are excluded
> and this is deliberate (§2.5).

#### P2.2 Migration

Extend each `p_decisions` element with `window_start`, `window_end` and
`expected_fingerprint`. The RPC validates **every** decision's fingerprint
before applying **any** of them, and returns

```json
{"conflict": true, "conflicting_indexes": [1]}
```

on the first mismatch, mutating nothing. All-or-nothing keeps a multi-event
email consistent. A transaction-scoped advisory key for `(user, window)` makes
the check a real concurrent CAS without holding anything during extraction or
LLM I/O.

#### P2.3 Python — the retry loop

In `save_extracted_events()`:

```python
for attempt in range(MAX_RESOLUTION_ATTEMPTS):   # 3
    decisions = _resolve_all(...)                # re-reads candidates, re-compares
    result = commit_email_extraction(...)
    if result.get("fenced"):   return            # lost the email; someone else owns it
    if not result.get("conflict"):  break        # committed
    logger.info("resolution conflict, recomputing", extra={"attempt": attempt})
else:
    raise ResolutionConflictExhausted(email_id)  # falls into normal email retry
```

#### P2.4 Tests

| Test | Level | Must fail before the fix |
|---|---|---|
| `test_two_emails_same_day_produce_one_event` | integration, **truly concurrent** | Yes — produces two events without P2 |
| `test_two_emails_different_days_never_conflict` | integration, concurrent | — (guards against over-fencing) |
| `test_stale_fingerprint_returns_conflict_and_mutates_nothing` | integration | — |
| `test_conflict_recomputes_and_matches_the_winner` | integration | One event, two `event_sources` rows |
| `test_conflict_exhaustion_fails_the_email_into_retry` | unit | — |
| `test_python_and_sql_fingerprints_agree` | integration | Seed rows, compute both, assert equal. This is the drift guard. |

**The concurrency tests must be genuinely concurrent.** Two connections from
`pg_pool`, driven with `asyncio.gather`. Sequential `fetchrow`s on one
connection prove nothing — that mistake is
`stub-rollback-and-gate-repair.md` D-R2.7, and it is the single easiest way to
ship this increment as another green no-op.

Run `test_two_emails_same_day_produce_one_event` against the P1-only schema
first and watch it create two events.

**Acceptance:** the duplicate race is closed with `LLM_EXTRACTION_CONCURRENCY`
still at 8, proven by a concurrent real-database test that was observed
failing.

---

### P3 — Delete the dead paths and make conflicts observable

**Branch:** `chore/resolution-observability`
**Depends on:** P2.

**Status:** Implemented in this increment. P4 remains blocked until P1–P3
have been deployed and observed in production for seven days.

1. **Delete**, do not deprecate, anything P1/P2 made dead — the direct
   PostgREST writes in `events.py`, and any partial-write recovery that existed
   only because the write was not atomic. `CLAUDE.md`: *"an operation has
   exactly one implementation."*
2. **Content-free metrics** on the existing `/health` surface:
   - resolution conflicts per hour, and retries-per-email histogram — **if this
     climbs, the fingerprint band is too coarse and that is the signal to act**;
   - fenced writes since start;
   - conflict-exhaustion count (should be zero);
   - pending emails and oldest pending age.
3. **Guard test** beside `test_no_worker_module_retains_a_postgrest_fallback`:
   `test_event_writes_go_through_commit_rpc`, asserting no module under
   `selko/services` or `selko/workers` inserts into `events` outside the RPC.

---

### P4 — Repair the existing production duplicates

**Branch:** `fix/duplicate-event-repair`
**Depends on:** P1–P3 deployed and verified in production for seven days.

Replaces R5 / `scripts/repair_review_queue_integrity.py`, deleted by G1.1.

P2 stops new duplicates; it does not collapse the pairs already in production.
`review-queue-integrity.md` §9 specifies this script well and is **carried
forward unchanged** as the requirement. Restated obligations, because they are
the ones most likely to be skipped:

- Dry-run is the default. `--apply` requires `--environment production`,
  `--manifest <absolute path>`, `--confirm-user <uuid>`.
- The manifest is untracked; UUIDs and actions only.
- `--apply` **must open a database connection and must exit non-zero when it
  does not mutate.** D-R5.1 exited 0 while doing nothing, so an operator
  reading the exit code would conclude the repair ran.
- One transaction, targets locked in deterministic UUID order.
- Every §9 precondition checked; every failure printed.
- The ambiguous interview cancellation stays unapplied until the operator
  supplies an exact event id and time. *"One of these"* exits non-zero.
- A redacted artifact with reverse operations is written to a caller-supplied
  path.

Rehearse on staging with synthetic duplicates first. Nothing here authorises
the production apply; that needs separate explicit approval on the day.

---

## 5. Verification

Before each merge: `./scripts/verify.sh backend`.
After each merge: `./scripts/verify.sh staging`.

Staging drills — P2 changes commit semantics under real concurrency, and only
staging has the real pooler:

1. Seed one user with two emails describing the same appointment; run the
   worker 8-wide; assert one event and two sources.
2. Seed one user with eight emails across eight different days; assert zero
   conflicts and full parallelism.
3. Kill a worker mid-extraction; assert the reclaiming worker completes and the
   zombie's write is fenced.

Drill 3 cannot be proven locally in a way anyone should trust — it needs a real
process kill against the real session pooler.

### First seven production days

- zero duplicate events in this regression class;
- conflict rate low and, critically, **conflict-exhaustion count zero**;
- fenced-write count may be non-zero — that is the fence working;
- extraction throughput unchanged from the current eight-wide baseline. A
  throughput drop means the fence is serializing more than the same-day band,
  and is a defect in this plan, not a tuning problem.

---

## 6. Rollback

| Increment | Rollback |
|---|---|
| P1 | Do **not** roll back the RPC while workers run — in-flight commits would have no committer. Stop background processing, drain, then revert code and function together. `lock_generation` is additive; leave it. |
| P2 | Code and RPC revert together. Dropping the fingerprint arguments restores P1 behaviour; the duplicate race returns. |
| P3 | Revert. Observability only. |
| P4 | Use the artifact's reverse operations in one transaction, only if nothing has touched the survivor since. Prefer forward correction otherwise. |

---

## 7. Definition of done

- [ ] P1–P4 merged, locally verified, staging-verified, all three drills run.
- [ ] `LLM_EXTRACTION_CONCURRENCY` is still 8 and `claim_unprocessed_email`'s
      selection predicate is unchanged — extraction parallelism is intact
      within a user and across users.
- [ ] `test_two_emails_same_day_produce_one_event` uses two pool connections
      and `asyncio.gather`, and was **observed failing** before P2.
- [ ] `test_two_emails_different_days_never_conflict` passes, proving the fence
      is scoped to the day band and not to the user.
- [ ] Python and SQL fingerprints are computed from one shared rule, with a
      test asserting they agree.
- [ ] Every email-processing event write goes through `commit_email_extraction`;
      no second writer exists.
- [ ] A stale generation writes nothing and raises nothing.
- [ ] `docs/database-schema.md` and `docs/job-queue.md` describe
      `lock_generation`, `commit_email_extraction`, its decision shape, and the
      fingerprint rule.
- [ ] `review-queue-integrity.md` R2 marked **superseded by this file**, with
      decisions 6 and 7 recorded as upheld.
- [ ] No table, RPC or module added by this plan lacks a caller (G4 guard).
