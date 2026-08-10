# Direct-PG Completion and Live-UI Hardening

**Status:** planned — remediation of PRs #262–#278 (Aug 6–9 batch)

**Supersedes the "Status: implemented" line of**
[`direct-postgres-work-transport.md`](direct-postgres-work-transport.md). That
line is wrong. Increments 3, 4 and 5 of that spec shipped as unreachable code.
This document finishes them, removes the dead code the batch left behind, and
repairs the defects found in the same review.

**There are no open questions in this document.** Every step names the file, the
line, the exact code, the exact test, and the exact command. If you hit
something undecided while implementing, that is a defect in this spec — stop and
fix the spec first.

**Platform constraints are unchanged** and are not revisited here: Supabase Free
(5 GB egress), Render Hobby (5 GB bandwidth), session pooler port 5432,
`numInstances: 1`. All platform research in
[`direct-postgres-work-transport.md`](direct-postgres-work-transport.md) §4
remains valid — read §4 before starting increment C1.

---

## 1. What is actually running today

Do not trust the prose in the older specs. This is the verified state as of
`78d06bb2`.

| Claimed | Actual |
|---|---|
| Inc3 — asyncpg session pool in use | `asyncpg` is not a declared dependency. `import asyncpg` raises `ImportError`, which `app.py:116` catches and downgrades to a warning. `pg_pool` is always `None`. |
| Inc4 — claim/complete/heartbeat over the pool | The seven `*_via_pool` methods in `services/email_ingestion.py:426-454` have **zero callers**. `pg_pool` is never passed to `WorkerPool`, `IngestionRuntime`, or `EmailIngestionRepository`. |
| Inc5 — NOTIFY triggers + WorkListener | Triggers exist and fire. `WorkListener.start()` is a stub that sets `_connected = True` and returns. The class is never instantiated. Nothing has ever issued `LISTEN`. |
| Inc2 — 1 claim loop + N semaphore executors | The loop collapse happened. **No semaphore was added.** Acquisition and attachment are now strictly serial. |

The measured egress improvement (929 → 96 MB/day) came entirely from increments
0–2. Every worker database call still crosses PostgREST at ~1,690 bytes, so the
373 MB/mailbox/month curve in
[`direct-postgres-work-transport.md`](direct-postgres-work-transport.md) §1.3 is
**unchanged**. At that rate twelve mailboxes exhaust both 5 GB allowances. This
work is what moves that curve.

### 1.1 Dead code and dead config the batch left behind

Everything in this table is unreachable, unread, or a duplicate. Increment C5
deletes all of it.

| Item | Where | Why it is dead |
|---|---|---|
| `self.pg_pool = pg_pool` (twice) | `workers/pool.py:98-99` | duplicated line |
| `_idle_backoff` | `workers/pool.py:292` | "retained for compat"; the scheduler no longer calls it |
| `_worker_loop` | `workers/pool.py:289` | legacy alias that delegates to `_scheduler_loop` |
| `_process_photo` | `workers/pool.py:564` | photo polling deleted in egress inc 1; unreachable |
| `_process_scheduled_task` | `workers/pool.py:473` | same; no caller anywhere |
| `num_workers` | `workers/pool.py:81,95` | stored and never read |
| `worker_pool_size` | `config.py:83` | "deprecated alias", only feeds the unread `num_workers` |
| `worker_calendar_sync_concurrency` | `config.py:84` | read nowhere; calendar sync is serial |
| `email_acquisition_concurrency`, `email_attachment_concurrency` | `config.py:125-126` | read nowhere since Inc2 removed the pollers without adding executors |
| `_on_notify` loop with `pass` body | `services/pg.py:137-140` | no-op |
| `if 'pg_pool' in locals()` + `except Exception: pass` | `api/app.py:178-182` | `pg_pool` is assigned unconditionally in that branch |
| duplicate `NEW.status IS DISTINCT FROM OLD.status` | `20260809000003` trigger | tested twice |
| stale module docstring | `workers/pool.py:1-13` | says `_process_email` is "retained for hardening inc 8 cleanup only"; it is the live LLM path |

---

## 2. Rules that apply to every increment

1. Source code → worktree + feature branch + PR, per `CLAUDE.md`. Branch names
   are given per increment.
2. Run `uv run pytest backend/tests/ -m "not integration"` before every PR.
   It must stay green.
3. Every increment adds a test that **fails before the change and passes after**.
   Write the test first and watch it fail. If it passes before your change, the
   test is wrong.
4. **One implementation per operation. There are no fallbacks.** If you find
   yourself writing `if pool is not None: ... else: ...`, stop — you are
   building the thing this spec exists to delete. A worker operation runs over
   asyncpg or it does not exist.
5. **Delete, do not deprecate.** No "kept for compat" helpers, no aliases, no
   `# retained for` comments. If a test breaks because you deleted dead code,
   fix the test — the test was pinning the corpse.
6. Never mark an increment done because the code exists. Done means the DoD
   command in that increment printed the stated output.
7. Do not update any spec's `Status:` line until its DoD command has been run
   and its output pasted into the PR body.

---

## 3. Increment order

C1 → C2 → C3 are a chain and must land in order. C4 and C5 depend on C2.
C6–C9 are independent of everything.

| # | Title | Depends on | Est. |
|---|---|---|---|
| C1 | Pool is mandatory; startup fails without it | — | 0.5 d |
| C2 | Single transport: port every worker call, delete the PostgREST twins | C1 | 2 d |
| C3 | Implement `WorkListener` for real | C2 | 1 d |
| C4 | Executor concurrency: acquire before claim, on all four paths | C2 | 1 d |
| C5 | Delete the dead code and dead config | C2 | 0.5 d |
| C6 | Realtime auth refresh + lifecycle catch-up + rejoin | — | 1 d |
| C7 | Contain Broadcast fan-out | — | 0.5 d |
| C8 | Make the schema/code gate real | — | 0.5 d |
| C9 | Android test parity | — | 0.5 d |

---

## Increment C1 — Pool is mandatory; startup fails without it

**Branch:** `fix/pg-pool-mandatory` · **Worktree:** `selko-fix-pg-pool-mandatory`

**Why:** `asyncpg` was never installed, and three separate code paths downgrade
a missing transport to a warning. The system reports healthy while running the
expensive transport it was built to replace.

### C1.1 Add the dependency

From the worktree root:

```bash
uv add asyncpg
```

Confirm `asyncpg` appears in `pyproject.toml` under `[project] dependencies` and
in `uv.lock`. Commit both.

### C1.2 Add the keepalive settings that H3 requires

`backend/selko/services/pg.py`, `create_pool`. The current call passes no TCP
keepalive settings, so hazard H3 — idle socket dropped by NAT or a load
balancer, listener goes deaf on a socket that still looks open — has a
mitigation in the spec and nothing in the code.

Replace `create_pool` in full:

```python
async def create_pool(config) -> "asyncpg.Pool":
    """Session-pooler pool with TCP keepalives and statement cache disabled.

    statement_cache_size=0 is set even though session mode supports prepared
    statements: it costs nothing here and makes a future misconfiguration to
    transaction mode fail loudly rather than intermittently.

    TCP keepalives (H3) are set below any known NAT/LB idle timeout so a
    silently dropped socket surfaces as a connection error rather than as a
    listener that never fires again.
    """
    import asyncpg

    assert_session_mode_url(config.supabase_db_url)
    keepalive = max(int(getattr(config, "pg_keepalive_seconds", 60) or 60), 10)
    pool = await asyncpg.create_pool(
        dsn=config.supabase_db_url,
        min_size=max(int(getattr(config, "pg_pool_min_size", 1) or 1), 1),
        max_size=max(int(getattr(config, "pg_pool_max_size", 4) or 4), 1),
        statement_cache_size=0,
        command_timeout=float(getattr(config, "pg_command_timeout_seconds", 30) or 30),
        timeout=getattr(config, "pg_connect_timeout_seconds", 10) or 10,
        server_settings={"application_name": "selko-worker"},
        # H3: below the ~350s idle timeout common to NAT and load balancers.
        # asyncpg sets no keepalives by default.
        connect_kwargs={
            "keepalives": 1,
            "keepalives_idle": keepalive,
            "keepalives_interval": 10,
            "keepalives_count": 3,
        },
    )
    logger.info(
        "Created asyncpg session-pooler pool min=%s max=%s keepalive_idle=%ss",
        getattr(config, "pg_pool_min_size", 1),
        getattr(config, "pg_pool_max_size", 4),
        keepalive,
    )
    return pool
```

**On `connect_kwargs`:** asyncpg forwards unknown keyword arguments from
`create_pool` to `connect`. If your installed asyncpg version rejects
`connect_kwargs`, pass the four keepalive keys as top-level kwargs to
`asyncpg.create_pool` instead. Decide which form your version accepts by running
the C1 test below — do not guess.

### C1.3 Replace the hardcoded `command_timeout=10`

`backend/selko/config.py`. Add to the `Config` dataclass next to
`pg_keepalive_seconds` (line 138):

```python
    pg_command_timeout_seconds: int = 30
```

And in the loader next to line 525:

```python
        pg_command_timeout_seconds=int(getenv("PG_COMMAND_TIMEOUT_SECONDS", "30")),
```

10 s is too tight for `upsert_discovered_email_items` with a 100-row page across
the Oregon ↔ us-east-1 split.

### C1.4 Fail startup instead of degrading silently

`backend/selko/api/app.py`, lines 107–121. Replace the whole block with:

```python
        # The direct-pg transport is the only transport for worker coordination.
        # A missing URL or a failed pool is a configuration error. There is
        # nothing to fall back to, and pretending otherwise is how this shipped
        # broken the first time.
        pg_pool = await create_pool(config)
        logger.info("Supavisor session pooler connected")
```

`create_pool` calls `assert_session_mode_url`, which raises `ConfigurationError`
on a missing, malformed, transaction-mode or IPv6-direct URL. Remove the
now-unused `assert_session_mode_url` import from `app.py`.

Fix the shutdown block at lines 176–182:

```python
        if pg_pool is not None:
            await pg_pool.close()
            logger.info("Pg pool closed")
```

Delete the `if 'pg_pool' in locals()` guard and the bare `except Exception: pass`.
Initialise `pg_pool = None` alongside `worker_pool` and `ingestion_runtime`
earlier in `lifespan` so the shutdown branch can reference it.

Apply the same change to `backend/selko/worker_app.py` — it constructs
`WorkerPool` and `IngestionRuntime` for staging drills and must create and pass
a pool identically. A drill that runs on a different transport than production
proves nothing.

### C1.5 Set the URL in every environment file

Get the URL from Supabase Dashboard → project → **Connect** → **Session pooler**.
It is a `*.pooler.supabase.com` host on port **5432**.

- Do **not** use "Direct connection" (`db.*.supabase.co` — IPv6-only, H4).
- Do **not** use "Transaction pooler" (port 6543 — breaks `LISTEN`, H1).

| File | Value |
|---|---|
| `.env` | `postgresql://postgres:postgres@localhost:54322/postgres` |
| `.env.test` | staging `lxmysergoeaegxlyfzwk` session pooler |
| `.env.production` | production `khahcozfbnpykspvatrg` session pooler |

**Environment separation is absolute.** Never put the production URL in `.env`
or `.env.test`. The database password is a distinct secret from
`SUPABASE_SERVICE_ROLE_KEY` (H5); never log it.

### C1.6 Report the transport on a health surface

`backend/selko/api/routes/health.py`, `/health/egress`. Store the pool on
`app.state.pg_pool` in `lifespan`, and add to the response:

```python
        "transport": "asyncpg" if request.app.state.pg_pool is not None else "none",
```

Add `transport: str` to `HealthEgressResponse` in
`backend/selko/api/schemas/common.py`.

This field exists because the review that produced this spec could not tell from
any running surface which transport was live. That must never be true again.

### Tests

`backend/tests/test_pg.py` — add:

```python
def test_create_pool_sets_keepalives_and_timeout(monkeypatch):
    """H3: asyncpg sets no TCP keepalives by default; we must pass them."""
    captured = {}

    async def fake_create_pool(**kwargs):
        captured.update(kwargs)
        return object()

    import asyncpg
    monkeypatch.setattr(asyncpg, "create_pool", fake_create_pool)

    from types import SimpleNamespace
    from selko.services.pg import create_pool

    config = SimpleNamespace(
        supabase_db_url="postgresql://postgres:pw@x.pooler.supabase.com:5432/postgres",
        pg_pool_min_size=1, pg_pool_max_size=4,
        pg_keepalive_seconds=60, pg_connect_timeout_seconds=10,
        pg_command_timeout_seconds=30,
    )
    import asyncio
    asyncio.run(create_pool(config))

    assert captured["statement_cache_size"] == 0
    assert captured["command_timeout"] == 30
    flat = {**captured, **captured.get("connect_kwargs", {})}
    assert flat["keepalives"] == 1
    assert flat["keepalives_idle"] == 60
```

### DoD

```bash
uv run pytest backend/tests/ -m "not integration" -q
```
green, and:

```bash
uv run python -c "import asyncpg; print(asyncpg.__version__)"
```
prints a version.

Start the API locally with `ENABLE_BACKGROUND_PROCESSING=true` and
`SUPABASE_DB_URL` **unset**. Startup must **fail** with a `ConfigurationError`
naming `SUPABASE_DB_URL`. Set it, confirm the log line
`Supavisor session pooler connected`, and confirm
`curl -s localhost:8000/health/egress | jq .transport` prints `"asyncpg"`.

### Rollback

Revert the PR.

---

## Increment C2 — Single transport: port every worker call, delete the PostgREST twins

**Branch:** `refactor/single-worker-transport` · **Worktree:** `selko-refactor-single-worker-transport`
**Depends on:** C1

**Why:** the `*_via_pool` methods exist and are correct; nothing calls them. The
sync PostgREST methods are what actually runs. Keeping both is a permanent
correctness tax and doubles the surface every future change has to get right.
After this increment there is **one** implementation of each worker operation.

### C2.0 Scope boundary — read this before editing

**In scope:** the trusted-worker coordination surface. Claim, heartbeat,
complete, fail, lease, and the worker-owned table writes listed in C2.2. These
run as service-role and bypass RLS today, so moving them to the `postgres` role
over the pooler is the same security posture, not a new one.

**Out of scope, do not touch:** web, iOS, Android, and every RLS-scoped API
route. Those keep using PostgREST with the **user's** JWT. If you find yourself
editing `frontend/`, `ios/`, or `android/` in this increment, stop.

### C2.1 Fix the missing import first

`backend/selko/workers/pool.py`, import block lines 37–42, currently:

```python
from selko.services.emails import (
    EmailError,
    claim_pending_email,
    complete_email_processing,
    fail_email_processing,
)
```

`claim_pending_email_via_pool` is called at line 374 and is **not imported**.
`NameError` is not `EmailError`, so it escapes the handler at line 386 into the
scheduler's generic `except Exception`, which logs and sleeps 5 s forever —
**email extraction would stop entirely with no symptom but a repeating log
line.** C2.3 renames these functions anyway, but fix the import as your first
commit so the branch is never in a state where wiring the pool breaks ingestion.

### C2.2 The complete port inventory

Every row below moves to asyncpg. Delete the PostgREST implementation in the
same commit that ports it — do not leave both.

**`services/email_ingestion.py` — `EmailIngestionRepository` becomes fully async.**
Drop the `_via_pool` suffix; the pool variant keeps the plain name.

| Method | Today | After |
|---|---|---|
| `claim_due_sync` | RPC + `_via_pool` twin | `async def claim_due_sync` over pool |
| `claim_due_reconciliation` | RPC + twin | async over pool |
| `heartbeat_sync` | RPC + twin | async over pool |
| `require_heartbeat` | sync wrapper | `async def`, awaits `heartbeat_sync` |
| `complete_sync` | RPC + twin | async over pool |
| `fail_sync` | RPC only | async over pool |
| `upsert_discovered` | RPC + twin | async over pool, `$3::jsonb` |
| `known_provider_message_ids` | RPC only | async over pool |
| `claim_item` | RPC + twin | async over pool |
| `complete_item` | RPC only | async over pool |
| `save_email_with_attachment_descriptors` | RPC only | async over pool |
| `fail_item` | RPC only | async over pool |
| `remove_item` | `.table().update()` at line 410 | async over pool, single `UPDATE … WHERE id = $1 AND lease_owner = $2` |
| `claim_attachment` | RPC + twin | async over pool |
| `finish_attachment` | RPC only | async over pool |
| `ensure_attachment_descriptors` | RPC only | async over pool |
| `attachment_readiness` | RPC only | async over pool |

`__init__` becomes `def __init__(self, config: Config, pg_pool)`. **Drop the
`client` parameter** — once every method is on the pool, the repository has no
use for a Supabase client, and keeping it invites a future fallback.

**Loose worker functions.**

| Function | File | Action |
|---|---|---|
| `claim_approved_event_for_sync` | `events.py:1721` | delete; rename `claim_approved_event_for_sync_via_pool` → `claim_approved_event_for_sync` |
| `claim_pending_email` | `emails.py:522` | delete; rename `claim_pending_email_via_pool` → `claim_pending_email` |
| `complete_event_sync`, `fail_event_sync`, `defer_event_sync_for_quota`, `park_event_for_oauth_reauth` | `events.py` | port to pool, `async def` |
| `complete_email_processing`, `fail_email_processing` | `emails.py` | port to pool, `async def` |
| `claim_integration_recovery` | `integrations.py:350` | port to pool, `async def` |
| `requeue_calendar_recovery_batch` | `calendars.py:185` | port to pool, `async def` |
| `refresh_waiting_calendar_recoveries` | `calendars.py:213` | port to pool, `async def` |
| `unlock_expired_email_locks` | `emails.py:668` | port to pool, `async def` |
| `unlock_expired_event_locks` | `events.py:1917` | port to pool, `async def` |
| `unlock_expired_integration_recoveries` | `integrations.py:371` | port to pool, `async def` |
| `unlock_expired_photo_locks`, `unlock_expired_scheduled_tasks` | `photos.py`, `scheduled_tasks.py` | port to pool, `async def` — they run at every startup |

`complete_integration_reauthorization` (`integrations.py:144`) is called from an
**API route** on behalf of a user, not from a worker. **Leave it on PostgREST.**

### C2.3 The porting pattern

The SQL functions do not change. They are already `SECURITY DEFINER` and already
do the locking. You are changing only how they are invoked.

```python
# Before
def claim_item(self, worker_id: str) -> dict[str, Any] | None:
    result = self.client.rpc(
        "claim_email_ingestion_item",
        {"p_worker_id": worker_id, "p_lease_seconds": self.config.email_lease_seconds},
    ).execute()
    rows = _rpc_data(result)
    return rows[0] if rows else None

# After
async def claim_item(self, worker_id: str) -> dict[str, Any] | None:
    row = await self.pg_pool.fetchrow(
        "SELECT * FROM public.claim_email_ingestion_item($1, $2)",
        worker_id, self.config.email_lease_seconds,
    )
    return dict(row) if row else None
```

Rules for the port:

- `RETURNS TABLE` / `RETURNS SETOF` → `fetchrow` with `SELECT * FROM fn(...)`.
- `RETURNS boolean` / scalar → `fetchval` with `SELECT fn(...)`.
- `RETURNS void` → `execute`.
- Any `jsonb` parameter gets an explicit `$n::jsonb` cast and a `json.dumps`
  argument. `upsert_discovered` at line 450 is the one that exists today; it has
  never executed, so its asyncpg type handling is unverified. The cast removes
  the question.
- Wrap the call in the module's existing error type
  (`EmailError`, `EventsError`, `CalendarsError`, `IntegrationError`) so callers
  keep their `except` clauses.

### C2.4 Callers become async

`asyncio.to_thread(self.repository.X, ...)` disappears everywhere — the calls are
already async now. Find every one:

```bash
grep -rn "to_thread(self.repository" backend/selko/workers/
```

Each becomes a direct `await`. `require_heartbeat` becoming `async def` forces
its callers async too:

```bash
grep -rn "require_heartbeat" backend/
```

Startup recovery in `app.py:133-137` becomes:

```python
        emails_unlocked = await unlock_expired_email_locks(pg_pool)
        events_unlocked = await unlock_expired_event_locks(pg_pool)
        photos_unlocked = await unlock_expired_photo_locks(pg_pool)
        tasks_unlocked = await unlock_expired_scheduled_tasks(pg_pool)
        recoveries_unlocked = await unlock_expired_integration_recoveries(pg_pool)
```

### C2.5 Pass the pool everywhere

`backend/selko/api/app.py`:

```python
        worker_pool = WorkerPool(
            idle_sleep_seconds=config.worker_idle_sleep_seconds,
            error_backoff_seconds=config.worker_error_backoff_seconds,
            pg_pool=pg_pool,
        )
        ...
        ingestion_runtime = IngestionRuntime(service_client, config, pg_pool=pg_pool)
```

(`num_workers` is dropped here — C5 removes the parameter. If you do C2 before
C5, keep passing it and let C5 clean up.)

`backend/selko/workers/ingestion_runtime.py:61` gains `pg_pool` and passes it to
every `EmailIngestionWorker` it constructs.
`backend/selko/workers/email_ingestion.py:115` becomes:

```python
        self.repository = EmailIngestionRepository(config, pg_pool)
```

`backend/selko/workers/pool.py` — make `pg_pool` a **required** positional
parameter, not a keyword defaulting to `None`. A `WorkerPool` without a pool
cannot do anything, so it must not be constructible.

### Tests

Existing tests that mock `client.rpc` will break. **Rewrite them against the
pool**, do not keep both. Add a shared fixture:

```python
# backend/tests/conftest.py
@pytest.fixture
def fake_pg_pool():
    """Minimal asyncpg pool double: records SQL and returns queued rows."""
    class FakePool:
        def __init__(self):
            self.calls = []
            self.rows = []
        async def fetchrow(self, sql, *args):
            self.calls.append((sql, args))
            return self.rows.pop(0) if self.rows else None
        async def fetchval(self, sql, *args):
            self.calls.append((sql, args))
            return self.rows.pop(0) if self.rows else None
        async def execute(self, sql, *args):
            self.calls.append((sql, args))
    return FakePool()
```

`backend/tests/test_workers.py` — the wiring test this whole class of defect
needed:

```python
@pytest.mark.asyncio
async def test_worker_pool_claims_over_the_pool(fake_pg_pool):
    """C2: a configured pool must actually reach the claim call."""
    pool = WorkerPool(fake_pg_pool)
    pool.config = load_config()
    await pool._process_any_work("test-worker")
    assert any("claim_approved_event" in sql for sql, _ in fake_pg_pool.calls)


def test_no_worker_module_retains_a_postgrest_fallback():
    """Rule 4 regression: one implementation per operation, no branches."""
    import pathlib, re
    banned = re.compile(r"_via_pool|if .*pg_pool is not None")
    for path in pathlib.Path("backend/selko").rglob("*.py"):
        text = path.read_text()
        assert not banned.search(text), f"{path} still branches on transport"
```

That second test is the guard rail. It fails today and must pass at the end of
C2.

**Integration tests** in `test_integration_ingestion_drill.py`, `@pytest.mark.integration`,
against local Supabase (`supabase start`): exercise each ported function once
against the real database and assert the returned shape. This is the only place
the `SELECT * FROM public.fn($1,$2)` form is actually proven.

### DoD

```bash
uv run pytest backend/tests/ -m "not integration" -q
```
green, and with local Supabase running:

```bash
uv run pytest backend/tests/ -m integration -q
```
green. Plus:

```bash
grep -rn "_via_pool" backend/
```
returns nothing.

Run the API locally against local Supabase with background processing on for
5 minutes, then:

```bash
curl -s localhost:8000/health/egress | jq '.top_operations[] | select(.operation | test("/rest/v1/rpc"))'
```

must print **nothing**. Paste that into the PR body.

### Rollback

Revert the PR. Leases make partial processing safe: any row claimed and not
completed has its lease expire and is reclaimed on the next pass.

---

## Increment C3 — Implement `WorkListener` for real

**Branch:** `feat/pg-work-listener` · **Worktree:** `selko-feat-pg-work-listener`
**Depends on:** C2

**Why:** migration `20260809000002` installs four `pg_notify('selko_work', …)`
triggers. Nothing has ever issued `LISTEN`. Until this lands, the safety poll is
the only wake mechanism and the design's central claim — "the backend does not
ask whether there is work, it is told" — is false.

### C3.1 Replace the stub

`backend/selko/services/pg.py`. Add `import time` at the top and delete the
`__import__("time")` call. Replace the whole `WorkListener` class:

```python
class WorkListener:
    """Dedicated LISTEN connection feeding asyncio.Events per work type.

    Owns its own connection, NOT a pool member — a pool connection could be
    handed to a query and lose its LISTEN registration.

    Liveness (H3): every PG_LISTENER_HEARTBEAT_SECONDS it emits a self-NOTIFY
    on 'selko_work' with payload 'heartbeat' and asserts receipt within 10s. A
    miss means the socket is dead-but-open; the connection is torn down and
    reconnected with exponential backoff (1s, 2s, 4s … capped at 60s).
    Reconnect always re-issues LISTEN before declaring itself healthy.
    """

    CHANNEL = "selko_work"
    HEARTBEAT_PAYLOAD = "heartbeat"
    WORK_TYPES = ("email_pending", "event_approved", "item_pending", "attachment_pending")

    def __init__(self, config):
        self.config = config
        self._conn = None
        self._events: dict[str, asyncio.Event] = {}
        self._connected = False
        self._reconnects = 0
        self._last_notification_at: float | None = None
        self._heartbeat_seen = asyncio.Event()
        self._heartbeat_task: asyncio.Task | None = None
        self._stopping = False

    def event_for(self, work_type: str) -> asyncio.Event:
        if work_type not in self._events:
            self._events[work_type] = asyncio.Event()
        return self._events[work_type]

    def _on_notify(self, connection, pid, channel, payload):
        self._last_notification_at = time.time()
        if payload == self.HEARTBEAT_PAYLOAD:
            self._heartbeat_seen.set()
            return
        event = self._events.get(payload)
        if event is not None:
            event.set()
        else:
            logger.debug("WorkListener: unknown payload %r on %s", payload, channel)

    async def _connect(self) -> None:
        import asyncpg

        assert_session_mode_url(self.config.supabase_db_url)
        self._conn = await asyncpg.connect(
            dsn=self.config.supabase_db_url,
            statement_cache_size=0,
            timeout=getattr(self.config, "pg_connect_timeout_seconds", 10) or 10,
        )
        await self._conn.add_listener(self.CHANNEL, self._on_notify)
        self._connected = True
        logger.info("WorkListener: LISTEN %s established", self.CHANNEL)

    async def start(self) -> None:
        self._stopping = False
        for work_type in self.WORK_TYPES:
            self.event_for(work_type)
        await self._connect()
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(), name="pg-work-listener-heartbeat"
        )

    async def _heartbeat_loop(self) -> None:
        interval = max(int(getattr(self.config, "pg_listener_heartbeat_seconds", 120) or 120), 30)
        backoff = 1.0
        while not self._stopping:
            try:
                await asyncio.sleep(interval)
                if self._stopping:
                    return
                self._heartbeat_seen.clear()
                await self._conn.execute(
                    "SELECT pg_notify($1, $2)", self.CHANNEL, self.HEARTBEAT_PAYLOAD
                )
                try:
                    await asyncio.wait_for(self._heartbeat_seen.wait(), timeout=10.0)
                    backoff = 1.0
                except asyncio.TimeoutError:
                    raise ConnectionError("listener heartbeat not received within 10s")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._connected = False
                self._reconnects += 1
                logger.warning(
                    "WorkListener: reconnecting after %s (reconnect #%d, backoff %.0fs)",
                    exc, self._reconnects, backoff,
                )
                await self._teardown_connection()
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 60.0)
                try:
                    await self._connect()
                    # A dropped socket may have lost notifications. Wake every
                    # work type so the next drain reconciles from the database,
                    # which is the durable source of truth.
                    for event in self._events.values():
                        event.set()
                except Exception as reconnect_exc:
                    logger.error("WorkListener: reconnect failed: %s", reconnect_exc)

    async def _teardown_connection(self) -> None:
        if self._conn is not None:
            try:
                await self._conn.remove_listener(self.CHANNEL, self._on_notify)
            except Exception:
                pass
            try:
                await self._conn.close()
            except Exception as exc:
                logger.warning("WorkListener: error closing connection: %s", exc)
            self._conn = None

    async def stop(self) -> None:
        self._stopping = True
        self._connected = False
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None
        await self._teardown_connection()

    def status(self) -> dict:
        return {
            "connected": self._connected,
            "reconnects": self._reconnects,
            "last_notification_at": self._last_notification_at,
        }
```

**`status()` must never report `connected: True` unless a `LISTEN` is registered
on a live connection.** The stub did exactly that, which is why this increment
exists.

### C3.2 Instantiate it and feed the schedulers

`backend/selko/api/app.py`, after the pool:

```python
        from selko.services.pg import WorkListener

        work_listener = WorkListener(config)
        await work_listener.start()
        app.state.work_listener = work_listener
```

Pass it to both schedulers as a required parameter. Stop it in the shutdown
branch **after** both schedulers stop and **before** the pool closes. Mirror all
of this in `backend/selko/worker_app.py`.

### C3.3 Wait on the listener in the idle path

`backend/selko/workers/pool.py`, `_scheduler_loop`, idle branch at lines 264–276:

```python
                # --- idle: wait for nudge, notification, or safety poll ---
                waiters = [asyncio.create_task(self._nudge_event.wait())]
                for work_type in ("event_approved", "email_pending"):
                    waiters.append(
                        asyncio.create_task(self._work_listener.event_for(work_type).wait())
                    )
                _, pending = await asyncio.wait(
                    waiters,
                    timeout=float(self.config.worker_safety_poll_seconds),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                if self._nudge_event.is_set():
                    self._nudge_event.clear()
                for work_type in ("event_approved", "email_pending"):
                    self._work_listener.event_for(work_type).clear()
```

`worker_safety_poll_seconds` already has a hard floor of 60 s (`config.py:527`).
**Do not add a way to disable it** (H2): `NOTIFY` is not durable, and the poll is
what turns a missed notification into latency rather than stranded work.

Apply the same pattern to `_claim_loop` in
`backend/selko/workers/email_ingestion.py:829-855` — `item_pending` for the
acquisition loop, `attachment_pending` for the attachment loop.

### C3.4 Expose listener status

Add `"listener": app.state.work_listener.status()` to `/health/ingestion` and the
field to `HealthIngestionResponse`.

### Tests

`backend/tests/test_pg.py`:

```python
def test_listener_sets_event_for_payload():
    listener = WorkListener(config=_fake_config())
    event = listener.event_for("email_pending")
    assert not event.is_set()
    listener._on_notify(None, 1, "selko_work", "email_pending")
    assert event.is_set()


def test_heartbeat_payload_does_not_set_work_events():
    listener = WorkListener(config=_fake_config())
    work = listener.event_for("email_pending")
    listener._on_notify(None, 1, "selko_work", "heartbeat")
    assert listener._heartbeat_seen.is_set()
    assert not work.is_set()


def test_status_is_false_before_start():
    """Regression: the Inc5 stub reported connected=True without a LISTEN."""
    assert WorkListener(config=_fake_config()).status()["connected"] is False
```

**Integration tests**, `@pytest.mark.integration`, against local Supabase:

1. **H2 — durability.** Stop the listener, insert a row that fires a trigger, and
   assert the work is processed within `worker_safety_poll_seconds`. A missed
   notification must cost latency, never work.
2. **H3 — dead socket.** `SELECT pg_terminate_backend(pid) FROM pg_stat_activity
   WHERE application_name = 'selko-worker'`, then assert
   `status()["reconnects"]` increments and a later `NOTIFY` is delivered.
3. **§3.1 — batch collapse.** Insert 100 `email_ingestion_items` in one
   transaction; assert exactly **one** notification arrives.
4. **D3 — no double-processing.** Two listeners, one notification, one claim.

### DoD

Both test commands green. Then, with the API running against local Supabase:

```bash
psql "$SUPABASE_DB_URL" -c "SELECT pg_notify('selko_work','event_approved')"
```

The log must show a scheduler wake within one second, and
`curl -s localhost:8000/health/ingestion | jq .listener` must show
`"connected": true` with a recent `last_notification_at`.

Run idle for 30 minutes and confirm from `/health/egress` that supabase
`calls_per_second` is below `2 / worker_safety_poll_seconds`. Paste the snapshot
into the PR body.

### Rollback

Revert the PR. The schedulers fall back to the safety poll, which is the
behaviour C2 leaves in place. Leave `20260809000002` alone — unconsumed
`pg_notify` is free.

---

## Increment C4 — Executor concurrency: acquire before claim, on all four paths

**Branch:** `fix/executor-concurrency` · **Worktree:** `selko-fix-executor-concurrency`
**Depends on:** C2

**Why:** two related defects with one shape.

*Ingestion:* Inc2 collapsed N pollers to 1 loop, which was correct, but never
added the semaphore. Acquisition and attachment are strictly serial, and
`email_acquisition_concurrency` / `email_attachment_concurrency` are read
nowhere.

*LLM:* [pool.py:373-385](../../backend/selko/workers/pool.py) claims an email,
fires a task, returns `True`, and immediately re-drains. **The semaphore bounds
execution, not claiming.** With the 578-email backlog named in the code comment,
578 tasks are created at once, each holding a 300 s lease. The comment's own
arithmetic — 8-wide, ~6 minutes — puts the tail at ~360 s against that lease.
Expired leases are reclaimable, so the same process re-extracts emails already
in flight: duplicate LLM spend and duplicate suggestions in the review queue.

*Calendar:* `worker_calendar_sync_concurrency` is read nowhere; event sync is
awaited inline.

**The rule for all four: backpressure belongs at the claim, not at the work.**
A claimed row holds a lease; never claim one you are not about to process.

### C4.1 The pattern

```python
    async def run_acquisition_once(self) -> bool:
        # Acquire the executor slot BEFORE claiming. Claiming first lets the
        # drain loop outrun the executors, and every claimed row holds a lease
        # that expires while it waits in the queue.
        await self._acquisition_semaphore.acquire()
        try:
            item = await self.repository.claim_item(self.worker_id)
        except BaseException:
            self._acquisition_semaphore.release()
            raise
        if not item:
            self._acquisition_semaphore.release()
            return False

        task = asyncio.create_task(self._process_acquisition_item(item))
        self._inflight.add(task)
        task.add_done_callback(self._inflight.discard)
        task.add_done_callback(lambda _: self._acquisition_semaphore.release())
        return True
```

Move the existing body after the claim into
`async def _process_acquisition_item(self, item) -> None`.

### C4.2 Apply it to all four paths

| Path | File | Semaphore sized by |
|---|---|---|
| acquisition | `workers/email_ingestion.py:627` | `email_acquisition_concurrency` |
| attachment | `workers/email_ingestion.py:705` | `email_attachment_concurrency` |
| LLM extraction | `workers/pool.py:371-387` | `llm_extraction_concurrency` |
| calendar sync | `workers/pool.py:353-365` | `worker_calendar_sync_concurrency` |

Create the semaphores in each class's `__init__` (or `start()` where they must
bind to the running loop, as `_llm_semaphore` already does) and keep an
`_inflight: set[asyncio.Task]` per path.

For the LLM path, use a non-blocking acquire so a full executor pool does not
stall the other work types:

```python
            try:
                await asyncio.wait_for(self._llm_semaphore.acquire(), timeout=0.01)
            except asyncio.TimeoutError:
                pass  # all executors busy; fall through to the next work type
```

Delete `_process_email_with_semaphore` (pool.py:321-328) — the semaphore is now
held by the claim path, and taking it twice would deadlock.

### C4.3 Make the lease outlast the queue

Replace the literal `300` at both claim call sites in `_process_any_work` with a
config value. `backend/selko/config.py`:

```python
    llm_claim_lease_seconds: int = 900
```
```python
        llm_claim_lease_seconds=int(getenv("LLM_CLAIM_LEASE_SECONDS", "900")),
```

### C4.4 Await in-flight work on stop

In each stop path, after the loops exit:

```python
        if self._inflight:
            await asyncio.wait(self._inflight, timeout=30)
```

### C4.5 Correct the config docstrings

`backend/selko/config.py:122-126`:

```python
    # Executor width, NOT poller count. One claim loop per type drains the
    # queue; these bound how many items are processed concurrently. Raising
    # them does not increase database polling.
    email_acquisition_concurrency: int = 2
    email_attachment_concurrency: int = 2
```

### Tests

```python
@pytest.mark.asyncio
async def test_acquisition_respects_executor_width():
    """C4: concurrency 4 with 10 items — one claim loop, max 4 in flight, all 10 done."""
    assert peak_in_flight <= 4
    assert completed == 10


@pytest.mark.asyncio
async def test_claim_never_outruns_executors():
    """C4.1 regression: claiming before acquiring let leases expire in the queue."""
    # concurrency 1, processor blocks on an event, 10 items available
    assert claim_count == 1


@pytest.mark.asyncio
async def test_semaphore_released_when_claim_returns_none():
    """A no-work claim must not leak a permit."""
    assert semaphore._value == expected_width


@pytest.mark.asyncio
async def test_semaphore_released_when_claim_raises():
    """An error must not leak a permit."""


def test_every_concurrency_knob_is_read_by_a_worker():
    """Regression: after Inc2 three of these were read nowhere."""
    import pathlib
    source = "\n".join(
        p.read_text() for p in pathlib.Path("backend/selko/workers").rglob("*.py")
    )
    for knob in (
        "email_acquisition_concurrency",
        "email_attachment_concurrency",
        "llm_extraction_concurrency",
        "worker_calendar_sync_concurrency",
    ):
        assert knob in source, f"{knob} is not read by any worker"
```

### DoD

`uv run pytest backend/tests/ -m "not integration" -q` green. Seed 50 pending
emails locally, run with `LLM_EXTRACTION_CONCURRENCY=4`, and confirm no more
than 4 `claimed email` log lines appear without a matching `Completed email`.

### Rollback

Revert the PR. Behaviour returns to serial processing — slow but correct.

---

## Increment C5 — Delete the dead code and dead config

**Branch:** `chore/delete-dead-worker-code` · **Worktree:** `selko-chore-delete-dead-worker-code`
**Depends on:** C2

**Why:** §1.1 lists thirteen items that are unreachable, unread, or duplicated.
Every one of them is a trap for the next reader, and several are the residue of
"kept for compat" decisions that no caller ever needed.

### C5.1 Delete from `workers/pool.py`

| Delete | Line | Note |
|---|---|---|
| duplicate `self.pg_pool = pg_pool` | 99 | |
| `_idle_backoff` | 292–307 | delete the tests at `test_workers.py:703-715` too |
| `_worker_loop` alias | 287–290 | fix `test_workers.py:380`, which patches it |
| `_process_scheduled_task` | 473–512 | no caller; drop the `scheduled_tasks` imports it needed |
| `_process_photo` | 564–609 | no caller; drop the `photos` imports it needed |
| `num_workers` param and attribute | 81, 89, 95 | and from both construction sites |

Then rewrite the module docstring (lines 1–13). It currently says `_process_email`
is "retained for hardening inc 8 cleanup only" — it is the live LLM extraction
path. Say what the module does now: one scheduler, two work types (calendar sync
and LLM extraction), plus recovery bookkeeping.

Also delete the unused imports this leaves behind:
`claim_scheduled_task`, `complete_scheduled_task`, `fail_scheduled_task`,
`ScheduledTasksError`, `claim_pending_photo`, `complete_photo_processing`,
`fail_photo_processing`, `PhotosError`.

`workers/photo_fetch.py` and `workers/photo_process.py` **stay** — the photos
schema is deliberately retained per
[`photo-surface-removal.md`](photo-surface-removal.md). Only the worker-pool
plumbing that can never reach them goes.

### C5.2 Delete from `config.py`

| Delete | Line |
|---|---|
| `worker_pool_size` field and loader | 83, 484 |

`worker_calendar_sync_concurrency` **stays** — C4 makes it real. If C4 has not
landed when you do this, do C4 first.

Remove `WORKER_POOL_SIZE` from `.env.example`, `.env`, `.env.test`,
`.env.production`.

### C5.3 Delete from `services/pg.py`

The `for e in self._events.values():` loop with the `pass` body at lines 137–140.
C3 replaces this file's `WorkListener` wholesale; if C3 has landed, this is
already gone — verify rather than assume.

### C5.4 Delete from `api/app.py`

The `if 'pg_pool' in locals()` guard and `except Exception: pass` at lines
178–182. C1 already does this; verify.

### C5.5 Fix the duplicated trigger condition

New migration
`supabase/migrations/20260811000002_broadcast_dedupe_condition.sql`, recreating
`public.trg_events_broadcast` with `NEW.status IS DISTINCT FROM OLD.status`
appearing once:

```sql
        IF (NEW.status IS DISTINCT FROM OLD.status
            OR NEW.title IS DISTINCT FROM OLD.title
            OR NEW.start_datetime IS DISTINCT FROM OLD.start_datetime
            OR NEW.end_datetime IS DISTINCT FROM OLD.end_datetime
            OR NEW.sync_status IS DISTINCT FROM OLD.sync_status) THEN
```

If C7 has already landed, fold this into C7's migration instead of adding a
second one.

### C5.6 Purge the dead `scheduled_tasks` rows

Decision D5 of the original spec said to delete the rows and keep the table. The
rows are still there. New migration
`supabase/migrations/20260811000003_purge_email_fetch_tasks.sql`:

```sql
-- D5: 'email_fetch' scheduled tasks are residue of an architecture that no
-- longer exists (durable polling replaced it in #234). The table and
-- services/scheduled_tasks.py stay for the parked photo path; the rows go.
DELETE FROM public.scheduled_tasks WHERE task_type = 'email_fetch';
```

Record the deleted row count in the PR body.

### Tests

Deleting code deletes tests. Where a test pinned dead code, delete the test.
Where a test patched a deleted alias, repoint it at the real function.

Add one guard:

```python
def test_no_compat_shims_in_workers():
    """Rule 5: delete, do not deprecate."""
    import pathlib, re
    banned = re.compile(r"kept for compat|retained for compat|deprecated alias|Legacy alias")
    for path in pathlib.Path("backend/selko/workers").rglob("*.py"):
        text = path.read_text()
        assert not banned.search(text), f"{path} still carries a compat shim"
```

### DoD

`uv run pytest backend/tests/ -m "not integration" -q` green, and:

```bash
uv run ruff check backend/selko --select F401
```

reports no unused imports in the files you touched. Plus:

```bash
grep -rn "worker_pool_size\|num_workers\|_idle_backoff\|_worker_loop" backend/selko/
```

returns nothing.

### Rollback

Revert the PR. The two migrations are additive-safe: recreating a trigger
function is idempotent, and the row purge is not reversible but the rows are
provably dead (D5 verified `scheduled_tasks` is reachable only from the parked
photo path).

---

## Increment C6 — Realtime auth refresh, lifecycle catch-up, rejoin

**Branch:** `fix/live-updates-auth-lifecycle` · **Worktree:** `selko-fix-live-updates-auth-lifecycle`

**Why:** all three clients call `setAuth` exactly once, at channel start. Private
Broadcast channels authorize per-JWT against the `realtime.messages` RLS policy
created in `20260809000003`. When the access token expires (~1 h) the channel
stops delivering and nothing retries. Separately, the web tab-visibility
catch-up is a no-op, and no client handles a terminal channel state.

### C6.1 Web — refresh auth on token rotation

`frontend/src/lib/live-updates.js`:

```javascript
/**
 * Re-authorize the realtime socket after a token rotation.
 * Private channels authorize per-JWT; without this the channel goes deaf
 * when the access token expires (~1h) and nothing reports it.
 * @param {string | null} accessToken
 */
export async function refreshAuth(accessToken) {
	if (!accessToken) return;
	try {
		await supabase.realtime.setAuth(accessToken);
	} catch (e) {
		console.warn('[live-updates] setAuth refresh failed', e);
	}
}
```

`frontend/src/lib/stores.js:36`, inside the existing `onAuthStateChange`:

```javascript
		if (event === 'TOKEN_REFRESHED' || event === 'SIGNED_IN') {
			import('$lib/live-updates.js').then((m) => m.refreshAuth(session?.access_token ?? null));
		}
```

### C6.2 Web — make lifecycle catch-up actually refetch

`frontend/src/lib/live-updates.js`:

```javascript
/**
 * Force a catch-up refetch for every subscribed resource.
 * Used on tab-visible, window-focus and network-online. Unlike start(),
 * this does not short-circuit when the channel already exists.
 */
export function catchUp() {
	for (const resource of [...listeners.keys()]) {
		scheduleRefresh(resource, {
			resource,
			operation: 'CATCHUP',
			occurred_at: new Date().toISOString()
		});
	}
}
```

`frontend/src/routes/app/+layout.svelte` — in `onVisible` and the `online` and
`focus` handlers, replace `liveUpdates.start(currentUid)` with
`liveUpdates.catchUp()`. `start()` returns early when `userId === uid && channel`
([live-updates.js:104](../../frontend/src/lib/live-updates.js)), which is why the
current call does nothing.

### C6.3 Web — handle terminal channel states

In the `channel.subscribe` callback:

```javascript
	let rejoinAttempts = 0;
	channel.subscribe((status) => {
		connectionStatus = status;
		if (status === 'SUBSCRIBED') {
			rejoinAttempts = 0;
			catchUp();
			return;
		}
		if (status === 'CHANNEL_ERROR' || status === 'TIMED_OUT' || status === 'CLOSED') {
			// A private channel that fails authorization will not self-heal.
			// Rejoin with backoff and catch up from the database on success —
			// the database is the source of truth, the channel is a hint.
			const delay = Math.min(1000 * 2 ** rejoinAttempts, 60000);
			rejoinAttempts += 1;
			const uid = userId;
			setTimeout(() => {
				if (!uid) return;
				stop().then(() => start(uid));
			}, delay);
		}
	});
```

Capture `uid` **before** the timeout fires — `stop()` clears `userId`.

### C6.4 iOS — the same three fixes

`ios/Selko/Core/LiveUpdates/LiveUpdateService.swift`:

- `func refreshAuth(_ token: String) async` calling
  `await supabase.realtimeV2.setAuth(token)`, called from the app's
  `AuthChangeEvent.tokenRefreshed` observer.
- `func catchUp() async` emitting a synthetic invalidation for each of
  `["events", "event_sources", "emails", "integrations"]`, called from the
  scene-active hook instead of `start(userId:)`.
- `subscribeWithError()` currently sets `connectionStatus = "error: …"` and stops
  (line 69). Add the same capped exponential backoff rejoin.

### C6.5 Android — the same three fixes

`android/app/src/main/java/net/melisma/selko/data/repository/LiveUpdateRepository.kt`:

- Observe `supabaseClient.auth.sessionStatus` and re-call
  `supabaseClient.realtime.setAuth(token)` on `SessionStatus.Authenticated`.
- Add `catchUp()` emitting synthetic invalidations, called from `ON_START`.
- Handle `RealtimeChannel.Status.CLOSED` and errors with a backoff rejoin.

### Tests

New `frontend/src/lib/__tests__/live-updates.test.js`:

```javascript
it('re-authorizes realtime on TOKEN_REFRESHED', async () => { /* setAuth called with new token */ });
it('catchUp refetches even when the channel is already open', async () => { /* listener fires */ });
it('rejoins after CHANNEL_ERROR', async () => { /* stop+start called after backoff */ });
```

iOS: cases in `ios/SelkoTests/` for `catchUp()` emitting all four resources and
`refreshAuth` calling through.

Android: new
`android/app/src/test/java/net/melisma/selko/data/repository/LiveUpdateRepositoryTest.kt`
covering the same three behaviours.

### DoD

- `cd frontend && npm run test:unit` and `npm run check` pass.
- iOS: `rm -rf ios/TestResults.xcresult` then
  `xcodebuild test -project ios/iOS.xcodeproj -scheme iOS -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -resultBundlePath ios/TestResults.xcresult` passes.
- Android: `cd android && ./gradlew testDebugUnitTest` passes.
- **Screenshots: skip.** This increment changes no UI.
- Manual, web: sign in, run `await supabase.auth.refreshSession()` in devtools,
  approve an event from another browser, confirm the first tab updates.

### Rollback

Revert per platform — the three changes are independent.

---

## Increment C7 — Contain Broadcast fan-out

**Branch:** `fix/broadcast-fanout` · **Worktree:** `selko-fix-broadcast-fanout`

**Why:** the direct-pg spec relies on Postgres collapsing duplicate
`(channel, payload)` pairs per transaction for `pg_notify` (§3.1).
**`realtime.send` does not collapse.** The per-row triggers in `20260809000003`
emit one message per row, so any multi-row write — retroactive sender-ignore,
reconcile sweeps, bulk reject — fans out one Broadcast message per row against a
2,000,000/month quota. This is the same cost shape the Aug 6–9 work existed to
remove.

### C7.1 Measure before changing

Against local Supabase, after seeding:

```sql
BEGIN;
UPDATE public.events SET status = 'rejected'
 WHERE user_id = '<uid>' AND status = 'pending_review';
COMMIT;
SELECT count(*) FROM realtime.messages WHERE topic = 'user:<uid>:selko-changes';
```

Record the row count and the message count in the PR body. Equal counts confirm
the defect.

### C7.2 Collapse to one message per transaction per resource

New migration `supabase/migrations/20260811000001_broadcast_fanout_collapse.sql`:

```sql
-- Broadcast fan-out collapse: one message per (transaction, user, resource).
-- realtime.send does NOT deduplicate the way pg_notify does, so the per-row
-- triggers previously emitted one message per row. The payload is an
-- invalidation hint, so one per transaction carries the same information.

CREATE OR REPLACE FUNCTION public.broadcast_user_ui_change(
    p_user_id uuid,
    p_resource text,
    p_operation text,
    p_entity_id uuid
) RETURNS void
LANGUAGE plpgsql SECURITY DEFINER SET search_path = '' AS $$
DECLARE
    v_payload jsonb;
    v_topic text;
    v_guard text;
BEGIN
    IF p_user_id IS NULL THEN
        RETURN;
    END IF;

    -- Transaction-local GUC as the guard; reset automatically at commit
    -- or rollback, so it cannot leak between transactions on a pooled
    -- connection.
    v_guard := 'selko.bc_' || replace(p_user_id::text, '-', '') || '_' || p_resource;
    IF current_setting(v_guard, true) = '1' THEN
        RETURN;
    END IF;
    PERFORM set_config(v_guard, '1', true);

    v_topic := 'user:' || p_user_id::text || ':selko-changes';
    v_payload := jsonb_build_object(
        'resource', p_resource,
        'operation', p_operation,
        -- entity_id is omitted: consumers refetch the whole resource anyway,
        -- and a single id is misleading when the transaction touched many rows.
        'occurred_at', (now() AT TIME ZONE 'utc')::text
    );
    PERFORM realtime.send(v_payload, 'invalidate', v_topic, true);
END;
$$;

REVOKE ALL ON FUNCTION public.broadcast_user_ui_change(uuid, text, text, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.broadcast_user_ui_change(uuid, text, text, uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.broadcast_user_ui_change(uuid, text, text, uuid) TO authenticated;
```

Dropping `entity_id` is safe: `handleInvalidate`
(`frontend/src/lib/live-updates.js:86`) uses only `inv.resource`, and the iOS and
Android handlers do the same. Confirm by reading all three before you ship.

### C7.3 Narrow the events UPDATE trigger

Same migration. `trg_events_broadcast_upd` is `AFTER UPDATE` with **no column
list**, so it fires on every column change including lease churn:

```sql
DROP TRIGGER IF EXISTS trg_events_broadcast_upd ON public.events;
CREATE TRIGGER trg_events_broadcast_upd
    AFTER UPDATE OF status, title, start_datetime, end_datetime, sync_status
    ON public.events
    FOR EACH ROW EXECUTE FUNCTION public.trg_events_broadcast();
```

Fold C5.5's duplicate-condition fix into this migration if C5 has not landed.

### Tests

New `backend/tests/test_broadcast_fanout.py`, `@pytest.mark.integration`:

```python
@pytest.mark.integration
def test_bulk_update_emits_one_broadcast_per_resource(supabase_local):
    """C7: 50 rows updated in one transaction must produce one message."""
```

### DoD

Re-run the C7.1 measurement: 50 rows, 1 message. Paste before and after into the
PR body. `uv run pytest backend/tests/ -m "not integration" -q` green.

Apply to staging first with `supabase db push`, re-measure there, then
production.

### Rollback

Write the inverse migration restoring the pre-C7 function body from
`20260809000003`. Do not revert the PR — the schema has already moved.

---

## Increment C8 — Make the schema/code gate real

**Branch:** `fix/schema-compat-gate` · **Worktree:** `selko-fix-schema-compat-gate`

**Why:** [`scripts/assert-schema-code-compat.sh`](../../scripts/assert-schema-code-compat.sh)
claims the wrong deploy order is "mechanically impossible". It is not. Default
mode always exits 0. `--linked` exits 0 when the CLI is missing or when the list
command fails. It compares counts rather than versions, so a remote with the
same number of *different* migrations passes. It invokes
`supabase migration list --linked` twice, and `grep -c "\.sql"` counts against a
version table containing no `.sql` strings.

This is the mechanism meant to prevent the code/schema divergence recorded in
[`egress-and-work-scheduling.md`](egress-and-work-scheduling.md).

### C8.1 Replace the script

```bash
#!/usr/bin/env bash
# R5 — migrations must not be behind code.
#
# Compares migration VERSIONS (not counts) between the repository and the
# linked Supabase project. Any local version missing remotely is a failure.
#
# Usage: ./scripts/assert-schema-code-compat.sh --linked
#
# There is no mode that passes without checking. If the check cannot run,
# it fails. A gate that exits 0 when it cannot verify is not a gate.
set -euo pipefail

MIGR_DIR="supabase/migrations"

if [[ "${1:-}" != "--linked" ]]; then
  echo "❌ FAIL: --linked is required. A local-only check proves nothing."
  exit 1
fi

if ! command -v supabase >/dev/null 2>&1; then
  echo "❌ FAIL: supabase CLI not installed — cannot verify remote schema."
  exit 1
fi

LOCAL_VERSIONS=$(ls -1 "$MIGR_DIR"/*.sql | xargs -n1 basename | cut -d_ -f1 | sort -u)
LOCAL_COUNT=$(echo "$LOCAL_VERSIONS" | grep -c . || true)
echo "Local migration versions: $LOCAL_COUNT"

if ! REMOTE_RAW=$(supabase migration list --linked 2>&1); then
  echo "❌ FAIL: could not list linked migrations."
  echo "   Run 'supabase link' and export SUPABASE_ACCESS_TOKEN."
  echo "$REMOTE_RAW"
  exit 1
fi

REMOTE_VERSIONS=$(echo "$REMOTE_RAW" | grep -oE '[0-9]{14}' | sort -u)
REMOTE_COUNT=$(echo "$REMOTE_VERSIONS" | grep -c . || true)
echo "Remote applied versions: $REMOTE_COUNT"

MISSING=$(comm -23 <(echo "$LOCAL_VERSIONS") <(echo "$REMOTE_VERSIONS"))
if [[ -n "$MISSING" ]]; then
  echo "❌ FAIL: these migrations exist in the repo but not on the remote:"
  echo "$MISSING" | sed 's/^/   /'
  echo "   Run 'supabase db push' before deploying this code."
  exit 1
fi

echo "✅ Every local migration is applied remotely ($LOCAL_COUNT local, $REMOTE_COUNT remote)"
```

### C8.2 Wire it into the deploy path

Update the relevant section of `docs/ci-cd.md` to state that `--linked` is the
only supported invocation and that a non-zero exit blocks the deploy.

### Tests

Verify by hand and paste all three outputs into the PR body:

1. `./scripts/assert-schema-code-compat.sh` → fails with the `--linked` message.
2. Linked to staging with everything pushed → prints `✅`, exits 0.
3. Create `supabase/migrations/29999999999999_probe.sql`, re-run → fails and
   names `29999999999999`. Delete the probe afterwards.

### DoD

All three manual checks produce the stated result.

### Rollback

Revert the PR. The previous script always passed, so reverting removes a check
rather than breaking a deploy.

---

## Increment C9 — Android test parity

**Branch:** `test/android-review-parity` · **Worktree:** `selko-test-android-review-parity`

**Why:** across `46750d5d..78d06bb2`, `ReviewQueueViewModel.kt` gained 163 lines
and `EventDetailViewModel.kt` 132, plus a new `LiveUpdateRepository.kt` — and
`ReviewQueueViewModelTest.kt` and `EventDetailViewModelTest.kt` were never
touched. PR #278 fixed a race in Android's `showRejectUndo` and shipped only iOS
tests. `CLAUDE.md` requires a regression test in the module fixed.

### C9.1 Reject-undo tests

`android/app/src/test/java/net/melisma/selko/ui/screens/review/ReviewQueueViewModelTest.kt`,
mirroring `ios/SelkoTests/Review/ReviewQueueViewModelTests.swift`:

- rejecting one event shows the snackbar with the singular string
- a second reject within 8 s combines both and shows the plural string, count 2
- undo restores every combined event
- `dismissUndo` after 8 s clears `showUndoSnackbar` and `lastRejectedEvents`
- **the #278 race:** two `showRejectUndo` calls in flight must not lose an event
  from `lastRejectedEvents` — the regression test that PR should have carried
- partial-success reject removes only the succeeded ids and still refetches

### C9.2 Live-update consumer tests

New `android/app/src/test/java/net/melisma/selko/data/repository/LiveUpdateRepositoryTest.kt`:

- an `invalidate` for `events` triggers exactly one refetch after debounce
- a payload for an unlisted resource is ignored
- five invalidations within the debounce window produce one refetch

### C9.3 Event detail tests

`EventDetailViewModelTest.kt` — mirror the iOS additions in #278, in particular
that `reject` on an unloaded event does not fabricate one.

### DoD

```bash
cd android
```
```bash
./gradlew testDebugUnitTest
```

green, with the new tests in the report. **Screenshots: skip** — no UI change.

### Rollback

Revert the PR. Tests only.

---

## 4. After all increments land

1. Update the `Status:` line of
   [`direct-postgres-work-transport.md`](direct-postgres-work-transport.md) to
   name the PRs that actually completed Inc2–Inc5.
2. Update [`live-ui-updates.md`](live-ui-updates.md) with the auth-refresh and
   fan-out decisions from C6 and C7.
3. Add to `CLAUDE.md` under Architecture Principles: *worker database access is
   asyncpg over the session pooler; PostgREST is for RLS-scoped client and API
   traffic only. There is no fallback between them.*
4. Run [`cutover-verification-20260807.md`](cutover-verification-20260807.md)
   against production, then re-measure `/health/egress` and Render
   `bandwidth_usage` for 24 hours and record `bytes_per_mailbox_per_day`.

## 5. Deferred, deliberately

- **Multi-instance.** `numInstances` stays 1, per D3 of the original spec. C3
  makes `LISTEN` strictly better than the in-process nudge if that changes, but
  claim contention at N>1 is still not exercised and is not claimed as
  supported.
- **Region colocation.** Render Oregon ↔ Supabase us-east-1 stays as-is, per D4.
- **Bulk row I/O.** Email bodies, attachment blobs and event rows that workers
  read and write outside the coordination surface stay on the service client.
  They are a single implementation already — this is not a fallback, and C2's
  guard test does not flag them. Port them only if the meter shows they matter.
