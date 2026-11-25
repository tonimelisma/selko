# 02 — Data layer: every database function and every database call site

Part of the plan for `docs/specs/sqlite-single-process.md` (increment **Q6**,
"the SQLite data layer"). This section covers what `backend/selko/db/` must
contain and every line of today's code that reaches the database.
Schema DDL (`0001_initial.sql`), auth (`accounts`, `/auth/*`), the client
endpoints (Q1), `/live` (Q2) and the import (Q7) are other sections; they are
only referenced here.

**How this was measured (2026-11-25, read-only).** Live definitions from the
local database `supabase_db_selko` (`pg_get_functiondef`, `pg_get_triggerdef`,
`pg_proc.proacl`); callers from `grep -rnw` over `backend/selko`,
`backend/tests`, `frontend/src` and `scripts`; test names by parsing every
`backend/tests/**/test_*.py` with `ast` and listing the test functions whose
body names the function. Nothing was written to the database and no test was
run. Line numbers are those of the tree at this date.

**Counts confirmed:** 73 functions in `public` (61 `SECURITY DEFINER`, 12
invoker), 25 triggers on `public` tables **plus one on `auth.users`**
(`on_auth_user_created` → `handle_new_user`), so 26 trigger rows in total. The
overview's "25 triggers" counts `public` only. `.table(` call sites today:
**130** (129 literal + 1 dynamic in `email_sync_health.py:162`), not 141 — the
CLI and MCP removals on 2026-11-25 took the difference. `.rpc(` sites in
`backend/selko`: 19 (12 distinct functions over supabase-py); asyncpg call
sites: 37 (22 distinct SQL functions + 9 inline statements).

"EXECUTE" below is the **live** ACL (`pg_proc.proacl`), which is the net
result of every `GRANT`/`REVOKE` in the 120 migrations: `service` =
`postgres`+`service_role` only; `+auth` = also `authenticated`;
`anon+auth` = explicitly `anon` and `authenticated`; `PUBLIC` = `=X/postgres`
(anyone, including `anon`). All of it disappears with the port: there are no
database roles in SQLite, and the API is the only door (§4.3 of the overview).

---

## 0. Findings that change the plan

These came out of reading the 73 definitions against their callers. Each is
cited again where it applies.

1. **`ignore_sender_and_reject_pending` is broken in production whenever it
   finds a pending change.** Its loop calls `reject_event_change_proposal`
   with **14 arguments**; the function takes 13 (the `p_restore_status`
   parameter was removed and this call was not updated). Verified read-only:
   `to_regprocedure(…14 args…)` is null, the 13-arg form exists. It also runs
   `SECURITY INVOKER` from the web client as `authenticated`, which has **no
   EXECUTE** on `reject_event_change_proposal`
   (`has_function_privilege('authenticated', …) = false`). Either fault aborts
   the whole call, so "Ignore sender" fails for any sender who has a pending
   change proposal (the New-lane rejections roll back too). No test calls it.
   The port must decide the intended behaviour (§5.6) and add the missing test.
2. **Eight functions have no production caller** (dead or parked):
   `claim_calendar_work`, `heartbeat_calendar_work`,
   `unlock_expired_event_locks` (the Python function of the same name counts
   rows instead of calling it, `services/events.py:2752`),
   `reconcile_outlook_email_folders`, `claim_pending_photo`,
   `claim_next_scheduled_task`, `get_llm_usage_summary`,
   `get_user_quota_usage`. Three more are reachable only from operator
   scripts: `resolve_event_change_proposal`, `queue_event_cancellation`,
   `event_change_proposal_hash` (`scripts/repair_review_queue_integrity.py`).
   Python wrappers with no caller in `backend/selko` either:
   `emails.save_emails`, `emails.store_gmail_message_attachments`,
   `emails.skip_email_processing`, `emails.complete_email_processing`,
   `scheduled_tasks.complete/fail/cleanup_old_scheduled_tasks`,
   `events.get_events_new/approved/updates`, `events.get_event_with_sources`.
   §6 lists what is safe to drop.
3. **The `event_approved` wake-up has never been sent by the database.**
   `WorkListener.WORK_TYPES` (`services/pg.py:156`) and
   `workers/pool.py:261` wait on `event_approved`, but no trigger emits it:
   only `email_pending`, `item_pending`, `attachment_pending` exist
   (`notify_work_available` triggers). Calendar work is woken by the in-process
   `WorkerPool.nudge()` from the routes and by the safety poll. The port keeps
   that exactly; adding a real `event_approved` publish in `_enqueue_calendar_work`
   is a small latency improvement, listed as optional (§7.2).
4. **The startup lease reset runs after the workers start**
   (`api/app.py:130` starts `WorkerPool`, `:134–138` then unlock). With one
   process the reset must run first (§7.3).
5. **The commit fence compares a Postgres `text` sort with a Python byte
   sort.** `commit_email_extraction`'s hint fingerprint orders by
   `src.key` under the database collation; `resolution_fingerprint.py` sorts
   bytewise. Today this only works because the keys are hex, digits, `-`, `:`,
   `.`, `T`, `Z`. The port computes both sides with the same Python function,
   which removes the cross-language risk (§5.4).

---

## 1. Shape of `backend/selko/db/`

| Module | Holds | Lines (est.) |
|---|---|---|
| `db/connection.py` | `Database`: one writer `sqlite3.Connection` (`check_same_thread=False`, `isolation_level=None`) behind a `threading.Lock`; a pool of 4 read connections; PRAGMAs (`journal_mode=WAL`, `synchronous=NORMAL`, `foreign_keys=ON`, `busy_timeout=5000`, `cache_size=-32768`); the `Tx` context manager; UDF registration; `run(fn, *a)` = `asyncio.to_thread` for async callers | 260 |
| `db/codec.py` | the one codec: `uuid` ↔ lowercase `TEXT`; timestamps ↔ `YYYY-MM-DDTHH:MM:SS.ffffffZ` (fixed width, so text order = time order); `date`/`time` ISO; JSON columns (`json.dumps(sort_keys=False, separators)`/`loads`); booleans `0/1`; arrays as JSON arrays; `row_to_dict` that decodes by a per-table column-type map | 160 |
| `db/errors.py` | typed exceptions (§1.3) | 60 |
| `db/bus.py` | `EventBus` (after-commit publish), `WorkSignals` (replaces `WorkListener`, §7) | 120 |
| `db/emails.py` | email work state, save, reprocess, reads for services | 420 |
| `db/email_sync.py` | sync state/runs, discovery, ingestion items, folders | 430 |
| `db/attachments.py` | attachment claims and rows | 140 |
| `db/calendar_work.py` | calendar work items, routing helpers | 460 |
| `db/events.py` | `commit_email_extraction`, review status, event reads | 620 |
| `db/proposals.py` | proposal transitions, hash, invariant | 330 |
| `db/recovery.py` | reconnect recovery | 230 |
| `db/health.py` | `health_work_state`, health reads | 150 |
| `db/quotas.py` | quotas, LLM usage | 170 |
| `db/sender_rules.py` | sender rules, ignore, un-ignore reset | 200 |
| `db/mirror.py` | calendar mirror (`calendar_entries`, `calendar_mirror_state`, hints) | 200 |
| `db/integrations.py` | integrations, OAuth states, calendar settings, sync log | 300 |
| `db/ops.py` | `operational_incidents`, `graph_api_failures`, `llm_call_log` | 150 |
| `db/parked.py` | `photos`, `scheduled_tasks` (Google Photos is parked) | 160 |
| `db/startup.py` | `reset_leases_at_startup` (§7.3) | 80 |
| **Total** | | **≈ 4,640** |

### 1.1 The transaction

```python
with db.write() as tx:          # BEGIN IMMEDIATE on the writer connection
    tx.now                      # one timestamp for the whole transaction
    tx.execute(sql, params)     # plain sqlite3 execute on the writer
    tx.emit_live(user_id, resource, operation)   # buffered
    tx.emit_work(work_type)                      # buffered
# COMMIT; then bus.publish(...) for every buffered item. On exception: ROLLBACK,
# buffers dropped, exception re-raised.
```

- **`tx.now` replaces `now()`.** Postgres `now()` is the transaction start
  time and is constant inside a function; several functions rely on that
  (e.g. `claim_due_email_sync` returns `now() + interval` that equals the
  stored `lease_expires_at`). `tx.now = max(utc_now(), last_tx_now + 1µs)`,
  captured after `BEGIN IMMEDIATE` returns, so commit timestamps are strictly
  increasing. That keeps the `updated_at` fingerprint fence sound: two
  transactions can never write the same `updated_at` (with Postgres two
  concurrent transactions could, in principle, share a microsecond).
- **UDFs on the writer connection**, used by the permanent SQLite triggers
  (verified on Python 3.14 / SQLite 3.53.1 in this session: `trusted_schema`
  is 1, a UDF called from a permanent trigger works, a `WHEN NEW.x IS NOT OLD.x`
  guard suppresses the no-op update): `selko_now()` returns `tx.now` as text;
  `selko_emit_live(user_id, resource, operation)` and
  `selko_emit_work(work_type)` append to the current `Tx` buffers. A write
  from a connection without the UDFs (the `sqlite3` CLI) fails with "no such
  function", which is fail-closed: nothing can write behind the bus's back.
  The probe also showed that the buffer receives calls from a statement later
  rolled back, so `Tx` must clear its buffers on rollback (the design above
  does).
- **Reads** go through `db.read()` (a pooled read connection, WAL snapshot).
  A function that must read its own writes reads through `tx`.
- **Every public function in `db/` takes `user_id` first** when the row is
  user-owned (replaces RLS; the Q3 test enumerates `db/` and fails on a
  function without it, except the worker functions listed in
  `db/__init__.py:WORKER_SCOPED`, which are service-wide by design: every
  `claim_*`, `complete_*`, `fail_*`, `heartbeat_*`, `unlock_*`,
  `health_work_state`, `refresh_waiting_calendar_recoveries`).
- **Sync API.** All `db/` functions are synchronous. The services that call
  supabase-py today are synchronous and already run in threads
  (`workers/email_process.py:65`, `workers/calendar_sync.py:57,82`,
  `workers/ingestion_runtime.py:237,261`, `services/email_sync_health.py:98`).
  The asyncpg call sites are `async`; they become `await db.run(fn, …)`.

### 1.2 How each Postgres feature is replaced

| Postgres | In `db/` | Where it matters |
|---|---|---|
| `SELECT … FOR UPDATE [SKIP LOCKED] LIMIT 1` then `UPDATE … RETURNING` | one `UPDATE t SET … WHERE id = (SELECT id FROM t WHERE <predicate> ORDER BY … LIMIT 1) RETURNING *` inside `BEGIN IMMEDIATE` | all 11 `SKIP LOCKED` claims |
| `FOR UPDATE` on a row read before deciding | nothing: `BEGIN IMMEDIATE` already holds the only write lock; the read inside `tx` cannot change before commit | 30 functions |
| `pg_advisory_xact_lock` | removed: writers are serialized | `check_and_increment_quota`, `commit_email_extraction` |
| `now() + make_interval(secs => n)` / `interval '1 day'` / `(n || ' seconds')::interval` | `codec.ts(tx.now + timedelta(seconds=n))` bound as a parameter | 19 functions |
| `GET DIAGNOSTICS n = ROW_COUNT`, `RETURN FOUND` | `cursor.rowcount` | 10 + 8 functions |
| `RETURNING *` | SQLite `RETURNING *` (3.35+) | 17 |
| `ON CONFLICT (cols) [WHERE pred] DO UPDATE/NOTHING` | SQLite UPSERT, same syntax, partial-index target with the same `WHERE` | 7 |
| `jsonb` arguments (`p_decisions`, `p_items`, `p_email`, …) | Python `dict`/`list` arguments; no JSON SQL at all | 20 |
| `jsonb` columns read with `->`/`->>`/`?` | decoded in Python (`codec`) and tested with `in` | `ignore_sender…`, `reopen…` |
| `text[]` columns, `= ANY(arr)`, `unnest`, `ARRAY(SELECT …)` | JSON array columns; `IN (SELECT value FROM json_each(col))` in SQL, or Python sets | 5 columns, 6 functions |
| `auth.uid()` / `auth.role()` | explicit `user_id` parameter; the route takes it from the verified token | 5 functions |
| `RAISE EXCEPTION … USING ERRCODE` | typed exception (§1.3) | 21 |
| `pg_notify('selko_work', …)` | `tx.emit_work(...)` → `bus` after commit | 3 triggers |
| `realtime.send(…)` with the per-transaction GUC guard | `tx.emit_live(...)`, de-duplicated per `(user_id, resource)` per transaction | 11 triggers |
| deferred constraint trigger | pre-commit check in `Tx` over the event ids the transaction touched (§5.5) | 2 triggers |
| `extensions.digest(…, 'sha256')`, `md5()` | `hashlib` | 2 |
| `CURRENT_DATE` | `tx.now.date()` (UTC; Supabase's database time zone is UTC) | quotas |
| `EXECUTE format(… %I …)` dynamic SQL | a fixed column whitelist in Python | 2 |

### 1.3 Exceptions

`db/errors.py`:

| Exception | Postgres today | Raised by |
|---|---|---|
| `DbError(Exception)` | any `PostgrestAPIError` / asyncpg error | base |
| `NotOwned(DbError)` | `42501`, "event % is not owned by user %" | `_enqueue_calendar_work`, `set_event_review_status`, the 7 `… is not owned` raises |
| `InvalidArgument(DbError)` | `22023` and every plain `RAISE EXCEPTION` on bad input | 15 sites |
| `StaleProposal(DbError)` | `40001`, "proposal % changed before …" | `_lock_owned_pending_proposal`, `reopen…`, `resolve…` |
| `ProposalStateError(DbError)` | "proposal % is not an owned pending/applied/closed legacy proposal" | proposals |
| `InvariantViolation(DbError)` | `23514` | owner check, proposal invariant |
| `EmailActivelyLeased(DbError)` | `RAISE EXCEPTION 'email_actively_leased'` | `reprocess_email` |
| `NotFound(DbError)` | "email % not found", "Unknown email integration" | `commit_email_extraction`, `fail_email_processing`, `upsert_discovered_email_items` |
| `DbBusy(DbError)` | (none) `sqlite3.OperationalError: database is locked` after `busy_timeout` | `connection.py` |

`sqlite3.IntegrityError` (unique/CHECK/foreign key) is re-raised as
`UniqueViolation`/`CheckViolation(DbError)` by `Tx.execute`.

**`except` clauses that must change** (all other wrappers catch `Exception`
and keep working):

| File:line | Today | After |
|---|---|---|
| `api/routes/emails.py:59–60` | `except PostgrestAPIError` + substring `"email_actively_leased"` | `except EmailActivelyLeased` → 409; `except DbError` → 500 |
| `api/routes/emails.py:210`, `:305` | `except PostgrestAPIError` | `except DbError` |
| `services/integrations.py:156–157`, `:347–349`, `:660–661` | `except APIError` with `e.code == "204"` (PostgREST's "maybe_single found nothing") | gone: `db.integrations.get_*` returns `None` |
| `services/integrations.py:160, 209, 352, 378, 466, 499, 609, 664, 914` | `except PostgrestAPIError` | `except DbError` |
| `services/attachments.py:85, 285, 509` | `except PostgrestAPIError` | `except DbError` |
| `services/photos.py:59` | `except PostgrestAPIError` | `except DbError` |
| `services/emails.py:297` | `except PostgrestAPIError` | `except DbError` |
| `services/email_ingestion.py:16, 128` | `isinstance(exc, PostgrestAPIError)` → transport, retry | `isinstance(exc, DbBusy)` → transport, retry (a locked database is the one transient database failure left) |
| `services/event_processing.py:486` | substring `"PGRST116"` / `"0 rows"` from `.single()` | `db.emails.get_for_extraction` returns `None` → `LLMGatewayError("Email not found")` |
| `api/routes/events.py:338, 358, 398` | `except EventsError` → 400 | unchanged. A `DbError` from the proposal functions escapes as 500 today (supabase-py raises `APIError`, not `EventsError`) and still does; mapping `StaleProposal`/`ProposalStateError` to 409/400 is a behaviour change for the Q1 section, not this one |

---

## 2. The 73 functions and 26 triggers, by target module

Legend for each function: **Sig** signature → return · **Def** `SECURITY
DEFINER` · **Exec** live grants · **Callers** (file:line) · **PG** the
Postgres-specific features used · **Port** the SQLite/Python translation ·
**Size** estimated Python lines, difficulty S/M/L · **Tests** existing tests
that must keep passing (via the Python wrapper where the test calls the
wrapper). "PL" is the length of the plpgsql body today.

### 2.1 `db/emails.py` — email work state (7 functions)

| # | Function | Def | Exec | PL lines | Size | Diff |
|---|---|---|---|---|---|---|
| 1 | `_email_is_claimable(e emails) → boolean` (sql, STABLE) | no | PUBLIC | 11 | 15 | S |
| 2 | `claim_unprocessed_email(p_worker_id text, p_lock_duration_seconds int=300) → SETOF emails` | yes | service | 49 | 55 | M |
| 3 | `fail_email_processing(p_email_id uuid, p_worker_id text, p_generation bigint, p_error_code text, p_error_detail text, p_retry_base_seconds int, p_retry_max_seconds int) → jsonb` | yes | service | 45 | 45 | S |
| 4 | `reprocess_email(p_user_id uuid, p_email_id uuid) → SETOF emails` | yes | service, +auth | 41 | 40 | S |
| 5 | `unlock_expired_email_locks() → integer` | no | PUBLIC | 27 | 25 | S |
| 6 | `save_email_with_attachment_descriptors(p_user_id uuid, p_email jsonb, p_descriptors jsonb, p_calendar_components jsonb='[]') → uuid` | yes | service | 66 | 90 | M |
| 7 | (trigger fn) `parse_provider_labels() → trigger` | no | PUBLIC | 15 | 15 (SQL) | S |

**1 `_email_is_claimable`**
- Callers: `claim_unprocessed_email` only (inside the claim's `WHERE`). Not dead: internal.
- PG: row-type argument, `now()`, `NOT EXISTS` over `attachments`.
- Port: a SQL fragment constant `CLAIMABLE_EMAIL_PREDICATE` with `:now`
  (`processing_status='pending' AND attempts < max_attempts AND (locked_until IS NULL OR locked_until < :now) AND (next_retry_at IS NULL OR next_retry_at <= :now) AND NOT EXISTS (SELECT 1 FROM attachments a WHERE a.email_id = e.id AND a.ingestion_status IN ('pending','processing','retry'))`),
  shared by `claim_unprocessed_email` and `health_work_state.ready_emails`
  (today the health function duplicates it by hand, `fdefs` 1430–1439; one
  constant removes that drift risk).
- Tests: through `claim_unprocessed_email`.

**2 `claim_unprocessed_email`**
- Callers: `services/emails.py:511` (`claim_pending_email`, asyncpg) ←
  `workers/pool.py:363`. Tests reference it in
  `integration/test_integration_*` (below).
- PG: two `FOR UPDATE SKIP LOCKED LIMIT 1` selects, `make_interval`,
  `RETURNING *`, `lock_generation + 1`.
- Port, one `tx`: (a) `SELECT id, attempts, max_attempts FROM emails WHERE processing_status='processing' AND locked_until IS NOT NULL AND locked_until < :now ORDER BY locked_until LIMIT 1`;
  if found, `UPDATE` it to `pending` (clearing `processing_error`, `locked_by`,
  `locked_until`) when `attempts < max_attempts`, else to `failed` with
  `dead_letter_reason='lease_expired_at_limit'`, `dead_letter_at=:now`;
  (b) `UPDATE emails SET processing_status='processing', processing_error=NULL, locked_by=:w, locked_until=:until, attempts=attempts+1, lock_generation=lock_generation+1 WHERE id=(SELECT id FROM emails e WHERE <CLAIMABLE> ORDER BY date_sent IS NULL, date_sent, created_at LIMIT 1) RETURNING *`.
  `ASC NULLS LAST` becomes `date_sent IS NULL, date_sent` (SQLite sorts NULL
  first by default). The `emails_notify_pending` trigger fires on (a)'s
  `pending` update, as today.
- Behaviour kept: the stale-lease reclaim per call (CLAUDE.md "durable email
  work state"). Index needed in `0001`: `(processing_status, locked_until)`.
- Tests: `integration/test_integration_email_state_machine.py::test_expired_processing_email_is_reclaimed_without_restart`, `::test_expired_processing_email_at_attempt_limit_becomes_failed`, `::test_pending_email_cannot_equal_max_attempts`;
  `integration/test_integration_worker_pool_port.py::test_email_claim_complete_roundtrip`;
  `integration/test_integration_ingestion_drill.py::test_gate_blocks_llm_until_attachments_terminal`;
  `integration/test_integration_email_ingestion_v2.py::test_atomic_save_blocks_llm_claim_until_attachment_descriptors_settle`;
  `integration/test_integration_fenced_event_commit.py` (whole file, claims through it);
  `test_workers.py::test_worker_pool_claims_over_the_pool` (rewritten to assert `db.emails.claim_unprocessed_email` is reached).

**3 `fail_email_processing`**
- Callers: `services/emails.py:585` (asyncpg) ← `workers/pool.py:507`, `:518`.
- PG: `FOR UPDATE`, `IS DISTINCT FROM` fence, `power(2, …)`, `make_interval`,
  `left(…,100)`, `jsonb_build_object`; `RAISE EXCEPTION 'email % not found'`.
- Port: read `locked_by, lock_generation, attempts, max_attempts, processing_status`
  in `tx`; missing → `NotFound`; fence mismatch (`is not` comparisons in Python,
  so `None` vs value behaves like `IS DISTINCT FROM`) → return
  `{"fenced": True, "status": processing_status}`; else delay
  `min(max(retry_max,1), max(retry_base,1) * 2**min(max(attempts-1,0),5))`,
  write `pending` + `next_retry_at` or `failed` + dead-letter fields; return
  the same dict keys (`fenced, status, attempts, next_retry_at`). The caller's
  `json.loads(raw) if isinstance(raw, str)` branch (`emails.py:590`) becomes
  dead and is removed.
- Tests: `test_reliability.py::test_calls_fenced_rpc_with_worker_and_generation`, `::test_pending_outcome_is_returned`, `::test_terminal_outcome_is_returned`, `::test_fenced_outcome_is_returned_without_raising`;
  `integration/test_integration_workers.py::test_fail_email_processing_with_retry`;
  `integration/test_integration_email_state_machine.py::test_stale_email_worker_cannot_fail_new_generation`, `::test_failure_transition_is_atomic`, `::test_failure_backoff_grows_and_stays_capped`;
  `test_api_routes.py::test_health_ingestion_does_not_degrade_on_terminal_failures`.

**4 `reprocess_email`**
- Callers: `api/routes/emails.py:55` (user-scoped supabase client).
- PG: `auth.uid()`/`auth.role()` check, `FOR UPDATE`,
  `RAISE EXCEPTION 'email_actively_leased'` (matched by substring in
  `api/routes/emails.py:60`), `RETURN QUERY UPDATE … RETURNING`.
- Port: `reprocess_email(user_id, email_id) -> dict | None`; the ownership
  check becomes the `WHERE id=? AND user_id=?` (the route passes the token's
  user). Leased → `EmailActivelyLeased`. Returns the updated row or `None`
  (the route's "repeated clicks" branch, `emails.py:74`, keys on falsy).
- Tests: `integration/test_integration_email_state_machine.py::test_reprocess_resets_any_unleased_terminal_or_legacy_pending_row`, `::test_reprocess_refuses_an_actively_leased_row`; `test_api_routes.py` reprocess tests.

**5 `unlock_expired_email_locks`**
- Callers: `services/emails.py:652` ← `api/app.py:134` (startup).
- PG: `GET DIAGNOSTICS`, `now()`.
- Port: two `UPDATE`s in one `tx`, returns the first `rowcount`. Subsumed by
  `db/startup.reset_leases_at_startup` (§7.3), which calls it; kept by name
  because tests call it.
- Tests: `integration/test_integration_email_state_machine.py::test_unlock_expired_email_locks_retries_and_terminates_correctly`;
  `integration/test_integration_workers.py::test_email_lock_expiry_recovery`;
  `integration/test_integration_worker_pool_port.py::test_unlock_expired_helpers_run`;
  `test_ingestion_runtime.py::test_lifespan_runs_ingestion_in_process`, `::test_lifespan_recovers_stale_integration_recoveries_on_startup`.

**6 `save_email_with_attachment_descriptors`**
- Callers: `services/email_ingestion.py:434` (asyncpg,
  `EmailIngestionRepository.save_email_with_attachment_descriptors`) ←
  `workers/email_ingestion.py:825`. Mentioned in
  `scripts/backfill_calendar_components.py:20` (prose only).
- PG: dynamic `EXECUTE format()` over the payload's keys filtered to a
  17-column whitelist, `jsonb_populate_record` (type coercion of
  `to_emails`/`provider_labels`/`provider_folder_ids` `text[]` and
  `date_sent timestamptz`), `ON CONFLICT (user_id, email_provider, provider_message_id) DO UPDATE` of exactly the supplied columns,
  `jsonb_array_elements … WITH ORDINALITY`, partial-index
  `ON CONFLICT (email_id, provider_attachment_id) WHERE … DO NOTHING`.
- Port: `EMAIL_SAVE_COLUMNS` tuple (the same 17 names); build
  `INSERT INTO emails (cols) VALUES (?…) ON CONFLICT(user_id,email_provider,provider_message_id) DO UPDATE SET c=excluded.c … RETURNING id`
  from the keys present (identifiers come only from the whitelist, never from
  input); values through `codec` (lists → JSON, timestamps → canonical text);
  a fresh `id` generated in Python for the insert path. Attachments: one
  `executemany` with `ON CONFLICT(email_id, provider_attachment_id) WHERE provider_attachment_id IS NOT NULL AND provider_attachment_id <> '' DO NOTHING`
  (SQLite requires the conflict-target `WHERE` to match the partial index).
  Components: only when the list is non-empty, `DELETE` then insert with
  `enumerate()` as `component_index`. All one `tx`, so the readiness gate
  holds as today. Fires `parse_provider_labels_trigger`,
  `emails_notify_pending` and `trg_emails_broadcast_upd` as SQLite triggers.
- Hard part: `jsonb_populate_record` silently coerces strings; Python must
  coerce the same fields explicitly or a `date_sent` with an offset stored
  un-normalised breaks text ordering (`ORDER BY date_sent` in the claim). The
  codec normalises every timestamp to UTC `…Z` on write.
- Tests: `test_email_ingestion_v2.py::test_claim_item_normalizes_asyncpg_uuid_ids`, `::test_acquire_item_does_not_query_integrations_per_message`;
  `test_calendar_components.py::test_c1_migration_secures_components_and_preserves_on_empty_resave` (rewritten: it greps a migration);
  `integration/test_integration_calendar_components.py::test_calendar_components_survive_empty_resave`;
  `integration/test_integration_ingestion_drill.py::test_acquire_creates_email_and_descriptors_atomically`, `::test_outlook_acquisition_handles_file_vs_item_attachment`;
  `integration/test_integration_email_ingestion_v2.py::test_atomic_save_blocks_llm_claim_until_attachment_descriptors_settle`, `::test_re_acquired_email_keeps_existing_attachment_rows_unreset`;
  `integration/test_integration_worker_pool_port.py::test_save_email_with_attachment_descriptors_returns_uuid`, `::test_claim_item_save_roundtrip_is_json_safe`.

**7 `parse_provider_labels`** (trigger `emails.parse_provider_labels_trigger`, BEFORE INSERT OR UPDATE OF provider_labels)
- Callers: the trigger only.
- PG: `BEFORE` trigger assigning `NEW.is_*` from `'X' = ANY(NEW.provider_labels)`.
- Port: SQLite `BEFORE` triggers cannot assign `NEW`. Use
  `AFTER INSERT ON emails` and `AFTER UPDATE OF provider_labels ON emails`
  triggers running `UPDATE emails SET is_spam = EXISTS(SELECT 1 FROM json_each(NEW.provider_labels) WHERE value='SPAM'), … WHERE id = NEW.id`
  for the ten flags (`SPAM, TRASH, CATEGORY_PROMOTIONS, CATEGORY_SOCIAL, CATEGORY_UPDATES, CATEGORY_FORUMS, CATEGORY_PERSONAL→is_primary, IMPORTANT, STARRED, UNREAD`).
  `recursive_triggers` stays off (default), so the inner `UPDATE` does not
  re-fire. Verified pattern in this session's probe. The `is_*` columns have
  no other writer.
- Tests: none name it. Add `test_db_emails.py::test_labels_set_flags_on_insert_and_update`.

### 2.2 `db/email_sync.py` — provider discovery and ingestion items (12 functions)

| # | Function | Def | Exec | PL | Size | Diff |
|---|---|---|---|---|---|---|
| 8 | `claim_due_email_sync(p_worker_id text, p_lease_seconds int) → TABLE(integration_id uuid, user_id uuid, provider text, run_id uuid, run_kind text, lease_generation bigint, lease_expires_at timestamptz)` | yes | service | 28 | 45 | M |
| 9 | `claim_due_email_reconciliation(p_worker_id text, p_lease_seconds int) → TABLE(same 7)` | yes | service | 32 | 45 | M |
| 10 | `heartbeat_email_sync(p_integration_id uuid, p_worker_id text, p_generation bigint, p_lease_seconds int) → boolean` | yes | service | 7 | 12 | S |
| 11 | `complete_email_sync(p_integration_id uuid, p_run_id uuid, p_worker_id text, p_generation bigint, p_poll_interval_seconds int=300, p_reconciled bool=false) → boolean` | yes | service | 17 | 25 | S |
| 12 | `fail_email_sync(p_integration_id uuid, p_run_id uuid, p_worker_id text, p_generation bigint, p_error_code text, p_error_detail text=NULL, p_retry_base_seconds int=60, p_retry_max_seconds int=1800, p_auth_failure bool=false) → boolean` | yes | service | 19 | 30 | S |
| 13 | `upsert_discovered_email_items(p_integration_id uuid, p_run_id uuid, p_items jsonb, p_cursor text=NULL, p_folder_id uuid=NULL) → TABLE(inserted_count int, existing_count int, provider_ids_seen int)` | yes | service | 34 | 60 | M |
| 14 | `claim_email_ingestion_item(p_worker_id text, p_lease_seconds int=900) → SETOF email_ingestion_items` | yes | service | 13 | 20 | S |
| 15 | `complete_email_ingestion_item(p_item_id uuid, p_worker_id text, p_email_id uuid) → boolean` | yes | service | 7 | 10 | S |
| 16 | `fail_email_ingestion_item(p_item_id uuid, p_worker_id text, p_error_code text, p_retry_base_seconds int=60, p_retry_max_seconds int=1800, p_terminal bool=false) → boolean` | yes | service | 13 | 20 | S |
| 17 | `request_email_sync_now(p_integration_id uuid) → boolean` | yes | service, +auth | 17 | 18 | S |
| 18 | (trigger fn) `ensure_email_sync_state() → trigger` | yes | service | 31 | 30 | S |
| 19 | `reconcile_outlook_email_folders(p_integration_id uuid, p_forbidden_folder_ids text[]='{}') → integer` | yes | service | 15 | — | dead |

**8 `claim_due_email_sync`**
- Callers: `services/email_ingestion.py:282` (asyncpg, `claim_due_sync`).
  Prose: `workers/ingestion_runtime.py:9`, `scripts/drill-staging-workers.sh:88`.
- PG: `JOIN integrations`, `FOR UPDATE OF s SKIP LOCKED`, `NULLS FIRST`,
  abandon running runs, `INSERT … RETURNING id`, `make_interval`.
- Port, one `tx`: select the due state
  (`i.status='active' AND s.next_poll_at <= :now AND (s.lease_expires_at IS NULL OR s.lease_expires_at <= :now) ORDER BY s.next_poll_at, s.last_success_at IS NOT NULL, s.last_success_at LIMIT 1`);
  `UPDATE email_sync_runs SET status='abandoned', completed_at=:now WHERE integration_id=? AND status='running'`
  (must precede the insert: `email_sync_runs_one_running_per_integration` is a
  partial unique index, checked per statement in SQLite as in Postgres);
  insert the run with a Python `uuid4()`; update the state lease; return a
  dict with the seven keys (`SyncClaim(**row)` in `email_ingestion.py:288`
  takes it unchanged). `lease_expires_at` returned and stored are the same
  `tx.now + lease` value.
- Tests: `test_email_ingestion_v2.py::test_expired_sync_claim_uses_durable_rpc_and_returns_run`;
  `test_egress.py::test_snapshot_attributes_bytes_by_destination_and_operation`, `::test_fixed_idle_rate_stays_under_ceiling` (egress templates name the RPC; rewritten when the `supabase` egress destination goes away);
  `integration/test_integration_graph_ledger.py::test_graph_failure_is_recorded_with_redacted_operation_and_run`;
  `integration/test_integration_email_state_machine.py::test_next_sync_claim_abandons_previous_expired_run`, `::test_stale_sync_generation_cannot_complete_new_run`, `::test_one_running_run_per_integration_is_a_database_invariant`.

**9 `claim_due_email_reconciliation`**
- Callers: `services/email_ingestion.py:292` (`claim_due_reconciliation`).
- PG: as 8, plus `interval '1 day'`/`'7 days'`, `NULLS FIRST`.
- Port: as 8 with predicate `(last_reconciled_at IS NULL OR last_reconciled_at <= :now-1d) AND next_poll_at > :now`, order `last_reconciled_at IS NOT NULL, last_reconciled_at, next_poll_at`; kind `weekly_reconcile` when `last_reconciled_at <= :now-7d` else `daily_reconcile`.
- Tests: `test_ingestion_runtime.py` (calls `claim_due_reconciliation` on a fake); no integration test names it — add `test_db_email_sync.py::test_reconciliation_claim_kinds`.

**10 `heartbeat_email_sync`**
- Callers: `services/email_ingestion.py:302` (`heartbeat_sync`, `require_heartbeat` raises `LeaseLostError`).
- PG: `make_interval`, `RETURN FOUND`.
- Port: one fenced `UPDATE … WHERE integration_id=? AND lease_owner=? AND lease_generation=? AND lease_expires_at > :now`; `rowcount == 1`.
- Tests: `integration/test_integration_email_ingestion_v2.py::test_heartbeat_and_completion_require_matching_ownership`.

**11 `complete_email_sync`**
- Callers: `services/email_ingestion.py:316` (`complete_sync`).
- PG: `GET DIAGNOSTICS`, `make_interval`.
- Port: fenced state `UPDATE`; on `rowcount == 0` return `False`; else mark the run `completed` (fenced on `lease_generation`).
- Tests: `integration/test_integration_email_ingestion_v2.py::test_heartbeat_and_completion_require_matching_ownership`; `integration/test_integration_email_state_machine.py::test_stale_sync_generation_cannot_complete_new_run`.

**12 `fail_email_sync`**
- Callers: `services/email_ingestion.py:328` (`fail_sync`).
- PG: `FOR UPDATE`, `power`, `make_interval`, `left()`.
- Port: read `consecutive_failures` fenced; delay
  `min(retry_max, max(retry_base,1) * 2**min(failures-1,5))`; run → `failed`
  with truncated codes; state lease cleared, backoff set; when
  `p_auth_failure`, `UPDATE integrations SET status='expired'` (fires the
  `trg_integrations_broadcast_upd` live hint; `ensure_email_sync_state` returns
  early on a non-active status).
- Tests: `test_email_ingestion_v2.py::test_missing_credentials_are_classified_as_auth_and_expire_the_integration`, `::test_gmail_401_during_discovery_expires_the_integration`; `integration/test_integration_email_ingestion_v2.py::test_failure_backoff_grows_and_stays_capped`.

**13 `upsert_discovered_email_items`**
- Callers: `services/email_ingestion.py:354` (`upsert_discovered`).
- PG: `jsonb_array_elements`, `ARRAY(SELECT jsonb_array_elements_text …)`,
  `ON CONFLICT (integration_id, provider_message_id) DO UPDATE` with
  `ARRAY(SELECT DISTINCT unnest(old || new))`, run counters with
  table-qualified columns, cursor write to `integrations` or `email_folders`.
- Port: Python list of items; `existing = SELECT count(*) … WHERE integration_id=? AND provider_message_id IN (SELECT value FROM json_each(?))`;
  per item an UPSERT whose `DO UPDATE` folder union is computed in SQL with
  `(SELECT json_group_array(DISTINCT value) FROM (SELECT value FROM json_each(email_ingestion_items.provider_folder_ids) UNION SELECT value FROM json_each(excluded.provider_folder_ids)))`
  — or, simpler and testable, read the existing rows for the page first and
  compute the union with `dict.fromkeys` in Python (the page is ≤
  `MAX_PAGE_ITEMS`). The Postgres union's order is unspecified; tests compare
  sets. `acquisition_status` rule kept: `retry`/`pending` → `pending`,
  otherwise unchanged; `change_kind` kept when `completed`. Fires
  `items_notify_pending` per row → one `item_pending` work signal per commit
  (the bus de-duplicates; Postgres `pg_notify` also collapses identical
  payloads within a transaction — `integration/test_integration_work_listener.py::test_batch_collapse_one_notification_per_transaction` pins it).
  `ensure_attachment_descriptors`-style empty `provider_message_id` filter kept.
  Unknown integration → `NotFound("Unknown email integration")`.
- Tests: `integration/test_integration_email_ingestion_v2.py::test_discovery_page_write_records_run_counters`, `::test_identity_upsert_unions_folders_and_protects_completed_items`, `::test_cursor_advances_only_when_discovery_supplies_one`.

**14 `claim_email_ingestion_item`**
- Callers: `services/email_ingestion.py:396` (`claim_item`).
- PG: `FOR UPDATE SKIP LOCKED LIMIT 1`, `make_interval`, `RETURNING *`.
- Port: single `UPDATE … WHERE id=(SELECT … ORDER BY created_at LIMIT 1) RETURNING *`. `_normalize_pg_row` (`email_ingestion.py:404`) is no longer needed: `codec` already returns `str` ids and ISO strings.
- Tests: `test_email_ingestion_v2.py::test_claim_never_precedes_acquire`; `integration/test_integration_ingestion_stall_signal.py::test_a_row_serving_its_retry_backoff_is_not_stalled`; `integration/test_integration_worker_pool_port.py::test_claim_item_save_roundtrip_is_json_safe`; `test_acquisition_executor_bound.py`.

**15 `complete_email_ingestion_item`** — Callers: `services/email_ingestion.py:410` (`complete_item`). PG: `RETURN FOUND`. Port: one fenced `UPDATE`, `rowcount`. Tests: `test_email_ingestion_v2.py` (complete_item), `integration/test_integration_worker_pool_port.py` (`complete_item`).

**16 `fail_email_ingestion_item`** — Callers: `services/email_ingestion.py:460` (`fail_item`); prose `config.py:140`. PG: `FOR UPDATE`, `power`, `make_interval`, `left`, `RETURN FOUND`. Port: fenced read, delay in Python, one `UPDATE` to `retry` or `dead_letter`. Tests: `test_email_ingestion_v2.py::test_no_acquisition_failure_is_terminal_on_first_attempt`, `::test_permanent_error_is_terminal_on_first_attempt`.

**17 `request_email_sync_now`**
- Callers: `api/routes/integrations.py:127` (user client, `auth.uid()`).
- PG: `auth.uid()` ownership, `GET DIAGNOSTICS`.
- Port: `request_email_sync_now(user_id, integration_id) -> bool`; ownership
  is `EXISTS(SELECT 1 FROM integrations WHERE id=? AND user_id=?)`; then the
  lease-respecting `next_poll_at = :now` update. After commit the route still
  calls `ingestion_runtime.nudge()` (`integrations.py:134–137`).
- Tests: only `test_schema_contract.py` (contract list). Add `test_db_email_sync.py::test_request_sync_now_respects_lease_and_owner`.

**18 `ensure_email_sync_state`** (trigger `integrations.integrations_ensure_email_sync_state`, AFTER INSERT OR UPDATE OF status, provider)
- Callers: the trigger, fired by every integration write: `complete_integration_reauthorization`, `fail_email_sync` (expiry), `services/integrations.py:374, 457, 489` (status/token updates), `workers/photo_fetch.py:97`.
- PG: `ON CONFLICT (integration_id) DO UPDATE` with a lease-respecting `CASE`, `interval '14 days'`.
- Port: a permanent SQLite trigger `AFTER INSERT ON integrations` and `AFTER UPDATE OF status, provider ON integrations`, `WHEN NEW.provider IN ('gmail','outlook') AND NEW.status = 'active'`, body `INSERT INTO email_sync_state(integration_id, user_id, provider, initial_watermark_at, next_poll_at, …) VALUES (NEW.id, NEW.user_id, NEW.provider, selko_ts_minus(selko_now(), 1209600), selko_now()) ON CONFLICT(integration_id) DO UPDATE SET next_poll_at = CASE WHEN lease_expires_at IS NULL OR lease_expires_at <= selko_now() THEN selko_now() ELSE next_poll_at END, consecutive_failures = 0, last_error_code = NULL, updated_at = selko_now()`.
  `selko_ts_minus` is a second UDF (timestamp text minus seconds) so the
  trigger never formats time in SQL (SQLite's `strftime('%f')` gives
  milliseconds only, which would break the fixed-width text ordering).
  `email_sync_state`'s primary key is `integration_id` (verified:
  `email_sync_state_pkey PRIMARY KEY (integration_id)`), so the trigger needs
  no generated id. `selko_uuid()` (third UDF) is still registered for the
  other triggers' tables that have `id DEFAULT gen_random_uuid()`, should any
  trigger insert into them (none does today).
- Tests: none name it; covered by `integration/test_integration_recovery.py::test_gmail_reauthorization_creates_no_recovery` and every ingestion test that creates an integration through the API. Add `test_db_email_sync.py::test_reactivation_resumes_without_rewinding_a_held_lease`.

**19 `reconcile_outlook_email_folders`** — **Dead.** No caller anywhere
(`workers/email_ingestion.py:638` deletes folders through PostgREST instead).
Only `integration/test_schema_contract.py`'s definer list names it. Safe to
drop: not ported.

### 2.3 `db/attachments.py` (2 functions)

| # | Function | Def | Exec | PL | Size | Diff |
|---|---|---|---|---|---|---|
| 20 | `claim_email_attachment(p_worker_id text, p_lease_seconds int=900) → SETOF attachments` | yes | service | 13 | 20 | S |
| 21 | `finish_email_attachment(p_attachment_id uuid, p_worker_id text, p_status text, p_error_code text=NULL) → boolean` | yes | service | 7 | 15 | S |

**20** Callers: `services/email_ingestion.py:491` (`claim_attachment`). PG: `FOR UPDATE SKIP LOCKED`, `make_interval`, `RETURNING`. Port: single claim `UPDATE`. Tests: `integration/test_integration_worker_pool_port.py::test_claim_and_finish_attachment`; `test_email_ingestion_v2.py`, `test_acquisition_executor_bound.py` (fakes).
**21** Callers: `services/email_ingestion.py:505` (`finish_attachment`). PG: `RAISE EXCEPTION 'Invalid attachment terminal state'`, `RETURN FOUND`. Port: `InvalidArgument` for a status outside `stored/unsupported/retry/dead_letter`; fenced `UPDATE`; when the new status is terminal the email's readiness changes, so emit `email_pending`? — **no**: Postgres does not (the email row is not touched, and `emails_notify_pending` fires only on email writes); keep parity. Tests: `integration/test_integration_worker_pool_port.py::test_claim_and_finish_attachment`; `test_attachment_type_rejected.py`.

### 2.4 `db/calendar_work.py` — calendar work items and routing (17 functions)

| # | Function | Def | Exec | PL | Size | Diff |
|---|---|---|---|---|---|---|
| 22 | `_enqueue_calendar_work(p_event_id uuid, p_user_id uuid, p_action text, p_desired_event jsonb, p_expected_provider_revision text, p_force_overwrite bool) → calendar_work_items` | yes | service | 39 | 45 | M |
| 23 | `enqueue_calendar_work(… same, defaults NULL/NULL/false) → jsonb` | yes | service | 9 | 12 | S |
| 24 | `claim_calendar_work_item(p_worker_id text, p_lease_seconds int=300, p_providers text[]=NULL) → SETOF calendar_work_items` | yes | service | 48 | 70 | L |
| 25 | `claim_calendar_work(p_worker_id text, p_lease_seconds int=300) → SETOF events` | yes | service | 7 | — | dead |
| 26 | `complete_calendar_work(p_item_id uuid, p_worker_id text, p_generation bigint, p_provider_event_id text, p_provider_revision text=NULL) → boolean` | yes | service | 28 | 35 | S |
| 27 | `fail_calendar_work(p_item_id uuid, p_worker_id text, p_generation bigint, p_error_code text, p_error_detail text=NULL, p_retryable bool=true) → jsonb` | yes | service | 22 | 35 | S |
| 28 | `defer_calendar_work(p_item_id uuid, p_worker_id text, p_generation bigint, p_next_retry_at timestamptz, p_detail text='calendar quota exceeded') → boolean` | yes | service | 13 | 20 | S |
| 29 | `heartbeat_calendar_work(p_item_id uuid, p_worker_id text, p_generation bigint, p_lease_seconds int) → boolean` | yes | service | 8 | — | dead |
| 30 | `unlock_expired_event_locks() → integer` | yes | service | 10 | — | dead (SQL) |
| 31 | `queue_event_cancellation(p_event_id uuid, p_user_id uuid) → jsonb` | yes | service | 22 | 30 | S |
| 32 | `unsync_event_and_enqueue_calendar_work(p_event_id uuid, p_user_id uuid, p_expected_provider_revision text=NULL, p_force_overwrite bool=false) → jsonb` | yes | service | 18 | 25 | S |
| 33 | `undo_event_and_enqueue_calendar_work(p_event_id uuid, p_user_id uuid, p_action text=NULL, p_desired_event jsonb=NULL, p_expected_provider_revision text=NULL, p_force_overwrite bool=false) → jsonb` | yes | service | 16 | 22 | S |
| 34 | `calendar_write_provider(p_user_id uuid, p_event_id uuid) → text` (STABLE) | yes | service | 20 | 25 | S |
| 35 | `calendar_integration_writable(p_user_id uuid, p_provider text) → boolean` (sql, STABLE) | yes | service | 9 | 12 | S |
| 36 | `calendar_provider_of_id(p_id text) → text` (sql, IMMUTABLE) | no | PUBLIC | 3 | 0 (reuse) | S |
| 37 | `outlook_scopes_allow_calendar(p_scopes text[]) → boolean` (sql, IMMUTABLE) | no | PUBLIC | 6 | 0 (reuse) | S |
| 38 | (trigger fn) `calendar_work_item_owner_check() → trigger` | yes | service | 11 | 8 (SQL) | S |

**22 `_enqueue_calendar_work`**
- Callers (internal only): `apply_event_change_proposal`, `commit_email_extraction`, `enqueue_calendar_work`, `queue_event_cancellation`, `reopen_event_change_proposal`, `set_event_review_status`, `undo_event_and_enqueue_calendar_work`, `unsync_event_and_enqueue_calendar_work`.
- PG: `FOR UPDATE`, `RAISE … 22023` (invalid action; upsert without desired event; upsert for `rejected`/`cancelled` event), `42501` (not owned), `max(generation)+1`, supersede then `INSERT … RETURNING *` (the partial unique index `calendar_work_items_one_active_per_event` forbids two active rows, so the order matters and is kept).
- Port: `_enqueue_calendar_work(tx, event_id, user_id, action, desired_event, expected_provider_revision, force_overwrite) -> dict` — takes the caller's `tx` (it is never a transaction of its own). `desired_event` stored as JSON text. Raises `InvalidArgument`/`NotOwned` with the same messages.
- Note: `jsonb_build_object('start_datetime', p_start_datetime, …)` in callers renders a `timestamptz` as Postgres JSON text (`"2026-11-25T10:00:00+00:00"`); the port writes `codec.ts()` strings instead. Verified harmless: the only consumer of `desired_event` is `workers/calendar_sync.py:81`, which reads `delete_remote` and nothing else (`services/events.py:2551` copies it onto the claimed event); upserts write from the event row.
- Tests: `integration/test_integration_extraction_intent.py::test_calendar_upsert_is_refused_for_a_declined_event`, `::test_queueing_calendar_work_does_not_change_the_review_decision`.

**23 `enqueue_calendar_work`**
- Callers: `api/routes/events.py:122` (`sync_event`, service client); `scripts/seed_screenshot_data.py:397`.
- Port: `with db.write() as tx: item = _enqueue_calendar_work(tx, …)`; returns `{id, event_id, generation, status, action}`.
- Tests: `test_api_routes.py::test_event_sync_requeues_sync_failed_event_for_worker`; `integration/test_integration_work_listener.py::test_durability_missed_notification_costs_latency_never_work`, `::test_d3_two_listeners_one_notification_one_claim`; `integration/test_integration_workers.py::test_claim_approved_event_directly`, `::test_complete_event_sync_updates_status`, `::test_fail_event_sync_with_retry`, `::test_concurrent_workers_no_duplicate_event_sync`, `::test_claim_excludes_users_without_active_calendar_integration`, `::test_multiple_workers_get_different_events`; `integration/test_integration_calendar_work_items.py::test_enqueue_claim_complete_is_item_fenced`, `::test_new_enqueue_supersedes_old_and_stale_completion_is_fenced`, `::test_expired_processing_item_is_reclaimable`; `integration/test_integration_outlook_calendar.py`, `integration/test_integration_calendar_recovery_worker.py`, `integration/test_integration_automatic_cancellation.py`, `integration/test_integration_worker_pool_port.py`.

**24 `claim_calendar_work_item`** — hardest claim.
- Callers: `services/events.py:2510` (`claim_approved_event_for_sync`, asyncpg, passes `providers` from the circuit breaker) ← `workers/pool.py:333`; `scripts/seed_screenshot_data.py:410`.
- PG: `CROSS JOIN LATERAL` computing each row's provider with `calendar_write_provider()` (a plpgsql function per candidate row), `= ANY(p_providers)`, `calendar_integration_writable()` per row, two `FOR UPDATE OF w SKIP LOCKED` passes (pending, then expired processing reclaimed to pending), `make_interval`, `RETURNING *`.
- Port: SQLite cannot call a Python routing function per row cheaply inside `WHERE` (a UDF can, but `calendar_write_provider` itself queries three tables). Do it in two steps inside one `tx`:
  1. `SELECT w.*, e.google_calendar_event_id, s.target_calendar_id FROM calendar_work_items w JOIN events e ON e.id = w.event_id LEFT JOIN user_calendar_settings s ON s.user_id = w.user_id WHERE w.status='pending' AND w.attempts < w.max_attempts AND (w.next_retry_at IS NULL OR w.next_retry_at <= :now) ORDER BY w.created_at LIMIT :scan` (scan = 50);
  2. load the candidate users' integrations in one query
     (`SELECT user_id, provider, status, scopes FROM integrations WHERE user_id IN (…)`), compute each candidate's provider with the
     existing Python twins (`calendar_providers.provider_of_id`,
     `writable_providers`, `resolve_target_provider`; same rules as
     `calendar_write_provider`: existing event id → target calendar → Google if writable → Outlook if writable → Google), filter by `providers` and writability, take the first;
  3. if none, repeat for `status='processing' AND locked_until < :now` ordered by `locked_until`, resetting the chosen row to `pending` first (as today);
  4. `UPDATE … SET status='processing', locked_by, locked_until, attempts+1, provider=:p RETURNING *` and touch `events.updated_at`.
  If 50 pending rows are all unwritable, loop the scan with an offset until exhausted (Postgres scans the whole queue; keep that, or the claim starves behind 50 blocked users). Behaviour is identical; the per-row SQL function becomes per-batch Python.
- Tests: `test_outlook_calendar.py::test_the_claim_passes_providers_to_the_rpc`; `integration/test_integration_workers.py::test_claim_excludes_users_without_active_calendar_integration`, `::test_concurrent_workers_no_duplicate_event_sync`, `::test_multiple_workers_get_different_events`; `integration/test_integration_calendar_work_items.py::test_expired_processing_item_is_reclaimable`; `integration/test_integration_outlook_calendar.py` (all); `test_state_ownership_s5.py`; `test_workers.py`.

**25 `claim_calendar_work`** — **Dead.** A wrapper returning the event row; no caller. `test_workers.py::test_worker_pool_claims_over_the_pool` mentions it only to assert it is *not* used. Safe to drop; not ported.

**26 `complete_calendar_work`**
- Callers: `services/events.py:2594` (`complete_event_sync`), `:2618` (`complete_event_cancellation`), both after `_resolve_calendar_work_item` (`:2572`, inline SQL below); `scripts/seed_screenshot_data.py:420`.
- PG: `FOR UPDATE`, `IS DISTINCT FROM` fences, `CASE`.
- Port: fenced read; one `UPDATE events` with the same `CASE` (cancel clears `google_calendar_event_id`/`synced_at`; `cancelled` only when the event was `active`); item → `succeeded`. Returns bool.
- Tests: `integration/test_integration_workers.py::test_complete_event_sync_updates_status`; `integration/test_integration_calendar_work_items.py::test_enqueue_claim_complete_is_item_fenced`, `::test_unsync_is_worker_owned_and_clears_remote_identity_on_completion`; `integration/test_integration_automatic_cancellation.py::test_cancel_claim_and_completion_are_worker_owned`; `test_state_ownership_s5.py`.

**27 `fail_calendar_work`**
- Callers: `services/events.py:2679` (`park_event_for_oauth_reauth`, `retryable=False`), `:2718` (`fail_event_sync`); `scripts/seed_screenshot_data.py:431, 461`.
- PG: `FOR UPDATE`, `power(2, least(attempts-1,5))`, `make_interval`, `left()`.
- Port: fenced read; backoff `min(1800, max(60, 60 * 2**min(attempts-1, 5)))`; status `pending`/`failed`/`blocked`; returns `{fenced, status}`.
- Tests: `test_reliability.py::test_event_retry_with_backoff`, `::test_event_delay_capped`, `::test_oauth_park_releases_claim_without_spending_attempt_or_dead_lettering`, `::test_dead_letter_on_max_sync_attempts`, `::test_no_dead_letter_on_event_retry`; `integration/test_integration_workers.py::test_fail_event_sync_with_retry`.

**28 `defer_calendar_work`** — Callers: `services/events.py:2646` (`defer_event_sync_for_quota`). PG: `FOR UPDATE`, `greatest`, `left`. Port: fenced update, `attempts = max(attempts-1, 0)`, `next_retry_at` normalised by `codec.ts` (the caller passes an ISO string). Tests: `test_reliability.py::test_calendar_quota_deferral_releases_claim_without_spending_attempt`.

**29 `heartbeat_calendar_work`** — **Dead.** No caller in code or scripts; only `test_schema_contract.py`'s definer list. Safe to drop.

**30 `unlock_expired_event_locks` (SQL)** — **Dead.** The Python function of the same name (`services/events.py:2735`, called at `api/app.py:135`) runs `SELECT count(*) … WHERE status='processing' AND locked_until < now()` (`:2752`) and never calls the SQL function; claim-time recovery owns mutation. Port only the Python count (`db.calendar_work.count_expired_leases`) or fold it into the startup reset. Tests: `test_ingestion_runtime.py::test_lifespan_runs_ingestion_in_process`; `integration/test_integration_worker_pool_port.py::test_unlock_expired_helpers_run`.

**31 `queue_event_cancellation`**
- Callers: `scripts/repair_review_queue_integrity.py:442` only (operator repair, asyncpg). Production automatic cancellation goes through `commit_email_extraction` with `calendar_action='cancel'`.
- PG: `FOR UPDATE`, `EXISTS` on processing work, `RAISE EXCEPTION 'event % cannot be cancelled in its current state'`.
- Port: straightforward; `InvalidArgument` for the refusal. Keep (the repair tool is the documented recovery path), unless the repair tool is retired with Postgres — see §6.
- Tests: `test_repair_review_queue_integrity.py::test_repair_migration_secures_audit_and_centralizes_cancellation` (reads a migration file; rewritten); `integration/test_integration_automatic_cancellation.py::test_cancel_claim_and_completion_are_worker_owned`.

**32 `unsync_event_and_enqueue_calendar_work`** — Callers: `api/routes/events.py:235` (`unsync_event`). PG: `FOR UPDATE`, `EXISTS`, `'{"delete_remote": true}'::jsonb`, `RAISE … 22023 'event % is not synced'`. Port: same checks; `desired_event={"delete_remote": True}`. Tests: `test_api_routes.py::test_event_unsync_queues_worker_deletion`; `integration/test_integration_calendar_work_items.py::test_unsync_is_worker_owned_and_clears_remote_identity_on_completion`.

**33 `undo_event_and_enqueue_calendar_work`** — Callers: `services/events.py:2350` (`undo_history_event`) ← `api/routes/events.py:382`. Port: optional enqueue then `review_status='pending_review'`. Return `{status, work_item_id, generation}` (the caller tests truthiness: `events.py:2358`). Tests: `unit/test_undo_history_event.py::test_new_synced_queues_calendar_delete`; `integration/test_integration_events.py` (undo).

**34 `calendar_write_provider`**, **35 `calendar_integration_writable`** — Callers: internal only (`claim_calendar_work_item`, `requeue_calendar_recovery_batch`). Python twins exist and are named as such: `services/calendars.py:724–741` (`_write_provider`), `services/calendar_providers.py:109` (`writable_providers`), `:126` (`resolve_target_provider`). Port: `db/calendar_work.py` imports those twins (one implementation instead of two — the "SQL twin" comments go away). Note the SQL treats `target_calendar_id = ''` as unset and Python treats any falsy value as unset: identical. Tests: `test_outlook_calendar.py::test_only_a_calendar_grant_makes_outlook_writable`; `integration/test_integration_outlook_calendar.py`.

**36 `calendar_provider_of_id`**, **37 `outlook_scopes_allow_calendar`** — Callers: internal (34, 35, `complete_integration_reauthorization`). Twins: `calendar_providers.provider_of_id` (`:90`), `outlook_scopes_allow_calendar` (`:97`; SQL `lower(s) LIKE '%calendars.readwrite'` ≡ Python `lower().endswith`). Port: 0 new lines. Tests: `test_outlook_calendar.py::test_only_a_calendar_grant_makes_outlook_writable`, `::test_the_mirror_loop_includes_calendar_capable_outlook_rows`.

**38 `calendar_work_item_owner_check`** (trigger `calendar_work_items.calendar_work_items_owner_check`, BEFORE INSERT OR UPDATE)
- PG: `RAISE … 23514 'calendar work item owner does not match event owner'`.
- Port: permanent SQLite trigger `BEFORE INSERT ON calendar_work_items` and `BEFORE UPDATE OF user_id, event_id ON calendar_work_items` with `WHEN (SELECT user_id FROM events WHERE id = NEW.event_id) IS NOT NEW.user_id BEGIN SELECT RAISE(ABORT, 'calendar work item owner does not match event owner'); END`. `Tx.execute` maps `sqlite3.IntegrityError` with that message to `InvariantViolation`. (Postgres fires it on every UPDATE; restricting to the two columns is equivalent because no other column affects the check.)
- Tests: `test_schema_contract.py::test_live_triggers_for_every_triggered_table` (rewritten against `sqlite_master`). Add one negative test.

### 2.5 `db/events.py` — extraction commit and review decisions (3 functions)

| # | Function | Def | Exec | PL | Size | Diff |
|---|---|---|---|---|---|---|
| 39 | `commit_email_extraction(p_email_id uuid, p_worker_id text, p_generation bigint, p_decisions jsonb, p_terminal text) → jsonb` | yes | service | 251 | 300 | L |
| 40 | `set_event_review_status(p_event_id uuid, p_review_status text, p_user_id uuid=NULL) → jsonb` | yes | service, +auth | 46 | 45 | S |
| 41 | `ignore_sender_and_reject_pending(p_sender_email text=NULL, p_sender_domain text=NULL) → jsonb` | no (invoker) | anon+auth+service | 81 | 90 | M |

**39 `commit_email_extraction`** — the largest function (251 lines).
- Callers: `services/events.py:148` (`_commit_email_extraction`, service supabase client) ← `process_email_for_events` (`services/events.py`, run in a thread by `workers/email_process.py:65`); `scripts/seed_screenshot_data.py:113`.
- PG: `FOR UPDATE` on the email; lease fence (`locked_by`/`lock_generation` `IS DISTINCT FROM`); `pg_advisory_xact_lock(hashtextextended(…))` per decision window and per hint, taken in sorted order; band fingerprint `md5(string_agg(id || ':' || to_char(updated_at AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS.US"Z"') ORDER BY id))`; hint fingerprint over `events ∪ calendar_entries` selected through `event_identity_hints` with `format('%s|%s|%s', kind, value_hash, recurrence_id) IN (jsonb_array_elements_text(hint_keys))`; `jsonb` field access with `?`; 12 `RAISE EXCEPTION`s (9 with `22023`); `INSERT … RETURNING`; three `ON CONFLICT` upserts (`event_sources` partial index `WHERE source_origin='email'`, `event_change_proposals (source_id)`, `event_identity_hints (event_id, kind, value_hash, recurrence_id)` with a sequence-monotonic `CASE`); calls `_enqueue_calendar_work`; fires the deferred proposal invariant and five broadcast triggers.
- Port, one `tx`:
  1. validate `terminal ∈ {processed, skipped, failed}` → `InvalidArgument`;
  2. read the email; missing → `NotFound`; fence mismatch → return `{"fenced": True, "applied": 0}`;
  3. **no advisory locks** (the writer lock serializes every commit);
  4. for each non-noop decision, in input order with its index: recompute the band fingerprint with `resolution_fingerprint.candidate_fingerprint(rows)` over `SELECT id, updated_at FROM events WHERE user_id=? AND start_datetime >= ? AND start_datetime < ?`, and the hint fingerprint with a new `resolution_fingerprint.hint_fingerprint(rows)` (sorted keys, md5) over the same two-table selection, matching hint keys with `kind || '|' || value_hash || '|' || recurrence_id IN (SELECT value FROM json_each(?))`. Mismatch → `{"fenced": False, "conflict": True, "conflicting_indexes": [i]}`. Because the producer side (`services/events.py`, which computes `expected_fingerprint` and `expected_hint_fingerprint` before the LLM call) and the commit side now call the same Python function on the same `codec` timestamps, the collation mismatch in §0.5 disappears. `updated_at` is stored with microseconds, so the `to_char(… .US)` format is exactly `codec.ts`;
  5. the decision loop: the same validation ladder and messages (`InvalidArgument` for the `22023` ones; `NotOwned` for "event % is not owned by email user"; `InvalidArgument` for "update decision requires event_id", "invalid identity hint", "invalid extraction decision envelope"); `create` inserts with a Python `uuid4()`; `update` applies only the keys present in `fields` (Python `if key in fields`); `event_sources` upsert keeps the partial-index target; extra Google sources inserted; proposals: supersede other pending ones, then UPSERT on `source_id` with `resolved_at = NULL if pending else :now`; `_enqueue_calendar_work(tx, …)` when `review_status='active'` and intent ∈ {no_change, apply}; hints UPSERT with the `sequence`/`dtstamp` `CASE` written as `CASE WHEN excluded.kind='ical_uid' AND excluded.sequence >= event_identity_hints.sequence THEN excluded.sequence ELSE event_identity_hints.sequence END`;
  6. mark the email terminal; return `{"fenced": False, "conflict": False, "applied": n, "event_ids": [...]}`.
  The caller's `isinstance(result, list)` unwrap (`events.py:159`) becomes dead.
- Hard parts: (a) ordering — Postgres iterates decisions in `jsonb_array_elements` order for the write loop and in `(window_start, window_end)` order only for lock acquisition; with no locks the second ordering is irrelevant, the write order stays input order; (b) `(v_fields->>'all_day')::boolean` accepts `'true'/'false'/'t'/'f'` strings — Python must coerce strings the same way (`codec.pg_bool`) because the decisions are built from LLM output; (c) `(v_fields->>'start_datetime')::timestamptz` parses offsets and naive values in the database time zone (UTC) — `codec.ts_in` must treat naive as UTC.
- Tests (must all pass unchanged in intent): `integration/test_integration_fenced_event_commit.py::test_stale_generation_cannot_write`, `::test_multi_event_email_commits_all_or_nothing`, `::test_zombie_generation_after_reclaim_writes_nothing`; `integration/test_integration_event_identity.py::test_commit_writes_identity_hints_in_same_transaction`, `::test_hint_lookup_is_part_of_the_commit_fence`; `integration/test_integration_identity_mirror_fence.py` (all); `integration/test_integration_extraction_intent.py` (all); `integration/test_integration_events.py`; `integration/test_integration_hint_upsert.py`; unit: `test_fenced_event_commit.py`, `test_extraction_decision_intent.py`, `test_events_refactor.py`, `test_events.py`, `test_selko_managed_updates.py`, `test_declined_event_terminality.py`, `test_calendar_policy.py` (these stub `_commit_email_extraction` or the supabase client; they move to the temp-SQLite fixture).

**40 `set_event_review_status`**
- Callers: `frontend/src/lib/services/events.js:172` (web, `auth.uid()`; the Q1 section moves it behind an API route); `frontend/src/lib/services/__tests__/events.test.js:438, 450` (stubs).
- PG: `auth.uid()`/`auth.role()`, `FOR UPDATE`, `42501`/`22023`, `jsonb_build_object` including `source_attribution`, `_enqueue_calendar_work`.
- Port: `set_event_review_status(user_id, event_id, review_status)`; same order (write `active` before enqueue so the declined-event guard sees the new decision). Returns `{event_id, review_status, work_item_id, generation}`.
- Tests: none in the backend (only the contract list). Add `test_db_events.py::test_approve_enqueues_upsert_and_reject_does_not` and the route test the Q1 section requires.

**41 `ignore_sender_and_reject_pending`** — see §0.1 and §5.6.
- Callers: `frontend/src/lib/services/sender-rules.js:81` (web; Q1 moves it behind an API route).
- PG: `auth.uid()`, two partial-index `ON CONFLICT … WHERE sender_email IS NOT NULL` upserts, `UPDATE … FROM` CTE, `GET DIAGNOSTICS`, `LIKE '%@' || domain`, `FOR UPDATE OF p, e` loop, `jsonb ?`/`->>`, the broken 14-argument `PERFORM reject_event_change_proposal(…)`.
- Port: `db/sender_rules.ignore_sender_and_reject_pending(user_id, sender_email=None, sender_domain=None) -> {"rejected_new": n, "discarded_changes": m}`; rule upsert; New-lane rejection with `UPDATE events SET review_status='rejected' … WHERE user_id=? AND review_status='pending_review' AND id IN (SELECT DISTINCT s.event_id FROM event_sources s JOIN emails m ON m.id = s.email_id WHERE m.user_id=? AND (m.from_email = ? OR m.from_email LIKE '%@' || ?))`; then for each matching pending proposal call `db.proposals.reject_event_change_proposal(tx, …, resolution_reason='repair_operator')` with the snapshot-restored fields, **dropping the obsolete restore-status argument** (the 13-argument function no longer accepts one and documents why: a pending proposal's event is `active` and rejecting it does not change the decision). Whether `resolution_reason` should be `user_rejected` rather than `repair_operator` is a product decision (`reject_event_change_proposal` accepts both): keep `repair_operator` (what the code says) and flag it.
- Note `LIKE` is case-insensitive for ASCII in SQLite but case-sensitive in Postgres: use `m.from_email GLOB '*@' || ?` or `substr(m.from_email, -length(?)-1) = '@' || ?` to keep Postgres semantics. The same applies to every `LIKE` in §2 (`reset_skipped_emails_for_sender_rule`, `health_work_state`'s `incident_key LIKE 'email-sync:%'` — the last is harmless either way). Alternatively `PRAGMA case_sensitive_like=ON` on every connection (deprecated but supported in 3.53): prefer the explicit expressions.
- Tests: none. Add `test_db_sender_rules.py::test_ignore_rejects_new_and_discards_pending_changes` (the case that is broken today) and `::test_ignore_domain_matches_suffix_case_sensitively`.

### 2.6 `db/proposals.py` — change proposals (7 functions)

| # | Function | Def | Exec | PL | Size | Diff |
|---|---|---|---|---|---|---|
| 42 | `_lock_owned_pending_proposal(p_event_id uuid, p_user_id uuid, p_proposal_id uuid, p_expected_hash text) → event_change_proposals` | no | anon+auth+service | 17 | 18 | S |
| 43 | `event_change_proposal_hash(p_proposal event_change_proposals) → text` (sql, IMMUTABLE) | no | PUBLIC | 12 | 20 | M |
| 44 | `apply_event_change_proposal(13 args, see below) → jsonb` | yes | service | 32 | 40 | S |
| 45 | `reject_event_change_proposal(p_event_id uuid, p_user_id uuid, p_proposal_id uuid, p_expected_hash text, p_delete_event bool, p_title text, p_start_datetime timestamptz, p_end_datetime timestamptz, p_all_day bool, p_location text, p_description text, p_importance text, p_resolution_reason text) → jsonb` | yes | service | 31 | 40 | S |
| 46 | `reopen_event_change_proposal(p_event_id uuid, p_user_id uuid, p_proposal_id uuid, p_expected_hash text, p_action text=NULL, p_desired_event jsonb=NULL, p_expected_provider_revision text=NULL, p_force_overwrite bool=false) → jsonb` | yes | service | 31 | 40 | S |
| 47 | `resolve_event_change_proposal(p_event_id uuid, p_user_id uuid, p_proposal_id uuid, p_expected_hash text, p_resolution_reason text) → jsonb` | no | anon+auth+service | 23 | 25 | S |
| 48 | (trigger fn) `enforce_event_change_proposal_invariant() → trigger` | yes | service | 32 | 50 | L |

`apply_event_change_proposal` signature: `(p_event_id uuid, p_user_id uuid, p_proposal_id uuid, p_expected_hash text, p_title text, p_start_datetime timestamptz, p_end_datetime timestamptz, p_all_day bool, p_location text, p_description text, p_importance text, p_review_status text, p_calendar_sync_action text)`.

**42 `_lock_owned_pending_proposal`** — Callers: `apply_event_change_proposal`, `reject_event_change_proposal`. PG: `FOR UPDATE OF p, e`, `40001`. Port: `tx`-scoped read; `ProposalStateError` / `StaleProposal`. Tests: through 44/45.

**43 `event_change_proposal_hash`**
- Callers: `_lock_owned_pending_proposal` (`fdefs` 80), `reopen_event_change_proposal`, `resolve_event_change_proposal`; `scripts/repair_review_queue_integrity.py:302`. **Every backend caller passes `p_expected_hash = NULL`** (`services/events.py:2133, 2198, 2237, 2338`), so the hash is only ever compared when the repair script supplies one it computed itself.
- PG: `sha256(convert_to(jsonb_build_object(…)::text))`. The value depends on jsonb's canonical text (keys ordered by length, then bytes; Postgres timestamp text).
- Port: `sha256(json.dumps({...}, sort_keys=True, separators=(",", ":")))` over the decoded row. **Not byte-compatible** with the Postgres hash; harmless because no hash is persisted (manifests made by the repair tool before cutover become invalid: re-run its dry run after cutover). Tests: none name it; add a round-trip test (`hash(row)` matches, any field change mismatches).

**44 `apply_event_change_proposal`** — Callers: `services/events.py:2129` (`apply_change_proposal`) ← `api/routes/events.py:322`. PG: `FOR UPDATE`, `22023`, `jsonb_build_object`, `_enqueue_calendar_work`. Port: one `tx`; `desired_event` built with `codec.ts`. Tests: `integration/test_integration_event_change_proposals.py::test_proposal_is_authoritative_and_apply_reject_reopen_are_atomic`; `integration/test_integration_events.py` (apply); `test_events_refactor.py`.

**45 `reject_event_change_proposal`** — Callers: `services/events.py:2194` (delete branch), `:2233` ← `api/routes/events.py:356`; and (broken) `ignore_sender_and_reject_pending`. PG: `FOR UPDATE`, `22023`, `DELETE`s. Port: takes `tx` as an optional first argument so `ignore_sender…` can call it inside its own transaction; `db.proposals.reject_event_change_proposal(...)` without a `tx` opens one. Tests: `integration/test_schema_contract.py::test_reject_event_change_proposal_is_one_atomic_transition` (moves to `test_db_proposals.py`); `test_events_refactor.py`.

**46 `reopen_event_change_proposal`** — Callers: `services/events.py:2334` (`undo_history_event`). PG: `FOR UPDATE`, `40001`, `NULLIF(…,'')::timestamptz`, `to_jsonb(v_item)`. Port: returns `{event_id, proposal_id, status:'active', calendar_work: item-dict-or-None}`. Ordering hazard: it sets the proposal `pending` **before** setting the event `active` — legal only because the invariant is deferred (§5.5). Tests: `integration/test_integration_event_change_proposals.py::test_proposal_is_authoritative_and_apply_reject_reopen_are_atomic`; `unit/test_undo_history_event.py::test_applied_change_restores_calendar`, `::test_gcal_404_clears_sync_on_change_undo`.

**47 `resolve_event_change_proposal`** — Callers: `scripts/repair_review_queue_integrity.py:461` only (asyncpg). Port only if the repair tool survives (§6). Tests: none.

**48 `enforce_event_change_proposal_invariant`** (constraint triggers `event_change_proposals.event_change_proposals_invariant` AFTER INSERT OR DELETE OR UPDATE, and `events.events_change_proposal_invariant` AFTER INSERT OR UPDATE, both `DEFERRABLE INITIALLY DEFERRED`) — see §5.5. Tests: `integration/test_schema_contract.py::test_pending_proposal_requires_active_review_status` (moves to `test_db_proposals.py`).

### 2.7 `db/recovery.py` — reconnect recovery (5 functions)

| # | Function | Def | Exec | PL | Size | Diff |
|---|---|---|---|---|---|---|
| 49 | `complete_integration_reauthorization(p_user_id uuid, p_provider text, p_access_token text, p_refresh_token text=NULL, p_token_expiry timestamptz=NULL, p_scopes text[]='{}', p_provider_email text=NULL) → uuid` | yes | service | 45 | 50 | M |
| 50 | `claim_integration_recovery(p_worker_id text, p_lock_seconds int=300) → SETOF integration_recoveries` | yes | service | 30 | 25 | S |
| 51 | `requeue_calendar_recovery_batch(p_recovery_id uuid, p_worker_id text, p_batch_size int=100, p_max_batches int=5) → integer` | yes | service | 43 | 60 | M |
| 52 | `refresh_waiting_calendar_recoveries(p_batch_size int=20) → integer` | yes | service | 22 | 30 | S |
| 53 | `unlock_expired_integration_recoveries() → integer` | yes | service | 10 | 12 | S |

**49** Callers: `services/integrations.py:195` ← `save_oauth_credentials` (`:236`) ← `api/routes/integrations.py:390`; ← `save_provider_tokens` (`:273`) ← `api/routes/integrations.py:477`. PG: `ON CONFLICT (user_id, provider) DO UPDATE` with `COALESCE(EXCLUDED.refresh_token, integrations.refresh_token)`, `integration_provider` enum cast, `text[]`, supersede-then-insert (partial unique `integration_recoveries_one_active_idx`). Port: one `tx`; scopes as JSON; enum is a `CHECK`; `outlook_scopes_allow_calendar` Python twin; fires `integrations_ensure_email_sync_state` and the live hint. Returns the id (today `result.data`, a string). Tests: `test_integrations.py::test_saves_all_fields`, `::test_saves_via_reauthorization_rpc`, `::test_returns_integration_id_from_rpc`, `::test_wraps_rpc_failure`; `integration/test_integration_recovery.py::test_upserts_credentials_and_creates_calendar_recovery`, `::test_preserves_existing_refresh_token_when_omitted`, `::test_repeated_reauthorization_supersedes_previous_recovery`, `::test_gmail_reauthorization_creates_no_recovery`; `integration/test_integration_outlook_calendar.py`; `integration/test_integration_calendar_recovery_worker.py`.

**50** Callers: `services/integrations.py:401` ← `workers/pool.py:427`. PG: `FOR UPDATE SKIP LOCKED`, `make_interval`, `COALESCE(started_at, now())`. Port: single claim `UPDATE`. Tests: `test_integrations.py::test_claim_returns_first_row`, `::test_claim_returns_none_when_nothing_pending`; `test_workers.py::test_claims_pending_recovery_and_tags_batch`, `::test_lost_claim_is_not_treated_as_processed`, `::test_idle_recovery_probe_is_throttled`, `::test_active_recovery_releases_the_throttle`, `::test_falls_through_to_recovery_when_no_events`; `integration/test_integration_recovery.py::test_claim_locks_row_and_increments_attempts`, `::test_superseded_recovery_cannot_be_requeued_by_old_worker`; `integration/test_integration_worker_pool_port.py::test_calendar_recovery_claim_and_refresh_run`.

**51** Callers: `services/calendars.py:182` ← `workers/pool.py:436`. PG: data-modifying CTE chain (`batch` with `FOR UPDATE OF w SKIP LOCKED` → `revived` `UPDATE … FROM batch RETURNING` → `UPDATE events`), `calendar_write_provider` per row, `GET DIAGNOSTICS`, `LOOP … EXIT WHEN`. Port: Python loop of at most `max_batches`: select candidate items (failure code `oauth_required`/`oauth_scope_required`, status `failed`/`blocked`, `e.recovery_id IS NULL`, no newer active item) joined with event and settings, compute provider with the Python twin, keep those equal to the recovery's provider, take `batch_size`, `UPDATE` them back to `pending` (`attempts = min(attempts, max_attempts-1)`), tag events; then counters and `waiting` status. Fenced by `locked_by = ? AND locked_until > :now`, `-1` when lost. Tests: `test_calendars.py::test_returns_tagged_count_from_rpc`, `::test_wraps_rpc_failure`; `integration/test_integration_outlook_calendar.py::test_reconnecting_requeues_parked_items_for_that_provider_only`; `integration/test_integration_recovery.py`; `integration/test_integration_calendar_recovery_worker.py`; `integration/test_integration_worker_pool_port.py::test_calendar_recovery_claim_and_refresh_run`; `test_workers.py` (above).

**52** Callers: `services/calendars.py:205` ← `workers/pool.py:460`. PG: `FOR … SKIP LOCKED` loop, `count(*) FILTER (WHERE …)`. Port: `SUM(CASE WHEN …)` per recovery. Tests: `test_calendars.py::test_returns_processed_count_from_rpc`, `::test_defaults_to_zero_when_rpc_returns_none`; `integration/test_integration_calendar_recovery_worker.py`; `test_workers.py::test_falls_back_to_refreshing_waiting_recoveries`.

**53** Callers: `services/integrations.py:424` ← `api/app.py:138`. Port: one `UPDATE`; part of §7.3. Tests: `test_integrations.py::test_unlock_returns_count`; `integration/test_integration_recovery.py::test_unlock_expired_returns_locked_rows_to_pending`; `test_ingestion_runtime.py::test_lifespan_recovers_stale_integration_recoveries_on_startup`.

### 2.8 `db/health.py` (1 function)

**54 `health_work_state(p_warning_seconds int) → TABLE(status text, ready_emails int, processing_emails int, stale_processing_emails int, unclaimable_pending int, failed_emails int, stale_sync_runs int, items_pending int, items_dead_letter int, attachments_dead_letter int, items_stalled_seconds int, integrations_due int, leases_held int, oldest_next_poll_seconds int, open_incidents int)`** — definer, service, PL 132 lines → ~90 Python, **M**.
- Callers: `api/routes/health.py:41` (`_work_state_status`), `:146` (`_work_state_counts`), `workers/ingestion_runtime.py:414` (`health_snapshot`). Prose: `scripts/assert-health.sh:31`, `scripts/drill-staging-workers.sh:90`.
- PG: 14 `count(*)`s, `EXTRACT(EPOCH FROM (now() - min(…)))`, `COALESCE`, `LIKE 'email-sync:%'`.
- Port: all 14 counts in one read transaction on a read connection, so they share one WAL snapshot. (plpgsql under `READ COMMITTED` takes a new snapshot per statement, so the SQLite version is at least as consistent.) Seconds computed in Python from `codec` timestamps. `ready_emails` uses the shared `CLAIMABLE_EMAIL_PREDICATE`; `items_stalled_seconds` must keep mirroring `claim_email_ingestion_item`'s predicate (put both in one constant too). Returns a dict with the 15 keys (callers unwrap `data[0]` today: `health.py:46, 151`, `ingestion_runtime.py:419` — those unwraps go).
- Tests: `test_ingestion_runtime.py::test_health_snapshot_counts_1500_dead_letters_without_truncation`; `test_api_routes.py::test_health_ok`, `::test_health_ingestion_when_background_processing_is_off`, `::test_health_ingestion_does_not_degrade_on_terminal_failures`; `integration/test_integration_api.py::test_health_check`; `integration/test_integration_ingestion_stall_signal.py` (all); `integration/test_integration_email_state_machine.py::test_health_degrades_on_unclaimable_or_stale_work`, `::test_health_counts_use_worker_claim_predicates`, `::test_health_ignores_expired_integration_poll_age`.

### 2.9 `db/quotas.py` (3 functions)

| # | Function | Def | Exec | PL | Size | Diff |
|---|---|---|---|---|---|---|
| 55 | `check_and_increment_quota(p_user_id uuid, p_quota_type text, p_increment int=1) → TABLE(allowed bool, current_count int, quota_limit int, remaining int)` | yes | service | 79 | 50 | S |
| 56 | `get_user_quota_usage(p_user_id uuid, p_date date=CURRENT_DATE) → TABLE(9 int columns)` | yes | service | 20 | — | dead in production |
| 57 | `get_llm_usage_summary(p_user_id uuid, p_start_date date=CURRENT_DATE, p_end_date date=CURRENT_DATE) → TABLE(total_calls int, successful_calls int, failed_calls int, total_tokens bigint, total_prompt_tokens bigint, total_completion_tokens bigint, total_latency_ms bigint, avg_latency_ms int, estimated_cost_usd numeric, calls_by_operation jsonb)` | yes | service | 37 | — | dead in production |

**55** Callers: `services/quotas.py:118` (`QuotaService.check_and_increment`) ← `services/llm_gateway.py:831`, `api/routes/emails.py:116`, `workers/pool.py:554`. PG: `pg_advisory_xact_lock(hashtext(user || date))`, `CURRENT_DATE`, `ON CONFLICT DO NOTHING`, `EXECUTE format('%I')` over a 3-way column map, `RAISE EXCEPTION 'Invalid quota type: %'`. Port: column map dict (whitelist), no lock, `tx.now.date()`; returns a dict (`QuotaService` reads `result.data[0]` today, adapt). Tests: `unit/test_quota_service.py::test_check_and_increment_allowed`, `::test_check_and_increment_custom_increment`; `integration/test_rate_limiting.py::test_quota_rpc_check_and_increment`; `integration/test_rate_limiting.py::test_usage_quotas_rls_only_own_data` (an RLS test: deleted, replaced by the Q3 cross-user test).

**56** Callers: `services/quotas.py:184` (`QuotaService.get_usage`), which nothing in `backend/selko` calls (tests only: `test_security.py`, `integration/test_rate_limiting.py::test_quota_rpc_get_user_usage`, `unit/test_quota_service.py`). **Dead in production.** Safe to drop together with `QuotaService.get_usage`; or port as a 20-line read if the Q1 section wants a usage endpoint. Recommendation: drop.

**57** Callers: `services/llm_logging.py:307` (`get_user_usage_summary`), no caller in `backend/selko` (test: `integration/test_llm_logging.py`). **Dead in production.** Safe to drop with the method.

### 2.10 `db/sender_rules.py` (1 trigger function, plus 41 above)

**58 `reset_skipped_emails_for_sender_rule() → trigger`** (trigger `sender_rules.sender_rule_before_delete`, BEFORE DELETE) — definer, service, PL 68 → 35 Python, **S**.
- Callers: the trigger, fired by every `DELETE FROM sender_rules` (the web client deletes rules directly today, `frontend/src/lib/services/sender-rules.js`; Q1 moves it to an endpoint → `db.sender_rules.delete_rule(user_id, rule_id)`).
- PG: `GET DIAGNOSTICS`, `interval '30 days'`, `LIKE '%@' || domain`, `RAISE LOG`.
- Port: **Python in `delete_rule`, not a SQLite trigger** — it needs `now - 30 days` and a `LIKE` with Postgres case semantics, both easier in Python; the only writer is the new endpoint, enforced by the "no SQL outside `db/`" test. Same order: if no equivalent ignore rule remains, reset `skipped` emails for the sender/domain in the 30-day window (`attempts=0`, clear error/lock) — this fires `emails_notify_pending` so the worker wakes — then delete the rule. `RAISE LOG` → `logger.info`.
- Tests: `test_sender_rule_migrations.py::test_sender_rule_dedupe_installs_guard_before_deleting_duplicates` (greps a migration; rewritten). Add `test_db_sender_rules.py::test_deleting_ignore_rule_requeues_recent_skipped_mail`.

### 2.11 `db/folders` (in `db/email_sync.py`) (1 function)

**59 `set_email_folder_preference(p_folder_id uuid, p_is_included bool) → SETOF email_folders`** — definer, service +auth, PL 20 → 20, **S**.
- Callers: `services/email_folders.py:231` (`set_folder_preference`, user client) ← `api/routes/integrations.py:110`.
- PG: `auth.uid()`, `RETURN QUERY UPDATE … RETURNING *`.
- Port: `set_email_folder_preference(user_id, folder_id, is_included) -> dict | None`, same `WHERE` (`user_id=?`, not system, not permanently excluded, provider in gmail/outlook). The comment at `email_folders.py:228–230` (table UPDATE privilege revoked) becomes "the only writer of `is_included` is this function", pinned by the no-SQL-outside-`db/` test.
- Tests: `test_reliable_email_history.py::test_folder_preference_uses_restricted_rpc_instead_of_table_update` (rewritten: assert the route reaches `db.email_sync.set_email_folder_preference`).

### 2.12 `db/parked.py` — Google Photos and scheduled tasks (4 functions)

| # | Function | Def | Exec | PL | Size | Diff |
|---|---|---|---|---|---|---|
| 60 | `claim_pending_photo(p_worker_id text, p_lock_duration_seconds int=300) → SETOF photos` | yes | service | 27 | — | dead in production |
| 61 | `unlock_expired_photo_locks() → integer` | yes | service | 17 | 12 | S |
| 62 | `claim_next_scheduled_task(p_task_types text[], p_worker_id text, p_lock_duration_seconds int=300) → SETOF scheduled_tasks` | no | PUBLIC+anon+auth | 29 | — | dead in production |
| 63 | `unlock_expired_scheduled_tasks() → integer` | no | PUBLIC | 15 | 12 | S |

- **60** Callers: `services/photos.py:85` (`claim_pending_photo`), which nothing calls; tests `test_photos.py::test_claims_photo_successfully`, `::test_returns_none_when_no_pending`, `::test_custom_lock_duration`, `::test_raises_on_error`. Dead (Google Photos parked, `test_reachability.py:17–21`). Safe to drop with the wrapper and its tests, or port as an 18-line claim if photos are to be un-parked later. Recommendation: drop; the parked feature can port it when revived.
- **61** Callers: `services/photos.py:235` ← `api/app.py:136`. Port: one `UPDATE` (the `WITH … RETURNING` count becomes `rowcount`). Tests: `test_photos.py::test_unlocks_expired_locks`, `::test_returns_zero_when_no_expired_locks`; `integration/test_integration_worker_pool_port.py::test_unlock_expired_helpers_run`. If 60 is dropped, 61 is only startup hygiene for an unused table: fold into §7.3.
- **62** Callers: `services/scheduled_tasks.py:90` (`claim_scheduled_task`), called by no production code (tests `test_scheduled_tasks.py::test_claim_passes_correct_rpc_params`, `integration/test_integration_workers.py`). Uses `(n || ' seconds')::interval`, `= ANY(text[])`. Dead; drop with its wrapper. (It is `PUBLIC`-executable and `SECURITY INVOKER` today: the port also closes that exposure.)
- **63** Callers: `services/scheduled_tasks.py:180` ← `api/app.py:137`. Tests: `test_scheduled_tasks.py::test_unlock_returns_count_when_tasks_unlocked`, `::test_unlock_returns_zero_when_none_expired`, `::test_unlock_handles_null_data`, `::test_unlock_calls_correct_rpc`, `::test_unlock_db_error_raises_scheduled_tasks_error`. Fold into §7.3.

### 2.13 Live hints and work wake-ups (8 functions → `db/bus.py` + SQLite triggers)

| # | Function | Def | Exec | PL | Fired by trigger(s) |
|---|---|---|---|---|---|
| 64 | `broadcast_user_ui_change(p_user_id uuid, p_resource text, p_operation text, p_entity_id uuid) → void` | yes | service | 30 | called by 65–70 |
| 65 | `trg_calendar_work_items_broadcast() → trigger` | yes | service | 9 | `trg_calendar_work_items_broadcast` AFTER INSERT OR DELETE OR UPDATE ON calendar_work_items |
| 66 | `trg_emails_broadcast() → trigger` | yes | service | 9 | `trg_emails_broadcast_upd` AFTER UPDATE OF processing_status, processing_error ON emails |
| 67 | `trg_event_change_proposals_broadcast() → trigger` | yes | service | 9 | `trg_event_change_proposals_broadcast` AFTER INSERT OR DELETE OR UPDATE ON event_change_proposals |
| 68 | `trg_event_sources_broadcast() → trigger` | yes | service | 11 | `trg_event_sources_broadcast_ins` AFTER INSERT; `trg_event_sources_broadcast_upd` AFTER UPDATE OF source_origin ON event_sources |
| 69 | `trg_events_broadcast() → trigger` | yes | service | 15 | `trg_events_broadcast_ins` AFTER INSERT; `trg_events_broadcast_del` AFTER DELETE; `trg_events_broadcast_upd` AFTER UPDATE OF review_status, title, start_datetime, end_datetime ON events |
| 70 | `trg_integrations_broadcast() → trigger` | yes | service | 8 | `trg_integrations_broadcast_upd` AFTER UPDATE OF status ON integrations |
| 71 | `notify_work_available() → trigger` (takes `TG_ARGV[0]`) | yes | service | 5 | `emails_notify_pending` (`'email_pending'`), `items_notify_pending` (`'item_pending'`), `attachments_notify_pending` (`'attachment_pending'`) |

- Callers: triggers only. No Python or frontend code calls 64–71; the web
  app subscribes to the Realtime topic `user:<id>:selko-changes` (Q2 replaces
  it with `/live`).
- PG: `realtime.send(payload, 'invalidate', topic, true)`, a
  transaction-local GUC (`set_config('selko.bc_<user>_<resource>', '1', true)`)
  so each transaction sends at most one hint per user and resource, whatever
  the operation (the first operation wins); `pg_notify('selko_work', <type>)`,
  which Postgres de-duplicates per transaction for identical payloads and
  delivers only on commit.
- Port: one permanent SQLite trigger per Postgres trigger, same events, same
  `UPDATE OF` column lists, the `IS DISTINCT FROM` guards as
  `WHEN NEW.c IS NOT OLD.c OR …`, body `SELECT selko_emit_live(NEW.user_id, 'events', 'UPDATE');`
  (for `event_sources`, `(SELECT user_id FROM events WHERE id = NEW.event_id)`;
  `DELETE` triggers use `OLD.*`; `emails_notify_pending` keeps its
  `WHEN NEW.processing_status = 'pending'`). `Tx` keeps
  `live: dict[(user_id, resource), operation]` (insert-if-absent mirrors the
  GUC guard exactly) and `work: set[str]`; after `COMMIT`, `bus.publish_live`
  sends `{"resource", "operation", "occurred_at": tx.now}` per entry and
  `bus.signal_work` sets each `asyncio.Event` with
  `loop.call_soon_threadsafe` (the commit happens in a worker thread).
  `entity_id` is omitted from the payload as today (`fdefs` 155–156).
- Size: bus 120 lines + 14 trigger definitions (~70 SQL lines in `0001`); **M** (the threading hand-off is the only subtle part).
- Tests: `integration/test_broadcast_fanout.py::test_bulk_update_emits_one_broadcast_per_resource`, `::test_distinct_transactions_emit_distinct_broadcasts`; `integration/test_integration_work_listener.py::TestWorkListener` (`test_notify_sets_the_matching_event`, `test_h3_dead_socket_reconnects_and_still_delivers` — deleted, no socket —, `test_durability_missed_notification_costs_latency_never_work`, `test_batch_collapse_one_notification_per_transaction`, `test_d3_two_listeners_one_notification_one_claim`); `test_pg.py` (13 tests, deleted with `services/pg.py`; `test_listener_sets_event_for_payload`, `test_heartbeat_payload_does_not_set_work_events`, `test_status_is_false_before_start` become `test_db_bus.py` tests).

### 2.14 Generic triggers (2 functions)

**72 `set_updated_at() → trigger`** — invoker, PUBLIC, PL 6. Fired by **7** triggers (verified: `SELECT count(*) FROM pg_trigger WHERE tgfoid = 'public.set_updated_at'::regproc` = 7; the overview's "8 `updated_at`" is off by one): `set_events_updated_at`, `set_global_limits_updated_at`, `set_integrations_updated_at`, `set_sender_rules_updated_at`, `set_usage_quotas_updated_at`, `set_user_calendar_settings_updated_at`, `set_users_updated_at`, all BEFORE UPDATE.
- Port: SQLite cannot assign `NEW` in a `BEFORE` trigger; use `AFTER UPDATE ON t FOR EACH ROW BEGIN UPDATE t SET updated_at = selko_now() WHERE rowid = NEW.rowid; END` with no `WHEN`: Postgres's BEFORE trigger overwrites even an explicit `updated_at` with `now()` (the transaction time), so always writing `selko_now()` (= `tx.now`) matches it exactly. The inner `UPDATE` does not re-fire the trigger (`recursive_triggers` off).
- Hard part: the fence depends on `events.updated_at` being touched by every write; `_enqueue_calendar_work`, `claim_calendar_work_item`, `defer/fail_calendar_work` deliberately `UPDATE events SET updated_at = now()` to move the fingerprint. Kept verbatim.
- Tests: `integration/test_integration_identity_mirror_fence.py`; `integration/test_integration_fenced_event_commit.py`.

**73 `handle_new_user() → trigger`** (trigger `on_auth_user_created` AFTER INSERT ON **auth.users**) — definer, service, PL 7. Inserts `public.users(id, email, display_name = split_part(email,'@',1))`. Port: `db/accounts.create_account` (auth section) inserts `accounts` and `users` in the same `tx`. Not a SQLite trigger. Tests: `integration/test_integration_users.py`, `integration/test_integration_auth.py` (auth section).

### 2.15 All 26 triggers in one table

| Table | Trigger | Timing / events | Function | SQLite replacement |
|---|---|---|---|---|
| attachments | `attachments_notify_pending` | AFTER INSERT OR UPDATE OF ingestion_status, WHEN new = 'pending' | 71 | trigger → `selko_emit_work('attachment_pending')` |
| calendar_work_items | `calendar_work_items_owner_check` | BEFORE INSERT OR UPDATE | 38 | trigger `RAISE(ABORT)` |
| calendar_work_items | `trg_calendar_work_items_broadcast` | AFTER INSERT OR DELETE OR UPDATE | 65 | 3 triggers → `selko_emit_live` |
| email_ingestion_items | `items_notify_pending` | AFTER INSERT OR UPDATE OF acquisition_status, WHEN 'pending' | 71 | trigger → `selko_emit_work('item_pending')` |
| emails | `emails_notify_pending` | AFTER INSERT OR UPDATE OF processing_status, WHEN 'pending' | 71 | trigger → `selko_emit_work('email_pending')` |
| emails | `parse_provider_labels_trigger` | BEFORE INSERT OR UPDATE OF provider_labels | 7 | 2 AFTER triggers updating the row |
| emails | `trg_emails_broadcast_upd` | AFTER UPDATE OF processing_status, processing_error | 66 | trigger with `WHEN … IS NOT …` |
| event_change_proposals | `event_change_proposals_invariant` | CONSTRAINT AFTER INSERT OR DELETE OR UPDATE, DEFERRED | 48 | touched-ids trigger + pre-commit check (§5.5) |
| event_change_proposals | `trg_event_change_proposals_broadcast` | AFTER INSERT OR DELETE OR UPDATE | 67 | 3 triggers |
| event_sources | `trg_event_sources_broadcast_ins` | AFTER INSERT | 68 | trigger |
| event_sources | `trg_event_sources_broadcast_upd` | AFTER UPDATE OF source_origin | 68 | trigger |
| events | `events_change_proposal_invariant` | CONSTRAINT AFTER INSERT OR UPDATE, DEFERRED | 48 | touched-ids trigger + pre-commit check |
| events | `set_events_updated_at` | BEFORE UPDATE | 72 | AFTER UPDATE trigger |
| events | `trg_events_broadcast_del` | AFTER DELETE | 69 | trigger |
| events | `trg_events_broadcast_ins` | AFTER INSERT | 69 | trigger |
| events | `trg_events_broadcast_upd` | AFTER UPDATE OF review_status, title, start_datetime, end_datetime | 69 | trigger with `WHEN` |
| global_limits | `set_global_limits_updated_at` | BEFORE UPDATE | 72 | AFTER UPDATE trigger |
| integrations | `integrations_ensure_email_sync_state` | AFTER INSERT OR UPDATE OF status, provider | 18 | 2 triggers (UPSERT) |
| integrations | `set_integrations_updated_at` | BEFORE UPDATE | 72 | AFTER UPDATE trigger |
| integrations | `trg_integrations_broadcast_upd` | AFTER UPDATE OF status | 70 | trigger with `WHEN` |
| sender_rules | `sender_rule_before_delete` | BEFORE DELETE | 58 | Python in `db.sender_rules.delete_rule` |
| sender_rules | `set_sender_rules_updated_at` | BEFORE UPDATE | 72 | AFTER UPDATE trigger |
| usage_quotas | `set_usage_quotas_updated_at` | BEFORE UPDATE | 72 | AFTER UPDATE trigger |
| user_calendar_settings | `set_user_calendar_settings_updated_at` | BEFORE UPDATE | 72 | AFTER UPDATE trigger |
| users | `set_users_updated_at` | BEFORE UPDATE | 72 | AFTER UPDATE trigger |
| auth.users | `on_auth_user_created` | AFTER INSERT | 73 | Python in `db/accounts.create_account` (auth section) |

---

## 3. Every supabase-py call site outside the RPCs (130 `.table(`)

Each row: file:line · enclosing function · table · operation (with the
PostgREST filters) → replacement in `db/`. Embedded selects
(`select("*, event_sources(*, emails(*))")`) become explicit `JOIN`s that
return the same nested dict shape, built in Python; that is the only
non-mechanical part of this list. `count="exact"` becomes `SELECT count(*)`.
Every replacement takes `user_id` where the row is user-owned.

### 3.1 `api/routes/` (15)

| Site | Function | Table · op | Replacement |
|---|---|---|---|
| `api/routes/emails.py:194` | `process_email` | emails · select id eq id,user_id maybe_single | `db.emails.exists_owned(user_id, email_id)` |
| `api/routes/emails.py:228` | `process_email` | event_sources · select event_id eq email_id | `db.events.event_ids_for_email(user_id, email_id)` |
| `api/routes/emails.py:286` | `batch_process_emails` | emails · select id eq user_id order date_sent limit | `db.emails.list_ids_recent(user_id, limit)` |
| `api/routes/emails.py:334` | `batch_process_emails` | event_sources · select event_id eq email_id | `db.events.event_ids_for_email` |
| `api/routes/events.py:81` | `sync_event` | events · select * eq id maybe_single | `db.events.get(user_id, event_id)` |
| `api/routes/events.py:146` | `sync_event` | events · select * eq id single | `db.events.get` |
| `api/routes/events.py:199` | `unsync_event` | events · select `user_id, review_status, calendar_work_items(status, action, …)` | `db.events.get_with_work_items(user_id, event_id)` (JOIN) |
| `api/routes/events.py:277` | `_get_owned_event` | events · select user_id, review_status | `db.events.get(user_id, event_id)` |
| `api/routes/events.py:295` | `_get_owned_pending_proposal` | event_change_proposals · select eq event_id,status,user_id | `db.proposals.get_pending(user_id, event_id)` |
| `api/routes/health.py:60` | `_pending_email_metrics` | emails · select created_at count=exact eq pending order limit 1 | `db.health.pending_email_metrics()` |
| `api/routes/health.py:120` | `health_db_check` | users · select id limit 1 | `db.health.ping()` (`SELECT 1`) |
| `api/routes/health.py:300` | `health_egress_check` | integrations · select id count=exact in provider eq active | `db.health.count_active_mail_integrations()` |
| `api/routes/integrations.py:73` | `list_email_folders` | email_folders · select cols eq user_id,provider,is_system order full_path | `db.email_sync.list_folders(user_id, provider)` |
| `api/routes/integrations.py:98` | `update_email_folder` | email_folders · select * eq id,user_id,provider,is_system maybe_single | `db.email_sync.get_folder(user_id, folder_id, provider)` |
| `api/routes/integrations.py:400` | `google_oauth_callback` | user_calendar_settings · upsert | `db.integrations.upsert_calendar_settings(user_id, fields)` |

### 3.2 `services/attachments.py` (4) and Storage (3)

| Site | Function | Table · op | Replacement |
|---|---|---|---|
| `services/attachments.py:75` | `check_duplicate_attachment` | attachments · select * eq content_hash limit | `db.attachments.find_by_content_hash(user_id, content_hash)` |
| `services/attachments.py:279` | `save_attachment_metadata` | attachments · insert | `db.attachments.insert(user_id, row)` |
| `services/attachments.py:481` | `delete_attachment` | attachments · select storage_path eq id single | `db.attachments.get(user_id, attachment_id)` |
| `services/attachments.py:505` | `delete_attachment` | attachments · delete eq id | `db.attachments.delete(user_id, attachment_id)` |
| `services/attachments.py:200` | (upload) | **Storage** `from_(bucket).upload(path, data)` | `files.write_attachment(storage_path, data)` — temp file + `os.replace` under `/data/attachments/` |
| `services/attachments.py:497` | `delete_attachment` | **Storage** `.remove([path])` | `files.delete_attachment(storage_path)` (after the row delete commits) |
| `services/event_processing.py:463` | `fetch_email_with_attachments` | **Storage** `from_("attachments").download(path)` | `files.read_attachment(storage_path)` |

The Storage replacement (`selko/files.py`, ~60 lines) is the attachments
section's; this section only fixes the contract: `attachments.storage_path`
stays the path **relative to the attachments directory**, in today's format
`{user_id}/{uuid12}_{filename}` (`attachments.py:196–197`), so the Q7 import
copies objects to the same relative paths and rewrites no rows. (The
overview's `attachments/<user_id>/<attachment_id>` naming would require
rewriting `storage_path` on import; reconcile with the attachments section.)

### 3.3 `services/calendar_mirror.py` (7)

| Site | Function | Table · op | Replacement |
|---|---|---|---|
| `:188` | `sync_calendar` | calendar_mirror_state · select sync_token eq integration_id,calendar_id | `db.mirror.get_state(integration_id, calendar_id)` |
| `:238` | `sync_calendar` | calendar_entries · upsert on_conflict integration_id,calendar_id,provider_event_id | `db.mirror.upsert_entries(user_id, rows)` |
| `:263` | `sync_calendar` | calendar_mirror_state · upsert on_conflict integration_id,calendar_id | `db.mirror.save_state(...)` |
| `:330` | `_write_entry_hints` | event_identity_hints · upsert on_conflict calendar_entry_id,kind,value_hash,recurrence_id | `db.mirror.upsert_entry_hints(user_id, rows)` |
| `:356` | `_reload_stored` | calendar_entries · select eq user_id in provider_event_id | `db.mirror.entries_by_provider_ids(user_id, ids)` |
| `:379` | `_index_unhinted_entries` | calendar_entries · select is deleted_at null, ical_uid not null, limit | `db.mirror.unhinted_entries(user_id, limit)` |
| `:399` | `_index_unhinted_entries` | event_identity_hints · select calendar_entry_id not null | `db.mirror.hinted_entry_ids(user_id)` |

Note: `:238` and `:263` are separate PostgREST calls today (no shared
transaction); a mirror pass that writes entries and then the sync token can
put them in one `tx` (strictly better: a crash between them today re-reads
the page). Mirror writes touch `calendar_entries.updated_at`, which the
commit's hint fingerprint covers — that is the race
`integration/test_integration_identity_mirror_fence.py` pins.

### 3.4 `services/calendars.py` (8)

| Site | Function | Table · op | Replacement |
|---|---|---|---|
| `:238` | `_user_integrations` | integrations · select id,provider,status,scopes eq user_id | `db.integrations.list_for_user(user_id)` |
| `:461` | `get_calendar_settings` | user_calendar_settings · select * eq user_id | `db.integrations.get_calendar_settings(user_id)` |
| `:511` | `get_all_day_policy_and_timezone` | user_calendar_settings · select timezone, all_day_display_mode | same |
| `:597` | `update_calendar_settings` | user_calendar_settings · upsert | `db.integrations.upsert_calendar_settings` |
| `:711` | `_log_sync` | calendar_sync_log · insert | `db.integrations.log_calendar_sync(user_id, row)` |
| `:779` | `sync_event_to_calendar` | events · select * eq id single | `db.events.get(user_id, event_id)` |
| `:935` | `cancel_event_to_calendar` | events · select * eq id single | `db.events.get` |
| `:1096` | `get_latest_sync_snapshot` | calendar_sync_log · select eq event_id in action order synced_at limit | `db.integrations.latest_sync_snapshot(user_id, event_id, actions)` |

### 3.5 `services/email_folders.py` (2)

| `:102` | `upsert_discovered_folders` | email_folders · select * eq integration_id | `db.email_sync.folders_for_integration(integration_id)` |
|---|---|---|---|
| `:212` | `upsert_discovered_folders` | email_folders · upsert on_conflict integration_id,provider_folder_id | `db.email_sync.upsert_folders(integration_id, rows)` |

### 3.6 `services/email_sync_health.py` (11)

| Site | Function | Table · op | Replacement |
|---|---|---|---|
| `:162` | `_dead_letter_integration_ids` (dynamic table: `email_ingestion_items` at `:248`, `attachments` at `:254`) | select cols eq `<status_col>`='dead_letter' range paged | `db.health.dead_letter_integration_ids()` — one `SELECT DISTINCT integration_id` per table; the paging exists only because PostgREST truncates, so it goes |
| `:183` | `evaluate_once` | email_sync_state · select * | `db.email_sync.all_states()` |
| `:204` | `evaluate_once` | integrations · select id,status | `db.integrations.statuses()` |
| `:270` | `evaluate_once` | operational_incidents · select * eq incident_key maybe_single | `db.ops.get_incident(key)` |
| `:273` | `evaluate_once` | operational_incidents · insert | `db.ops.open_incident(row)` |
| `:285`, `:289`, `:300` | `evaluate_once` | operational_incidents · update eq incident_key | `db.ops.update_incident(key, fields)` |
| `:310` | `evaluate_once` | operational_incidents · select * eq status like incident_key | `db.ops.open_incidents(prefix)` |
| `:320`, `:325` | `evaluate_once` | operational_incidents · update eq id | `db.ops.update_incident_by_id(id, fields)` |

The evaluator's `:270→:273` read-then-insert becomes one `tx` (removes a
race that `operational_incidents_incident_key_key` currently catches as a
unique violation).

### 3.7 `services/emails.py` (5)

| `:290` | `save_emails` | emails · upsert on_conflict user_id,email_provider,provider_message_id | **dead**: no caller in `backend/selko` (verified); the v2 path saves through `save_email_with_attachment_descriptors`. Drop |
|---|---|---|---|
| `:411` | `store_gmail_message_attachments` | emails · update eq id | **dead**: no caller in `backend/selko` (verified). Drop |
| `:456` | `fetch_emails_for_user` | integrations · select id,provider eq user_id,status in provider | `db.integrations.active_mail_integrations(user_id)` |
| `:474` | `fetch_emails_for_user` | email_sync_state · update eq integration_id is lease_owner null | `db.email_sync.request_poll(integration_id)` (lease-respecting; same predicate as `request_email_sync_now`) |
| `:625` | `skip_email_processing` | emails · update eq id | **dead**: `skip_email_processing` has no caller (tests neither). Drop |

### 3.8 `services/event_processing.py` (2)

| `:415` | `fetch_email_with_attachments` | emails · select * eq id single | `db.emails.get_for_extraction(email_id)` (worker-scoped, returns None) |
|---|---|---|---|
| `:452` | `fetch_email_with_attachments` | attachments · select * eq email_id | `db.attachments.for_email(email_id)` |

### 3.9 `services/events.py` (36)

| Site | Function | Table · op | Replacement |
|---|---|---|---|
| `:223` | `mark_email_status` | emails · update eq id | `db.emails.mark_status(email_id, fields)` |
| `:255` | `get_user_timezone` | user_calendar_settings · select timezone | `db.integrations.get_calendar_settings` |
| `:399` | `_fetch_baseline_info_date` | event_sources · select `emails(date_sent)` eq event_id | `db.events.source_email_dates(event_id)` (JOIN) |
| `:425` | `_is_from_users_calendar` | event_sources · select id eq event_id,source_origin limit | `db.events.has_source_origin(event_id, origin)` |
| `:453` | `_load_identity_context` | emails · select provider,thread_id,subject,body_text eq id | `db.emails.identity_context(email_id)` |
| `:463` | `_load_identity_context` | email_calendar_components · select … eq email_id order | `db.emails.calendar_components(email_id)` |
| `:490` | `_invite_is_already_on_calendar` | email_calendar_components · select uid_hash | `db.emails.calendar_components` |
| `:510` | `_invite_is_already_on_calendar` | event_identity_hints · select calendar_entry_id eq kind,user_id in value_hash not null limit | `db.mirror.entry_hint_exists(user_id, kind, hashes)` |
| `:1147` | `process_email_for_events` | email_calendar_components · select method eq email_id,method limit | `db.emails.has_component_method(email_id, method)` |
| `:1271` | `process_email_for_events` | event_sources · select source_type eq email_id | `db.events.source_types_for_email(email_id)` |
| `:1327` | `_load_identity_candidates` | event_identity_hints · select … eq user_id,kind,value_hash,recurrence_id | `db.events.hints_matching(user_id, keys)` |
| `:1349` | `_load_identity_candidates` | calendar_entries · select … eq user_id in id is deleted_at null | `db.mirror.entries_by_ids(user_id, ids)` |
| `:1372` | `_load_identity_candidates` | events · select * eq user_id in id | `db.events.get_many(user_id, ids)` |
| `:1409` | `_mirror_candidates_in_window` | calendar_entries · select … gte/lt start_at | `db.mirror.entries_in_window(user_id, start, end)` |
| `:1671` | `find_matching_event` | events · select * gte/lt start_datetime | `db.events.in_window(user_id, start, end)` (the band whose fingerprint the commit re-checks: must return `updated_at` in `codec` form) |
| `:1843` | `find_matching_event` | events · select * eq google_calendar_event_id,user_id order limit | `db.events.by_provider_event_id(user_id, id)` |
| `:1962` | `retire_pending_already_on_calendar` | events · select … eq user_id,review_status gte/lte | `db.events.pending_in_window(user_id, …)` |
| `:2011` | `retire_pending_already_on_calendar` | events · update eq id,user_id,review_status | `db.events.retire_pending(user_id, event_id)` — a compare-and-set (`WHERE review_status='pending_review'`); keep it |
| `:2037` | `_explain_late_match` | event_sources · select email_id eq event_id not null | `db.events.source_email_ids(event_id)` |
| `:2047` | `_explain_late_match` | emails · select id,processing_outcome,processing_result | `db.emails.outcome(email_id)` |
| `:2057` | `_explain_late_match` | emails · update eq id | `db.emails.set_outcome(email_id, fields)` |
| `:2070` | `_latest_pending_change_proposal` | event_change_proposals · select * eq event_id,status | `db.proposals.get_pending(user_id, event_id)` |
| `:2084` | `apply_change_proposal` | events · select * single | `db.events.get` |
| `:2090` | `apply_change_proposal` | event_change_proposals · select * eq event_id,id | `db.proposals.get(user_id, event_id, proposal_id)` |
| `:2157` | `reject_change_proposal` | events · select * single | `db.events.get` |
| `:2163` | `reject_change_proposal` | event_change_proposals · select * | `db.proposals.get` |
| `:2182` | `reject_change_proposal` | event_sources · select id,source_type,source_origin eq event_id | `db.events.sources(event_id)` |
| `:2281` | `undo_history_event` | events · select * single | `db.events.get` |
| `:2287` | `undo_history_event` | event_change_proposals · select * eq event_id,status=applied order resolved_at desc limit 1 | `db.proposals.latest_applied(user_id, event_id)` |
| `:2366` | `get_events_new` | events · select `*, event_sources(*, emails(*))` eq user_id,review_status order | `db.events.list_with_sources(user_id, 'pending_review')` (two queries + Python nesting) |
| `:2377` | `get_events_approved` | events · select * eq user_id,review_status order | `db.events.list(user_id, 'active')` |
| `:2386` | `get_events_updates` | event_sources · select `*, events(*), emails(*)` in source_type order | `db.events.update_sources(user_id, types)` — **note:** no `user_id` filter today (relies on RLS of the calling client); the port must add it |
| `:2405` | `get_event_with_sources` | events · select `*, event_sources(*, emails(*))` eq id single | `db.events.get_with_sources(user_id, event_id)` |
| `:2426` | `check_sender_rules` | sender_rules · select * eq user_id,sender_email | `db.sender_rules.matching(user_id, email, domain)` |
| `:2436` | `check_sender_rules` | sender_rules · select * eq user_id,sender_domain | same |
| `:2459` | `generate_source_attribution` | event_sources · select `*, emails(*)` eq event_id order | `db.events.sources_with_emails(event_id)` |

`services/events.py:2386` is the one site where dropping RLS would leak
across users if ported mechanically (no `user_id` filter; it relied on the
user-scoped client). Verified: `get_events_new`, `get_events_approved`,
`get_events_updates` and `get_event_with_sources` (`:2364–2420`) have **no
caller** in `backend/selko` (the web app reads PostgREST directly). Drop all
four rather than port them; the Q1 endpoints replace them, scoped by
`user_id`.

### 3.10 `services/integrations.py` (12)

| Site | Function | Table · op | Replacement |
|---|---|---|---|
| `:148` | `get_provider_integration` | integrations · select * eq user_id,provider maybe_single | `db.integrations.get(user_id, provider)` |
| `:310` | `get_oauth_credentials` | integrations · select * eq user_id,provider | same |
| `:374` | `update_integration_status` | integrations · update status eq user_id,provider | `db.integrations.set_status(user_id, provider, status)` (fires ensure-sync-state + live hint) |
| `:457` | `update_oauth_credentials` | integrations · update tokens | `db.integrations.update_tokens(user_id, provider, fields)` |
| `:489` | `update_provider_tokens` | integrations · update tokens | same |
| `:600` | `_save_oauth_state` | oauth_states · insert | `db.integrations.save_oauth_state(row)` |
| `:629` | `_validate_and_consume_oauth_state` | oauth_states · select * eq state | `db.integrations.consume_oauth_state(state)` — select + delete in **one** `tx` (today `:629`, `:645`, `:649` are three calls; two concurrent callbacks with the same state could both pass) |
| `:645`, `:649` | `_validate_and_consume_oauth_state` | oauth_states · delete eq state | (inside `consume_oauth_state`) |
| `:674` | `_clean_expired_oauth_states` | oauth_states · delete lt expires_at | `db.integrations.delete_expired_oauth_states(now)` |
| `:910` | `delete_integration` | integrations · delete eq user_id,provider | `db.integrations.delete(user_id, provider)` (foreign keys `ON DELETE CASCADE` must be declared in `0001` exactly as live; `PRAGMA foreign_keys=ON`) |

### 3.11 `services/llm_logging.py`, `services/msgraph.py`, `services/quotas.py` (4)

| `services/llm_logging.py:168` | `log_call` | llm_call_log · insert | `db.ops.log_llm_call(row)` |
|---|---|---|---|
| `services/msgraph.py:108` | `record_graph_failure` | graph_api_failures · insert | `db.ops.record_graph_failure(row)` |
| `services/quotas.py:267` | `set_user_limit` | global_limits · select max_allowed single | `db.quotas.max_allowed(limit_type)` |
| `services/quotas.py:288` | `set_user_limit` | usage_quotas · upsert on_conflict user_id,date | `db.quotas.set_user_limit(user_id, date, fields)` |

### 3.12 `services/photos.py`, `services/scheduled_tasks.py` (9, parked)

| `services/photos.py:47` | `save_photo_metadata` | photos · upsert | `db.parked.upsert_photo` |
|---|---|---|---|
| `services/photos.py:116` | `complete_photo_processing` | photos · update | `db.parked.update_photo` |
| `services/photos.py:150`, `:174` | `fail_photo_processing` | photos · select / update | `db.parked.fail_photo` (one `tx`) |
| `services/photos.py:207` | `get_photo` | photos · select | `db.parked.get_photo` |
| `services/scheduled_tasks.py:56` | `enqueue_scheduled_task` | scheduled_tasks · insert | `db.parked.enqueue_task` |
| `services/scheduled_tasks.py:120` | `complete_scheduled_task` | scheduled_tasks · update | dead (no production caller) — drop |
| `services/scheduled_tasks.py:151` | `fail_scheduled_task` | scheduled_tasks · update | dead — drop |
| `services/scheduled_tasks.py:212` | `cleanup_old_scheduled_tasks` | scheduled_tasks · delete | **dead**: no caller in `backend/selko` (verified). Drop |

### 3.13 `workers/` (15)

| Site | Function | Table · op | Replacement |
|---|---|---|---|
| `workers/email_ingestion.py:306` | `_integration` | integrations · select * eq id single | `db.integrations.get_by_id(integration_id)` |
| `:318` | `_discover_gmail` | email_folders · select provider_folder_id eq integration_id,provider,is_included | `db.email_sync.included_folder_ids(integration_id, provider)` |
| `:329`, `:520` | `_discover_gmail` / `_discover_outlook` | email_sync_state · select folders_refreshed_at | `db.email_sync.folders_refreshed_at(integration_id)` |
| `:359`, `:541` | same | email_sync_state · update | `db.email_sync.mark_folders_refreshed(integration_id)` |
| `:545` | `_discover_outlook` | email_folders · select * eq integration_id,provider | `db.email_sync.folders_for_integration` |
| `:638` | `_discover_outlook` | email_folders · delete eq id | `db.email_sync.delete_folder(integration_id, folder_id)` |
| `:891` | `acquire_attachment` | emails · select user_id,email_provider,provider_message_id,integration_id single | `db.emails.acquisition_context(email_id)` |
| `:930` | `acquire_attachment` | attachments · update eq id,locked_by | `db.attachments.store_result(attachment_id, worker_id, fields)` (fenced on `locked_by`, as today) |
| `workers/email_process.py:125` | `process_email_process_job` | emails · select * eq id single | `db.emails.get_for_extraction` |
| `workers/ingestion_runtime.py:215` | `_calendar_mirror_floor` | integrations · select id,user_id,provider,scopes eq status in provider | `db.integrations.active_calendar_integrations()` |
| `workers/photo_fetch.py:47`, `:97`, `:137`, `:148` | photo fetch (parked) | integrations select/update; scheduled_tasks select | `db.parked.*` |

### 3.14 Auth calls (reference only — the auth section owns them)

| Site | Call | Replaced by |
|---|---|---|
| `api/deps.py:80` | `client.auth.get_user(token)` | JWT verification against the server secret (`auth` section, `GET /auth/user`) |
| `services/auth.py:47` | `client.auth.sign_in_with_password` | `db.accounts.verify_password` + token issue (`POST /auth/token`) |
| `services/users.py:71` | `auth.admin.create_user` | `db.accounts.create_account` (also does `handle_new_user`'s insert) |
| `services/users.py:108` | `auth.admin.list_users` | `db.accounts.list` |
| `services/users.py:133` | `auth.admin.delete_user` | `db.accounts.delete` (cascades through `users`) |
| `services/users.py:156` | `auth.admin.get_user_by_id` | `db.accounts.get` |

`services/auth.py:get_service_client` and the user-scoped client from
`api/deps.py:get_authenticated_client` disappear; every function that
receives a `Client` today receives `db` (and the caller's `user_id`)
instead. The egress meter's `supabase` destination
(`services/egress.py`, hooked on the shared service client) goes with them;
the `/health/egress` `transport` field changes from `"asyncpg"` to
`"sqlite"`, and `scripts/assert-health.sh:105` must change in the same PR.

---

## 4. Every asyncpg call site (37) and what replaces it

All become `await db.run(<db function>, …)`. "Inline" = SQL written in the
service, not a database function.

| Site | SQL | Replacement |
|---|---|---|
| `services/emails.py:511` | `SELECT * FROM public.claim_unprocessed_email($1,$2)` | `db.emails.claim_unprocessed_email` |
| `services/emails.py:539` | inline `UPDATE emails SET processing_status='processed', … WHERE id=$1` (`complete_email_processing`; no production caller, tests only) | `db.emails.complete_email_processing` or drop with its tests (`test_reliable_email_history.py`, `integration/test_integration_workers.py`, `integration/test_integration_worker_pool_port.py`, `test_workers.py`) |
| `services/emails.py:585` | `SELECT public.fail_email_processing($1..$7)` | `db.emails.fail_email_processing` |
| `services/emails.py:652` | `SELECT public.unlock_expired_email_locks()` | `db.emails.unlock_expired_email_locks` |
| `services/events.py:2510` | `SELECT * FROM public.claim_calendar_work_item($1,$2,$3)` | `db.calendar_work.claim_calendar_work_item` |
| `services/events.py:2520` | inline `SELECT * FROM public.events WHERE id=$1` | returned by the claim itself (`claim_calendar_work_item` returns `(item, event)` read in the same `tx`; removes a second round trip and a window in which the event could change) |
| `services/events.py:2572` | inline `SELECT * FROM calendar_work_items WHERE id=$1 AND status='processing' AND locked_by=$2 AND generation=$3` (`_resolve_calendar_work_item`) | `db.calendar_work.get_leased_item`; the fenced functions re-check anyway, so this pre-read can go: keep it for the "stale completion" log line only |
| `services/events.py:2594`, `:2618` | `SELECT public.complete_calendar_work($1..$5)` | `db.calendar_work.complete_calendar_work` |
| `services/events.py:2646` | `SELECT public.defer_calendar_work($1..$5)` | `db.calendar_work.defer_calendar_work` |
| `services/events.py:2679`, `:2718` | `SELECT public.fail_calendar_work($1..$6)` | `db.calendar_work.fail_calendar_work` |
| `services/events.py:2752` | inline `SELECT count(*) FROM calendar_work_items WHERE status='processing' AND locked_until < now()` | `db.calendar_work.count_expired_leases` (or §7.3) |
| `services/calendars.py:182` | `SELECT public.requeue_calendar_recovery_batch($1,$2,$3)` | `db.recovery.requeue_calendar_recovery_batch` |
| `services/calendars.py:205` | `SELECT public.refresh_waiting_calendar_recoveries($1)` | `db.recovery.refresh_waiting_calendar_recoveries` |
| `services/integrations.py:401` | `SELECT * FROM public.claim_integration_recovery($1,$2)` | `db.recovery.claim_integration_recovery` |
| `services/integrations.py:424` | `SELECT public.unlock_expired_integration_recoveries()` | `db.recovery.unlock_expired_integration_recoveries` |
| `services/photos.py:235` | `SELECT public.unlock_expired_photo_locks()` | `db.parked.unlock_expired_photo_locks` / §7.3 |
| `services/scheduled_tasks.py:180` | `SELECT public.unlock_expired_scheduled_tasks()` | `db.parked.unlock_expired_scheduled_tasks` / §7.3 |
| `services/email_ingestion.py:282` | `claim_due_email_sync` | `db.email_sync.claim_due_email_sync` |
| `:292` | `claim_due_email_reconciliation` | `db.email_sync.claim_due_email_reconciliation` |
| `:302` | `heartbeat_email_sync` | `db.email_sync.heartbeat_email_sync` |
| `:316` | `complete_email_sync` | `db.email_sync.complete_email_sync` |
| `:328` | `fail_email_sync` | `db.email_sync.fail_email_sync` |
| `:354` | `upsert_discovered_email_items` | `db.email_sync.upsert_discovered_email_items` |
| `:375` | inline `SELECT provider_message_id FROM email_ingestion_items WHERE integration_id=$1 AND provider_message_id = ANY($2::text[])` (chunked by `KNOWN_ID_QUERY_CHUNK`) | `db.email_sync.known_provider_message_ids` — `IN (SELECT value FROM json_each(?))`; chunking kept (SQLite has no parameter-count issue with one JSON parameter, but the chunk bounds memory) |
| `:396` | `claim_email_ingestion_item` | `db.email_sync.claim_email_ingestion_item` |
| `:410` | `complete_email_ingestion_item` | `db.email_sync.complete_email_ingestion_item` |
| `:434` | `save_email_with_attachment_descriptors` | `db.emails.save_email_with_attachment_descriptors` |
| `:460` | `fail_email_ingestion_item` | `db.email_sync.fail_email_ingestion_item` |
| `:472` | inline `UPDATE email_ingestion_items SET acquisition_status='removed', … WHERE id=$1 AND lease_owner=$2 RETURNING id` (`remove_item`) | `db.email_sync.remove_ingestion_item` |
| `:491` | `claim_email_attachment` | `db.attachments.claim_email_attachment` |
| `:505` | `finish_email_attachment` | `db.attachments.finish_email_attachment` |
| `:526` | inline `SELECT id FROM attachments WHERE email_id=$1 AND provider_attachment_id=$2` (`ensure_attachment_descriptors`) | `db.attachments.ensure_descriptors(email_id, user_id, descriptors)` — the per-descriptor select-then-insert loop becomes one `tx` with `INSERT … ON CONFLICT DO NOTHING` (today it is not atomic; same result) |
| `:533` | inline `INSERT INTO attachments (…) VALUES (…, 'pending')` | (inside `ensure_descriptors`) |
| `:551` | inline `SELECT ingestion_status FROM attachments WHERE email_id=$1` (`attachment_readiness`) | `db.attachments.readiness(email_id)` |
| `api/routes/health.py:267` | `SELECT 1` (`_pg_transport_state`) | `db.health.ping()`; reports `"sqlite"` |
| `services/pg.py:229` | `SELECT pg_notify($1,$2)` (listener heartbeat) | gone (§7) |
| `services/pg.py:207` | `add_listener('selko_work', …)` | gone (§7) |

`services/pg.py` (`create_pool`, `assert_session_mode_url`,
`_enable_tcp_keepalives`, `_normalize_pg_row`, `WorkListener`) is deleted
whole; `config.py`'s `supabase_db_url`, `pg_pool_*`, `pg_keepalive_seconds`,
`pg_command_timeout_seconds`, `pg_connect_timeout_seconds`,
`pg_listener_heartbeat_seconds` (`config.py:159, 591`) go with it, replaced by
`database_path` (default `/data/selko.db`) and `attachments_dir`.

---

## 5. The genuinely hard items

### 5.1 Claims that compute a per-row SQL function (`claim_calendar_work_item`, `requeue_calendar_recovery_batch`)

Postgres evaluates `calendar_write_provider()` (three table lookups) for each
candidate row inside the claim's `WHERE`, under `SKIP LOCKED`. SQLite could
call a Python UDF per row, but a UDF that queries the database from inside a
statement on the same connection is re-entrant and fragile. The port reads a
bounded batch with the joins it needs, routes in Python with the existing
twins, and loops until it finds a claimable row or the queue is exhausted.
Identical results; different cost profile (fine at Selko's size: the queue is
tens of rows). Must keep: the pending pass before the expired-processing
pass, `created_at` / `locked_until` ordering, and the provider filter from
the circuit breaker.

### 5.2 `save_email_with_attachment_descriptors`' dynamic column set

The function updates exactly the keys the caller supplied, so a re-acquired
email without a body does not erase the stored body. The Python version must
build the column list from a whitelist and the payload's keys — never from
the payload alone — and coerce types that `jsonb_populate_record` coerced
implicitly (`date_sent`, three `text[]` columns, `has_attachments`,
`is_calendar_invite`). The pinned behaviours are
`test_re_acquired_email_keeps_existing_attachment_rows_unreset` and
`test_calendar_components_survive_empty_resave`.

### 5.3 Timestamps as text

Everything that compares time in SQL (`locked_until < :now`,
`next_poll_at <= :now`, `ORDER BY date_sent`, `start_datetime >= :start`)
depends on one fixed-width UTC format. The rule: **no timestamp is ever
formatted in SQL**; Python formats every value through `codec.ts`, and the
three UDFs (`selko_now`, `selko_ts_minus`, `selko_uuid`) are the only way
triggers obtain a time or an id. A `CHECK (col GLOB '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9][0-9][0-9][0-9]Z')`
on every timestamp column (schema section) makes a malformed write fail
instead of silently mis-sorting.

### 5.4 The commit fence

`commit_email_extraction` rejects a decision when the events in its window
(or the rows its identity hints name) changed since the decision was
computed. With one writer, interleaving inside the commit is impossible, but
the race the fence exists for — the LLM call happens *outside* the
transaction, and a calendar-mirror pass or another email's commit can change
the band meanwhile — is unchanged. Keep both fingerprints, computed by the
same Python functions on both sides, over `updated_at` values that are
strictly increasing per transaction (`tx.now`, §1.1). Every write that should
move the fingerprint already sets `events.updated_at` explicitly; the
`set_updated_at` replacement covers the rest.

### 5.5 Deferred invariants (`enforce_event_change_proposal_invariant`)

Postgres checks at commit that every *pending* proposal's event is `active`
and owned consistently. Callers rely on the deferral:
`reopen_event_change_proposal` sets the proposal `pending` before the event
`active`. SQLite has no deferred triggers. Replacement:

- `TEMP` table `_touched_events(event_id TEXT PRIMARY KEY)` on the writer
  connection (temp schema, so it is per-connection and transactional);
- permanent triggers on `events` (AFTER INSERT/UPDATE) and
  `event_change_proposals` (AFTER INSERT/UPDATE/DELETE) call a fourth UDF
  `selko_touch_event(id)` that adds the id to `Tx.touched_events` (a Python
  set; simpler than the temp table and verified to work from triggers in this
  session's probe);
- `Tx.__exit__`, before `COMMIT`, runs the invariant's two `EXISTS` queries
  for the touched ids and raises `InvariantViolation` (rolling back) on a hit,
  with the Postgres messages.

The check is the same as Postgres's, at the same moment (commit). It cannot
be bypassed by a writer outside `db/` because no such writer exists (the
no-SQL-outside-`db/` test). Pinned by
`test_pending_proposal_requires_active_review_status`.

### 5.6 `ignore_sender_and_reject_pending`

Broken today (§0.1). Porting "the same contract" is impossible because the
current contract is "raise". The port implements the evident intent (reject
New-lane events from the sender, discard their pending changes restoring the
snapshot, record the ignore rule, all in one transaction) and adds the first
tests. Before Q6 lands, the same fix can ship to today's Postgres as a
13-argument call executed through a `SECURITY DEFINER` wrapper — recommended
as a separate small increment, because users hit it now.

### 5.7 `LIKE` case sensitivity and `NULLS FIRST/LAST`

Postgres `LIKE` is case-sensitive, SQLite's is not (ASCII). Postgres sorts
NULLs last ascending, SQLite first. Every port of a `LIKE` (`ignore_sender…`,
`reset_skipped…`, `health_work_state`) and every `ORDER BY` over a nullable
column (`claim_unprocessed_email`'s `date_sent`, both sync claims'
`last_success_at`/`last_reconciled_at`) is written explicitly
(`substr(...) = '@' || ?`; `col IS NULL, col`). A `test_db_sql_hygiene.py`
greps `db/` for bare `LIKE` and for `ORDER BY` columns listed as nullable in
`0001` without an explicit null term.

---

## 6. Safe to drop (not ported)

| Function | Why safe | Also delete |
|---|---|---|
| `claim_calendar_work` | no caller; a test asserts it is unused | the assertion in `test_workers.py::test_worker_pool_claims_over_the_pool` |
| `heartbeat_calendar_work` | no caller anywhere | — |
| `unlock_expired_event_locks` (SQL) | the Python namesake never calls it | — |
| `reconcile_outlook_email_folders` | no caller; `workers/email_ingestion.py:638` deletes folders itself | — |
| `claim_pending_photo` | wrapper has no caller; feature parked | `services/photos.py:63–100`, `test_photos.py` claim tests |
| `claim_next_scheduled_task` | wrapper `claim_scheduled_task` has no caller | `services/scheduled_tasks.py:66–106, 109–162`, their tests |
| `get_user_quota_usage` | `QuotaService.get_usage` has no caller | method + `test_quota_service.py`/`test_rate_limiting.py`/`test_security.py` usage tests |
| `get_llm_usage_summary` | `get_user_usage_summary` has no caller | method + `integration/test_llm_logging.py` summary test |
| `handle_new_user` | replaced by `create_account` (auth section) | — |
| `broadcast_user_ui_change`, `trg_*_broadcast` (6), `notify_work_available` | replaced by bus + triggers | — |

Decide with the owner (operator tooling, not product): the repair tool
`scripts/repair_review_queue_integrity.py` drives `queue_event_cancellation`,
`resolve_event_change_proposal` and `event_change_proposal_hash` over asyncpg
against production Postgres through `ops.yml`. After cutover it needs a
SQLite port (≈ 80 lines of `db/` plus rewriting the script to run inside the
image on the server, since production data never leaves the server) or
retirement. This plan ports the three functions (they are small and keep the
documented recovery path) and leaves the script rewrite to the Q7/Q8 section.
`scripts/seed_screenshot_data.py` (`call_rpc` at `:113, 397, 410, 420, 431, 461`)
must switch to `db/` calls in Q6, or `capture-all-screenshots.sh web` breaks.

---

## 7. LISTEN/NOTIFY, leases, and startup

### 7.1 What exists today

- `services/pg.py:141–309` `WorkListener`: a dedicated asyncpg connection
  `LISTEN selko_work`; `_on_notify` sets one `asyncio.Event` per payload
  (`email_pending`, `event_approved`, `item_pending`, `attachment_pending`);
  a heartbeat self-`NOTIFY` every `pg_listener_heartbeat_seconds` (120) with
  a 10 s receipt deadline; reconnect with 1→60 s backoff that sets every
  event on reconnect (a dropped socket may have lost notifications).
- Started in `api/app.py:120–122` (and `worker_app.py:32–33`), passed to
  `WorkerPool` (`app.py:124–129`, waits at `workers/pool.py:260–275` on
  `event_approved` and `email_pending`) and `IngestionRuntime`
  (`app.py:151–153` → `workers/email_ingestion.py:1035–1052`, waits on
  `item_pending`/`attachment_pending`).
- `/health/ingestion` publishes `listener=work_listener.status()`
  (`api/routes/health.py:193–196`); `scripts/assert-health.sh:98` requires
  `.listener.connected == true`.

### 7.2 What replaces it

`db/bus.py`:

```python
class WorkSignals:            # drop-in for WorkListener's consumer API
    WORK_TYPES = ("email_pending", "event_approved", "item_pending", "attachment_pending")
    def event_for(self, work_type) -> asyncio.Event
    def signal(self, work_type)          # thread-safe: loop.call_soon_threadsafe(ev.set)
    def status(self) -> dict             # {"connected": True, "reconnects": 0, "last_notification_at": t}
    async def start(self) / stop(self)   # bind the running loop; no I/O
```

- `Tx` calls `signals.signal(t)` for each buffered work type **after
  commit**, so a worker never wakes to a row it cannot yet see (the property
  `pg_notify`'s commit-time delivery gave).
- `WorkerPool`, `IngestionRuntime`, `EmailIngestionWorker` keep their
  `work_listener=` parameter (renamed `work_signals=` in the same PR) and
  their `event_for(...).wait()` / `.clear()` code unchanged. The safety poll
  stays the floor (CLAUDE.md "work arrives by notification").
- `status()` keeps the `connected` key so `assert-health.sh` keeps passing;
  `connected` is true once `start()` bound the loop. Whether to keep a field
  that can no longer be false is the observability question "never trust a
  signal that cannot fail": recommend replacing the `listener` block with
  `{"kind": "in_process", "signals_sent": n, "last_signal_at": t}` and
  changing `assert-health.sh:98` to assert `signals_sent` is present, in the
  same PR.
- Optional (not parity): emit `event_approved` from `_enqueue_calendar_work`
  so calendar work no longer depends on the routes' `nudge()` calls
  (`api/routes/events.py:139, 246, 328`) and the safety poll (§0.3).
- Deleted tests: `test_pg.py` (13), `integration/test_integration_work_listener.py::test_h3_dead_socket_reconnects_and_still_delivers`. Ported: the other four work-listener tests and the two fan-out tests, against the bus.

### 7.3 Lease and fencing columns that stay, and the startup reset

Kept exactly, because in-process asyncio tasks and executor threads still
overlap (a calendar write that outlives its lease is reclaimed by another
executor task; the zombie's completion must be refused):

| Table | Lease / fence columns |
|---|---|
| `emails` | `locked_by`, `locked_until`, `lock_generation`, `attempts`, `max_attempts`, `next_retry_at`, `dead_letter_reason`, `dead_letter_at` |
| `calendar_work_items` | `locked_by`, `locked_until`, `generation`, `attempts`, `max_attempts`, `next_retry_at`, `provider` |
| `email_sync_state` | `lease_owner`, `lease_generation`, `lease_expires_at` |
| `email_sync_runs` | `lease_generation`, `status` (partial unique `one_running_per_integration`) |
| `email_ingestion_items` | `lease_owner`, `lease_expires_at`, `attempts`, `max_attempts`, `next_retry_at` |
| `attachments` | `locked_by`, `locked_until`, `attempts`, `max_attempts`, `next_retry_at` |
| `integration_recoveries` | `locked_by`, `locked_until`, `attempts`, `max_attempts`, `next_retry_at` |
| `photos`, `scheduled_tasks` (parked) | `locked_by`, `locked_until` |

The CHECK `emails_pending_is_claimable_check` stays in `0001`.

**`db/startup.reset_leases_at_startup(db)`**, one `tx`, called from the
lifespan **before** `WorkerPool.start()` and `IngestionRuntime.start()`
(fixes §0.4). One process means any lease present at startup belongs to a
dead run:

1. `emails`: `processing` → `pending` (`attempts < max_attempts`) or `failed`
   with `lease_expired_at_limit` — i.e. `unlock_expired_email_locks` with
   `locked_until < :now` replaced by "any lease";
2. `calendar_work_items`: `processing` → `pending`, clear `locked_by/locked_until` (attempts unchanged, as claim-time recovery does);
3. `email_ingestion_items`: `processing` → `retry` with `lease_expires_at = NULL`;
4. `attachments`: `processing` → `retry`, clear lock;
5. `integration_recoveries`: `processing` → `pending`;
6. `email_sync_state`: `lease_owner = NULL, lease_expires_at = NULL`; `email_sync_runs` `running` → `abandoned` (otherwise `health_work_state.stale_sync_runs` reports degraded until the next claim);
7. `photos`, `scheduled_tasks`: `processing` → `pending`.

Generations are **not** reset (a zombie from the previous run cannot exist,
but monotonic generations cost nothing and keep every fence test valid).
Returns per-table counts for the startup log line (`app.py:140–149`).
Tests: `test_ingestion_runtime.py::test_lifespan_runs_ingestion_in_process`,
`::test_lifespan_recovers_stale_integration_recoveries_on_startup` (assert
the reset runs before the tasks start), plus a new
`test_db_startup.py::test_every_lease_is_released`.

---

## 8. Ordered work breakdown for `backend/selko/db/`

Each step merges on its own, behind the old code, with its gate green: the
new `db/` module is imported by its tests and by
`backend/tests/test_reachability.py` (a module only tests import fails that
test, so each step also wires one caller or is added to its allowlist for
the duration of Q6 only). The integration fixture changes once, in step 0:
`backend/tests/integration/conftest.py` gains `sqlite_db` (a temp file with
`0001_initial.sql` applied, the UDFs registered, torn down after the test),
alongside the existing `pg_pool`/`admin_client` until step 10.

| Step | Build | Gate (must pass) |
|---|---|---|
| 0 | `db/connection.py`, `codec.py`, `errors.py`, `bus.py` (no consumers yet), `migrations/0001_initial.sql` + runner (schema section), UDFs, `Tx` with outbox, touched-events check | new `test_db_connection.py` (writes serialize across threads; `tx.now` monotonic; buffers dropped on rollback; trigger without UDF fails; `DbBusy` on lock timeout), new `test_db_codec.py` (round trips; fixed-width ordering), `test_schema_contract.py::test_check_constraint_domains_are_pinned` and `::test_live_triggers_for_every_triggered_table` re-pointed at SQLite |
| 1 | generic triggers (72, 7, 38, 18, live/work triggers) in `0001`; `db/startup.py` | `test_db_bus.py` (ported `test_pg.py` listener tests), `integration/test_broadcast_fanout.py` on SQLite, `integration/test_integration_work_listener.py` (4 surviving tests) on SQLite, `test_outlook_calendar.py` |
| 2 | `db/emails.py` (1–6) | `integration/test_integration_email_state_machine.py` (email half), `test_reliability.py`, `integration/test_integration_workers.py` (email tests), `integration/test_integration_worker_pool_port.py::test_email_claim_complete_roundtrip`, `::test_unlock_expired_helpers_run`, `test_api_routes.py` (reprocess) |
| 3 | `db/email_sync.py` (8–18, 59), `db/attachments.py` (20–21) | `integration/test_integration_email_ingestion_v2.py`, `integration/test_integration_ingestion_drill.py`, `integration/test_integration_calendar_components.py`, `integration/test_integration_ingestion_stall_signal.py`, `integration/test_integration_graph_ledger.py`, `integration/test_integration_email_state_machine.py` (sync half), `test_email_ingestion_v2.py`, `test_acquisition_executor_bound.py`, `test_attachment_type_rejected.py`, `test_reliable_email_history.py` |
| 4 | `db/calendar_work.py` (22–24, 26–28, 31–38) | `integration/test_integration_calendar_work_items.py`, `integration/test_integration_workers.py` (calendar), `integration/test_integration_automatic_cancellation.py`, `integration/test_integration_outlook_calendar.py`, `test_state_ownership_s5.py`, `test_workers.py`, `test_reliability.py` (calendar) |
| 5 | `db/proposals.py` (42–48), `db/events.py` (39–41), `db/sender_rules.py` (58) | `integration/test_integration_fenced_event_commit.py`, `integration/test_integration_extraction_intent.py`, `integration/test_integration_event_identity.py`, `integration/test_integration_identity_mirror_fence.py`, `integration/test_integration_hint_upsert.py`, `integration/test_integration_event_change_proposals.py`, `integration/test_integration_events.py`, `integration/test_integration_late_calendar_match.py`, `test_schema_contract.py::test_pending_proposal_requires_active_review_status`, `::test_reject_event_change_proposal_is_one_atomic_transition` (both moved), `unit/test_undo_history_event.py`, `test_events_refactor.py`, `test_events.py`, `test_fenced_event_commit.py`, `test_extraction_decision_intent.py`, `test_declined_event_terminality.py`, `test_selko_managed_updates.py`, `test_calendar_policy.py`, new `test_db_sender_rules.py` (incl. the case broken today) |
| 6 | `db/recovery.py` (49–53) | `integration/test_integration_recovery.py`, `integration/test_integration_calendar_recovery_worker.py`, `integration/test_integration_worker_pool_port.py::test_calendar_recovery_claim_and_refresh_run`, `test_integrations.py`, `test_calendars.py` |
| 7 | `db/health.py` (54), `db/quotas.py` (55) | `test_ingestion_runtime.py`, `test_api_routes.py` (health), `test_health_endpoints.py`, `integration/test_integration_api.py::test_health_check`, `integration/test_rate_limiting.py::test_quota_rpc_check_and_increment`, `unit/test_quota_service.py` |
| 8 | non-RPC table functions (§3): `db/mirror.py`, `db/integrations.py`, `db/ops.py`, `db/parked.py`, remaining reads in `db/events.py`/`db/emails.py`; services switched module by module (§3 order) | `test_calendar_mirror.py`, `integration/test_integration_calendars.py`, `integration/test_integration_oauth.py`, `integration/test_integration_attachments.py`, `integration/test_integration_emails.py`, `integration/test_integration_event_processing.py`, `integration/test_llm_logging.py`, `test_photos.py`, `test_scheduled_tasks.py`, `test_gmail.py`, `test_outlook.py`, `test_emails.py`, `test_attachments.py` |
| 9 | lifespan switch: `api/app.py` builds `Database`, runs migrations and `reset_leases_at_startup`, then `WorkSignals`, `WorkerPool`, `IngestionRuntime`; `worker_app.py` deleted (staging drills end with hosted staging); `/health` transport `sqlite`; `assert-health.sh` updated | `test_ingestion_runtime.py::test_lifespan_*`, `test_api_routes.py`, `test_health_endpoints.py`, `integration/test_integration_e2e.py`, `test_reachability.py` |
| 10 | delete `services/pg.py`, `services/auth.py:get_service_client`, every `Client` parameter, `supabase` and `asyncpg` from `pyproject.toml`; integration conftest loses `pg_pool`/`admin_client`; RLS/grant tests deleted (`integration/test_integration_rls_security.py`, `test_integration_data_api_grants.py`, `test_integration_grant_posture.py`, `test_schema_contract.py::test_every_public_table_has_rls_enabled`, `::test_security_definer_functions_are_not_executable_by_api_roles`, `::test_default_function_privileges_do_not_grant_api_roles`, `::test_every_security_definer_function_has_a_contract`, `::test_frontend_select_columns_exist_in_the_live_schema`), replaced by Q3's cross-user test; `test_workers.py::test_no_worker_module_retains_a_postgrest_fallback` replaced by `test_no_supabase_or_asyncpg_importable_from_selko` and `test_no_sql_outside_db` (AST: no `execute(` on a sqlite connection outside `selko/db/`) | the full backend suite on SQLite; `./scripts/verify.sh backend` without Docker |

Effort, from the sizes above: ≈ 4,600 lines of new `db/` code, ≈ 1,500
lines of service changes (130 table sites, 37 asyncpg sites, 19 RPC sites,
the exception clauses), and the test fixture move. Steps 0–1 (foundation) and
5 (the extraction commit and proposals) carry most of the risk.

---

## 9. Facts for the memory/notes file

- `ignore_sender_and_reject_pending` calls `reject_event_change_proposal`
  with 14 args against a 13-arg signature, and its invoker role lacks
  EXECUTE: broken in production when the sender has a pending change
  (measured 2026-11-25, `to_regprocedure`, `has_function_privilege`).
- No database trigger emits `event_approved`; calendar work wakes by
  `WorkerPool.nudge()` and the safety poll.
- `api/app.py` starts the worker pool before the startup lease unlocks.
- Eight database functions have no production caller (§0.2, §6).
- Live `.table(` call sites: 130, not 141 (after the 2026-11-25 removals).
