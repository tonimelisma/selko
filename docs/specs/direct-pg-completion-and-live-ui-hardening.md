# Direct-PG Completion and Live-UI Hardening

**Status:** planned — remediation of PRs #262–#278 (Aug 6–9 batch)

**Supersedes the "Status: implemented" line of**
[`direct-postgres-work-transport.md`](direct-postgres-work-transport.md). That
line is wrong. Increments 3, 4 and 5 of that spec shipped as unreachable code.
This document finishes them and repairs the defects found in the same review.

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
| Inc2 — 1 claim loop + N semaphore executors | The loop collapse happened. **No semaphore was added.** Acquisition and attachment are now strictly serial. `email_acquisition_concurrency` and `email_attachment_concurrency` are read nowhere outside `config.py`. |

The measured egress improvement (929 → 96 MB/day) came entirely from increments
0–2. Every worker database call still crosses PostgREST at ~1,690 bytes.

**Consequence:** the per-mailbox cost curve in
[`direct-postgres-work-transport.md`](direct-postgres-work-transport.md) §1.3 is
unchanged. At 373 MB/mailbox/month, twelve mailboxes still exhaust both 5 GB
allowances. This work is what moves that curve.

---

## 2. Rules that apply to every increment

1. Source code → worktree + feature branch + PR, per `CLAUDE.md`. Branch names
   are given per increment.
2. Run `uv run pytest backend/tests/ -m "not integration"` before every PR.
   It must stay green.
3. Every increment adds a test that **fails before the change and passes after**.
   Write the test first and watch it fail. If it passes before your change, the
   test is wrong.
4. Never mark an increment done because the code exists. Done means the DoD
   command in that increment printed the stated output.
5. Do not update any spec's `Status:` line until its DoD command has been run
   and its output pasted into the PR body.

---

## 3. Increment order

C1 → C2 → C3 are a chain and must land in order. C4–C9 are independent of each
other and of the chain; take them in any order.

| # | Title | Depends on | Est. |
|---|---|---|---|
| C1 | Make the pool real and fail loudly | — | 0.5 d |
| C2 | Wire the pool into every claim path | C1 | 1 d |
| C3 | Implement `WorkListener` for real | C2 | 1 d |
| C4 | Restore executor concurrency | — | 0.5 d |
| C5 | Bound the LLM claim loop | — | 0.5 d |
| C6 | Realtime auth refresh + lifecycle catch-up | — | 1 d |
| C7 | Contain Broadcast fan-out | — | 0.5 d |
| C8 | Make the schema/code gate real | — | 0.5 d |
| C9 | Android test parity | — | 0.5 d |

---

## Increment C1 — Make the pool real and fail loudly

**Branch:** `fix/pg-pool-wiring` · **Worktree:** `selko-fix-pg-pool-wiring`

**Why:** `asyncpg` was never installed, and three separate code paths downgrade
a missing transport to a warning. The system reports healthy while running the
expensive transport it was built to replace.

### C1.1 Add the dependency

From the worktree root:

```bash
uv add asyncpg
```

Confirm `asyncpg` now appears in `pyproject.toml` under `[project] dependencies`
and in `uv.lock`. Commit both files.

### C1.2 Add the keepalive settings that H3 requires

`backend/selko/services/pg.py`, in `create_pool`. The current call passes no TCP
keepalive settings at all, so hazard H3 (idle socket dropped by NAT, listener
goes deaf on a socket that still looks open) has no mitigation.

Replace the body of `create_pool` with:

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

**Note on `connect_kwargs`:** asyncpg forwards unknown keyword arguments from
`create_pool` to `connect`. If your installed asyncpg version rejects
`connect_kwargs`, pass the four keepalive keys directly as top-level kwargs to
`asyncpg.create_pool` instead — asyncpg forwards them to the underlying
connection. Verify with the C1 integration test below; do not guess.

### C1.3 Replace `command_timeout=10` with a config value

`backend/selko/config.py`. Add to the `Config` dataclass next to
`pg_keepalive_seconds` (line 138):

```python
    pg_command_timeout_seconds: int = 30
```

And in the loader next to line 525:

```python
        pg_command_timeout_seconds=int(getenv("PG_COMMAND_TIMEOUT_SECONDS", "30")),
```

10 seconds is too tight for `upsert_discovered_email_items` with a 100-row page
across the Oregon ↔ us-east-1 split.

### C1.4 Fail startup instead of degrading silently

`backend/selko/api/app.py`, lines 107–121. Replace the whole block with:

```python
        # Inc3/C1: the direct-pg transport is mandatory when background
        # processing is on. A missing URL or a failed pool is a configuration
        # error, not a reason to fall back to the transport this replaced —
        # falling back silently restores the 1,690 B/call cost with no signal.
        pg_pool = await create_pool(config)
        logger.info("Supavisor session pooler connected")
```

`create_pool` already calls `assert_session_mode_url`, which raises
`ConfigurationError` on a missing, malformed, transaction-mode or IPv6-direct
URL. Delete the now-unused `assert_session_mode_url` import from `app.py` if
nothing else in that file uses it.

Then fix the shutdown block at lines 176–182:

```python
        if pg_pool is not None:
            await pg_pool.close()
            logger.info("Pg pool closed")
```

Remove the `if 'pg_pool' in locals()` guard and the bare `except Exception: pass`.
`pg_pool` is assigned unconditionally in the same branch, and a failure to close
a pool during shutdown must be logged, not swallowed.

Because `pg_pool` is now assigned inside the `if config.enable_background_processing`
branch but referenced in the shutdown branch, initialise it to `None` alongside
`worker_pool` and `ingestion_runtime` wherever those are initialised earlier in
`lifespan`.

### C1.5 Set the URL in every environment file

Get the URL from Supabase Dashboard → project → **Connect** → **Session pooler**.
It is a `*.pooler.supabase.com` host on port **5432**.

- Do **not** use "Direct connection" (`db.*.supabase.co` — IPv6-only, H4).
- Do **not** use "Transaction pooler" (port 6543 — breaks `LISTEN`, H1).

Set `SUPABASE_DB_URL` in:

| File | Project |
|---|---|
| `.env` | local (`postgresql://postgres:postgres@localhost:54322/postgres`) |
| `.env.test` | staging `lxmysergoeaegxlyfzwk` session pooler |
| `.env.production` | production `khahcozfbnpykspvatrg` session pooler |

**Environment separation is absolute.** Never put the production URL in `.env`
or `.env.test`. The production database password is a distinct secret from
`SUPABASE_SERVICE_ROLE_KEY` (H5).

### C1.6 Report the transport on a health surface

`backend/selko/api/routes/health.py`, in the `/health/egress` handler. Add to
the response:

```python
        "transport": "asyncpg" if _pg_pool_is_live() else "postgrest",
```

Add the field to `HealthEgressResponse` in `backend/selko/api/schemas/common.py`
as `transport: str`. Obtain the pool from wherever `app.state` holds it — if it
is not on `app.state` yet, put it there in `lifespan` (`app.state.pg_pool = pg_pool`)
as part of this increment.

The reason this field exists: the review that produced this spec could not tell
from any running surface which transport was live. That must never be true again.

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
    # Keepalives present under whichever form this asyncpg version accepts
    flat = {**captured, **captured.get("connect_kwargs", {})}
    assert flat["keepalives"] == 1
    assert flat["keepalives_idle"] == 60
```

`backend/tests/test_config.py` — add:

```python
def test_startup_requires_db_url_when_background_processing_on(monkeypatch):
    """C1.4: a missing SUPABASE_DB_URL must fail startup, not degrade."""
    from selko.services.pg import ConfigurationError, assert_session_mode_url
    with pytest.raises(ConfigurationError):
        assert_session_mode_url(None)
```

### DoD

```bash
uv run pytest backend/tests/ -m "not integration" -q
```
must print `PASSED` with no failures, and:

```bash
uv run python -c "import asyncpg; print(asyncpg.__version__)"
```
must print a version.

Start the API locally with `ENABLE_BACKGROUND_PROCESSING=true` and
`SUPABASE_DB_URL` **unset**. Startup must **fail** with a `ConfigurationError`
naming `SUPABASE_DB_URL`. Then set it and confirm the log line
`Supavisor session pooler connected` appears, and that
`curl localhost:8000/health/egress | jq .transport` prints `"asyncpg"`.

### Rollback

Revert the PR. `git revert` restores the warning-and-continue behaviour. The
`uv add asyncpg` is harmless if left in place.

---

## Increment C2 — Wire the pool into every claim path

**Branch:** `fix/pg-pool-call-sites` · **Worktree:** `selko-fix-pg-pool-call-sites`
**Depends on:** C1

**Why:** the `*_via_pool` methods exist and are correct. Nothing calls them.

### C2.1 Fix the missing import — do this first

`backend/selko/workers/pool.py`, the import block at lines 37–42. It currently
reads:

```python
from selko.services.emails import (
    EmailError,
    claim_pending_email,
    complete_email_processing,
    fail_email_processing,
)
```

Add `claim_pending_email_via_pool`:

```python
from selko.services.emails import (
    EmailError,
    claim_pending_email,
    claim_pending_email_via_pool,
    complete_email_processing,
    fail_email_processing,
)
```

Without this, line 374 raises `NameError` the instant the pool becomes non-`None`.
`NameError` is not `EmailError`, so it escapes the handler at line 386 into the
scheduler's generic `except Exception`, which logs and sleeps 5 s forever.
**Email extraction would stop entirely and the only symptom would be a repeating
log line.** This single missing name is why C2.1 comes before everything else in
this increment.

### C2.2 Delete the duplicated assignment

`backend/selko/workers/pool.py:98-99`:

```python
        self.pg_pool = pg_pool
        self.pg_pool = pg_pool
```

Delete one of them.

### C2.3 Pass the pool to `WorkerPool`

`backend/selko/api/app.py:124`:

```python
        worker_pool = WorkerPool(
            num_workers=config.worker_pool_size,
            idle_sleep_seconds=config.worker_idle_sleep_seconds,
            error_backoff_seconds=config.worker_error_backoff_seconds,
            pg_pool=pg_pool,
        )
```

### C2.4 Give `IngestionRuntime` a pool parameter and pass it down

`backend/selko/workers/ingestion_runtime.py:61`:

```python
    def __init__(self, client: Client, config: Config, *, instance_id: str | None = None, pg_pool=None):
        self.client = client
        self.config = config
        self.pg_pool = pg_pool
        ...
```

Find where `IngestionRuntime` constructs `EmailIngestionWorker` (search for
`EmailIngestionWorker(` in that file) and pass `pg_pool=self.pg_pool` through.

`backend/selko/workers/email_ingestion.py:115`:

```python
        self.repository = EmailIngestionRepository(client, config, pg_pool=pg_pool)
```

with `pg_pool` added to `EmailIngestionWorker.__init__` as a keyword-only
parameter defaulting to `None`.

`backend/selko/api/app.py:150`:

```python
        ingestion_runtime = IngestionRuntime(service_client, config, pg_pool=pg_pool)
```

### C2.5 Route the repository methods through the pool

`backend/selko/services/email_ingestion.py`. The sync methods and the
`*_via_pool` methods are currently two parallel APIs. Collapse them: keep the
`*_via_pool` bodies, and make each sync method's caller choose.

The call sites are in `backend/selko/workers/email_ingestion.py`. They currently
look like:

```python
        item = await asyncio.to_thread(self.repository.claim_item, self.worker_id)
```

Change each to:

```python
        if self.repository.pg_pool is not None:
            item = await self.repository.claim_item_via_pool(self.worker_id)
        else:
            item = await asyncio.to_thread(self.repository.claim_item, self.worker_id)
```

Apply the same shape to all seven pairs:

| Sync method | Pool method | Call site |
|---|---|---|
| `claim_due_sync` | `claim_due_sync_via_pool` | `coordinator_loop` |
| `claim_due_reconciliation` | `claim_due_reconciliation_via_pool` | `coordinator_loop` |
| `heartbeat_sync` | `heartbeat_sync_via_pool` | `require_heartbeat` |
| `complete_sync` | `complete_sync_via_pool` | `coordinator_loop` |
| `claim_item` | `claim_item_via_pool` | `run_acquisition_once:628` |
| `claim_attachment` | `claim_attachment_via_pool` | `run_attachment_once:706` |
| `upsert_discovered` | `upsert_discovered_via_pool` | discovery paths |

`require_heartbeat` is currently synchronous. Make it `async def` and `await`
its callers; find them with `grep -rn "require_heartbeat" backend/`.

### C2.6 Fix the jsonb parameter in `upsert_discovered_via_pool`

`backend/selko/services/email_ingestion.py:450`. It passes `json.dumps(page)` —
a Python `str` — to a `jsonb` parameter. This code has never executed, so the
type handling is unverified. Make it explicit by casting in SQL:

```python
    async def upsert_discovered_via_pool(self, claim, items, *, cursor=None, folder_id=None):
        import json
        page = list(items)
        val = await self.pg_pool.fetchrow(
            "SELECT * FROM public.upsert_discovered_email_items($1, $2, $3::jsonb, $4, $5)",
            claim.integration_id, claim.run_id, json.dumps(page), cursor, folder_id,
        )
        return dict(val) if val else {"inserted_count": 0}
```

The `$3::jsonb` cast makes the text→jsonb conversion explicit and independent of
asyncpg's codec defaults. Verify with the integration test below — do not assume.

### Tests

`backend/tests/test_workers.py` — a wiring test, because this whole class of
defect was invisible to the existing suite:

```python
@pytest.mark.asyncio
async def test_worker_pool_uses_pool_when_provided(monkeypatch):
    """C2: a configured pg_pool must actually reach the claim call."""
    calls = []

    async def fake_claim_via_pool(pool, worker_id, lock_duration_seconds=300):
        calls.append("pool")
        return None

    monkeypatch.setattr(
        "selko.workers.pool.claim_approved_event_for_sync_via_pool",
        fake_claim_via_pool,
    )

    sentinel_pool = object()
    pool = WorkerPool(num_workers=1, pg_pool=sentinel_pool)
    pool.config = load_config()
    pool._client = MagicMock()
    await pool._process_any_work("test-worker")

    assert calls == ["pool"], "claim did not go through the pg pool"


def test_pool_imports_every_via_pool_name_it_calls():
    """C2.1 regression: claim_pending_email_via_pool was called, never imported."""
    import selko.workers.pool as mod
    assert hasattr(mod, "claim_pending_email_via_pool")
    assert hasattr(mod, "claim_approved_event_for_sync_via_pool")
```

`backend/tests/test_email_ingestion_v2.py` — assert the repository honours the
pool for each of the seven pairs. Parametrise:

```python
@pytest.mark.parametrize("sync_name,pool_name", [
    ("claim_due_sync", "claim_due_sync_via_pool"),
    ("claim_due_reconciliation", "claim_due_reconciliation_via_pool"),
    ("heartbeat_sync", "heartbeat_sync_via_pool"),
    ("complete_sync", "complete_sync_via_pool"),
    ("claim_item", "claim_item_via_pool"),
    ("claim_attachment", "claim_attachment_via_pool"),
    ("upsert_discovered", "upsert_discovered_via_pool"),
])
def test_repository_exposes_both_transports(sync_name, pool_name):
    assert hasattr(EmailIngestionRepository, sync_name)
    assert hasattr(EmailIngestionRepository, pool_name)
```

**Integration test — this is the one that matters.** Add to
`backend/tests/test_integration_ingestion_drill.py`, marked `integration`, run
against local Supabase (`supabase start`):

```python
@pytest.mark.integration
@pytest.mark.asyncio
async def test_claim_paths_return_identical_shapes_over_both_transports():
    """The two transports must be interchangeable, not merely both present."""
    # Seed one claimable row, claim via PostgREST, roll back, claim via pool,
    # and assert the returned dicts have identical keys and values.
```

Write it out fully — this is the only test in the suite that can prove the
`SELECT * FROM public.fn($1,$2)` form matches what PostgREST returned.

### DoD

```bash
uv run pytest backend/tests/ -m "not integration" -q
```
green, and with local Supabase running:

```bash
uv run pytest backend/tests/ -m integration -q
```
green.

Then run the API locally against local Supabase with background processing on
for 5 minutes and confirm:

```bash
curl -s localhost:8000/health/egress | jq '.top_operations[] | select(.operation | test("rpc"))'
```

prints **no** `claim_*` RPC operations. Paste that output into the PR body.

### Rollback

Revert the PR. Leases make partial processing safe: any row claimed over the
pool and not completed has its lease expire and is reclaimed over PostgREST.

---

## Increment C3 — Implement `WorkListener` for real

**Branch:** `feat/pg-work-listener` · **Worktree:** `selko-feat-pg-work-listener`
**Depends on:** C2

**Why:** migration `20260809000002` installs four `pg_notify('selko_work', …)`
triggers. Nothing has ever issued `LISTEN`. Until this lands, the safety poll is
the only wake mechanism and the design's central claim — "the backend does not
ask whether there is work, it is told" — is false.

### C3.1 Replace the stub

`backend/selko/services/pg.py`. Replace `WorkListener.start`, `stop`, `status`
and `_on_notify` in full:

```python
class WorkListener:
    """Dedicated LISTEN connection feeding asyncio.Events per work type.

    Owns its own connection, NOT a pool member — a pool connection could be
    handed to a query and lose its LISTEN registration.

    Liveness (H3): every PG_LISTENER_HEARTBEAT_SECONDS it emits a self-NOTIFY
    on the 'selko_work' channel with payload 'heartbeat' and asserts receipt
    within 10s. A miss means the socket is dead-but-open; the connection is
    torn down and reconnected with exponential backoff (1s, 2s, 4s … capped at
    60s). Reconnect always re-issues LISTEN before declaring itself healthy.
    """

    CHANNEL = "selko_work"
    HEARTBEAT_PAYLOAD = "heartbeat"
    WORK_TYPES = ("email_pending", "event_approved", "item_pending", "attachment_pending")

    def __init__(self, config, pg_pool=None):
        self.config = config
        self.pg_pool = pg_pool
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

Add `import time` at the top of `pg.py`. Delete the `__import__("time")` call.

**`status()` must never report `connected: True` unless a `LISTEN` is
registered on a live connection.** The stub did exactly that, and it is why this
increment exists.

### C3.2 Instantiate it and feed the schedulers

`backend/selko/api/app.py`, after the pool is created:

```python
        from selko.services.pg import WorkListener

        work_listener = WorkListener(config, pg_pool=pg_pool)
        await work_listener.start()
        app.state.work_listener = work_listener
```

Pass it to both schedulers:

```python
        worker_pool = WorkerPool(..., pg_pool=pg_pool, work_listener=work_listener)
        ingestion_runtime = IngestionRuntime(service_client, config, pg_pool=pg_pool, work_listener=work_listener)
```

Stop it in the shutdown branch **after** both schedulers stop and **before** the
pool closes.

### C3.3 Wait on the listener event in the idle path

`backend/selko/workers/pool.py`, `_scheduler_loop`, the idle branch at lines
264–276. The scheduler currently waits on `self._nudge_event` with a
`_tick_seconds()` timeout. Wait on **either** the in-process nudge or the
listener event, with the safety poll as the timeout:

```python
                # --- idle: wait for nudge, notification, or safety poll ---
                waiters = [asyncio.create_task(self._nudge_event.wait())]
                if self._work_listener is not None:
                    for work_type in ("event_approved", "email_pending"):
                        waiters.append(
                            asyncio.create_task(self._work_listener.event_for(work_type).wait())
                        )
                timeout = float(self.config.worker_safety_poll_seconds)
                done, pending = await asyncio.wait(
                    waiters, timeout=timeout, return_when=asyncio.FIRST_COMPLETED
                )
                for task in pending:
                    task.cancel()
                if self._nudge_event.is_set():
                    self._nudge_event.clear()
                if self._work_listener is not None:
                    for work_type in ("event_approved", "email_pending"):
                        self._work_listener.event_for(work_type).clear()
```

`worker_safety_poll_seconds` already has a hard floor of 60 s
(`config.py:527`). **Do not add a way to disable it** (H2): `NOTIFY` is not
durable, and the poll is what turns a missed notification into latency rather
than into stranded work.

Apply the same pattern to `_claim_loop` in
`backend/selko/workers/email_ingestion.py:829-855`, waiting on
`item_pending` for the acquisition loop and `attachment_pending` for the
attachment loop.

### C3.4 Expose listener status on `/health/ingestion`

Add `"listener": app.state.work_listener.status()` to the
`/health/ingestion` payload, and the corresponding field to
`HealthIngestionResponse`.

### Tests

`backend/tests/test_pg.py`:

```python
@pytest.mark.asyncio
async def test_listener_sets_event_for_payload():
    listener = WorkListener(config=SimpleNamespace(supabase_db_url="postgresql://u:p@x.pooler.supabase.com:5432/d"))
    event = listener.event_for("email_pending")
    assert not event.is_set()
    listener._on_notify(None, 1, "selko_work", "email_pending")
    assert event.is_set()


@pytest.mark.asyncio
async def test_listener_heartbeat_payload_does_not_set_work_events():
    listener = WorkListener(config=...)
    work = listener.event_for("email_pending")
    listener._on_notify(None, 1, "selko_work", "heartbeat")
    assert listener._heartbeat_seen.is_set()
    assert not work.is_set()


def test_status_is_false_before_start():
    """Regression: the Inc5 stub reported connected=True without a LISTEN."""
    listener = WorkListener(config=...)
    assert listener.status()["connected"] is False
```

**Integration tests** in `test_integration_ingestion_drill.py`, all
`@pytest.mark.integration` against local Supabase:

1. **H2 — durability.** Stop the listener, insert a row that would fire a
   trigger, restart nothing, and assert the work is processed within
   `worker_safety_poll_seconds`. This proves a missed notification costs latency
   and never work.
2. **H3 — dead socket.** Terminate the listener's backend from another
   connection (`SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE
   application_name = 'selko-worker'`), then assert `status()["reconnects"]`
   increments and a subsequent `NOTIFY` is delivered.
3. **§3.1 — batch collapse.** Insert 100 `email_ingestion_items` in one
   transaction and assert exactly **one** notification arrives.
4. **D3 — no double-processing.** Run two listeners against one database, fire
   one notification, and assert the row is claimed once.

### DoD

Both test commands green. Then, against local Supabase with the API running:

```bash
psql "$SUPABASE_DB_URL" -c "SELECT pg_notify('selko_work','event_approved')"
```

The API log must show a scheduler wake within one second, and
`curl -s localhost:8000/health/ingestion | jq .listener` must show
`"connected": true` with a recent `last_notification_at`.

Run idle for 30 minutes and confirm via `/health/egress` that
`calls_per_second` for supabase is below `1 / worker_safety_poll_seconds × 2`.
Paste the snapshot into the PR body.

### Rollback

Revert the PR. The schedulers fall back to the safety poll, which is the
current (working) behaviour. Leave migration `20260809000002` in place —
unconsumed `pg_notify` is free.

---

## Increment C4 — Restore executor concurrency

**Branch:** `fix/ingestion-executor-concurrency` · **Worktree:** `selko-fix-ingestion-executor-concurrency`

**Why:** Inc2 collapsed N pollers to 1 loop, which was correct, but never added
the semaphore that was supposed to preserve throughput. Acquisition and
attachment are now strictly serial. `email_acquisition_concurrency` and
`email_attachment_concurrency` are read nowhere outside `config.py`.

### C4.1 Add the semaphores

`backend/selko/workers/email_ingestion.py`, in `EmailIngestionWorker.__init__`:

```python
        # Inc2/C4: concurrency multiplies executors, never pollers. One claim
        # loop per type; the semaphore bounds how many items are in flight.
        self._acquisition_semaphore = asyncio.Semaphore(
            max(config.email_acquisition_concurrency, 1)
        )
        self._attachment_semaphore = asyncio.Semaphore(
            max(config.email_attachment_concurrency, 1)
        )
        self._inflight: set[asyncio.Task] = set()
```

### C4.2 Acquire before claiming

This ordering is the whole point and it is the same defect as C5. Rewrite
`run_acquisition_once` (line 627):

```python
    async def run_acquisition_once(self) -> bool:
        # Acquire the executor slot BEFORE claiming. Claiming first would let
        # the drain loop claim faster than it can process, and every claimed
        # row holds a lease that expires while it waits.
        await self._acquisition_semaphore.acquire()
        try:
            if self.repository.pg_pool is not None:
                item = await self.repository.claim_item_via_pool(self.worker_id)
            else:
                item = await asyncio.to_thread(self.repository.claim_item, self.worker_id)
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

Move the existing body of `run_acquisition_once` (everything after the claim)
into a new `async def _process_acquisition_item(self, item) -> None`.

Apply the identical shape to `run_attachment_once` (line 705) with
`_attachment_semaphore` and `_process_attachment_item`.

### C4.3 Await in-flight work on stop

In the worker's stop path, after the loops exit:

```python
        if self._inflight:
            await asyncio.wait(self._inflight, timeout=30)
```

### C4.4 Correct the config docstrings

`backend/selko/config.py:122-126`. Replace the comment with:

```python
    # Executor width, NOT poller count. One claim loop per type drains the
    # queue; these bound how many items are processed concurrently. Raising
    # them does not increase database polling. (Inc2/C4)
    email_acquisition_concurrency: int = 2
    email_attachment_concurrency: int = 2
```

### Tests

`backend/tests/test_email_ingestion_v2.py`:

```python
@pytest.mark.asyncio
async def test_acquisition_respects_executor_width():
    """C4: concurrency 4 with 10 items — one claim loop, max 4 in flight, all 10 done."""
    # Arrange a repository whose claim_item returns 10 items then None.
    # Track peak concurrency inside _process_acquisition_item.
    assert peak_in_flight <= 4
    assert completed == 10


@pytest.mark.asyncio
async def test_claim_does_not_outrun_executors():
    """C4.2 regression: claiming before acquiring the slot let leases expire."""
    # With concurrency 1 and a processor that blocks, assert exactly one claim
    # has been issued while the first item is still in flight.
    assert claim_count == 1


def test_concurrency_config_is_actually_read():
    """Regression: after Inc2 these values were read nowhere outside config.py."""
    import subprocess
    out = subprocess.run(
        ["grep", "-rn", "email_acquisition_concurrency", "backend/selko/workers"],
        capture_output=True, text=True,
    ).stdout
    assert out.strip(), "email_acquisition_concurrency is not read by any worker"
```

### DoD

`uv run pytest backend/tests/ -m "not integration" -q` green, and
`grep -rn "email_acquisition_concurrency" backend/selko/workers/` returns at
least one hit.

### Rollback

Revert the PR. Behaviour returns to serial processing, which is slow but correct.

---

## Increment C5 — Bound the LLM claim loop

**Branch:** `fix/llm-claim-backpressure` · **Worktree:** `selko-fix-llm-claim-backpressure`

**Why:** [pool.py:373-385](../../backend/selko/workers/pool.py) claims an email,
fires a task, returns `True`, and immediately re-drains. The semaphore bounds
execution, not claiming. With the 578-email backlog named in the code comment,
578 tasks are created at once, each holding a 300 s lease. The comment's own
arithmetic — 8-wide, ~6 minutes — puts the tail at ~360 s against that 300 s
lease. Expired leases are reclaimable, so the same process re-extracts emails
that are already in flight: duplicate LLM spend and duplicate suggestions in the
user's review queue.

### C5.1 Acquire before claiming

`backend/selko/workers/pool.py`, `_process_any_work`, section 2. Replace lines
371–387 with:

```python
        # 2. LLM email extraction. The semaphore is acquired BEFORE the claim:
        # claiming first lets the drain loop outrun the executors, and every
        # claimed row holds a 300s lease that expires while it waits in the
        # queue — which makes the same email eligible for re-claiming and
        # re-extraction. Backpressure belongs at the claim, not at the work.
        if circuit_breaker.is_available("llm") and self._llm_semaphore is not None:
            acquired = False
            try:
                await asyncio.wait_for(self._llm_semaphore.acquire(), timeout=0.01)
                acquired = True
            except asyncio.TimeoutError:
                pass  # all executors busy; skip to the next work type

            if acquired:
                try:
                    if self.pg_pool is not None:
                        email = await claim_pending_email_via_pool(
                            self.pg_pool, worker_id, lock_duration_seconds=300
                        )
                    else:
                        email = claim_pending_email(
                            client, worker_id, lock_duration_seconds=300
                        )
                except EmailError as e:
                    self._llm_semaphore.release()
                    logger.error(f"{worker_id}: Error claiming email: {e}")
                    email = None
                except BaseException:
                    self._llm_semaphore.release()
                    raise

                if email is None:
                    self._llm_semaphore.release()
                else:
                    task = asyncio.create_task(
                        self._process_email(self._get_client(), worker_id, email)
                    )
                    self._email_tasks.add(task)
                    task.add_done_callback(self._email_tasks.discard)
                    task.add_done_callback(lambda _: self._llm_semaphore.release())
                    return True
```

Delete `_process_email_with_semaphore` (lines 321–328) — the semaphore is now
held by the claim path, and taking it twice would deadlock.

### C5.2 Make the lease outlast the queue

The lease must cover worst-case queue wait plus processing. With backpressure in
place the queue wait is bounded, but make the relationship explicit rather than
leaving `300` as a literal in two places.

`backend/selko/config.py`, add:

```python
    llm_claim_lease_seconds: int = 900
```
```python
        llm_claim_lease_seconds=int(getenv("LLM_CLAIM_LEASE_SECONDS", "900")),
```

Use `self.config.llm_claim_lease_seconds` in place of the literal `300` at both
claim call sites in `_process_any_work`.

### Tests

`backend/tests/test_workers.py`:

```python
@pytest.mark.asyncio
async def test_llm_claims_never_exceed_executor_width():
    """C5 regression: 578 claims were issued against an 8-wide semaphore."""
    # concurrency 2, processor blocks on an event, 10 emails available.
    # Drain repeatedly; assert claim_count never exceeds 2 while blocked.
    assert claim_count <= 2


@pytest.mark.asyncio
async def test_semaphore_released_when_claim_returns_none():
    """A no-work claim must not leak a permit."""
    # Drain 100 times against an empty queue; assert the semaphore is full.
    assert pool._llm_semaphore._value == expected_width


@pytest.mark.asyncio
async def test_semaphore_released_when_claim_raises():
    """An EmailError must not leak a permit."""
```

### DoD

`uv run pytest backend/tests/ -m "not integration" -q` green. Seed 50 pending
emails locally, run the API with `LLM_EXTRACTION_CONCURRENCY=4`, and confirm from
the log that no more than 4 `claimed email` lines appear without a matching
`Completed email` line.

### Rollback

Revert the PR.

---

## Increment C6 — Realtime auth refresh and lifecycle catch-up

**Branch:** `fix/live-updates-auth-lifecycle` · **Worktree:** `selko-fix-live-updates-auth-lifecycle`

**Why:** all three clients call `setAuth` exactly once, at channel start. Private
Broadcast channels authorize per-JWT against the `realtime.messages` RLS policy
created in `20260809000003`. When the access token expires (~1 h), the channel
stops delivering and nothing retries. Separately, the web tab-visibility
catch-up is a no-op, and no client handles a terminal channel state.

### C6.1 Web — refresh auth on token rotation

`frontend/src/lib/live-updates.js`. Add an exported function:

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

`frontend/src/lib/stores.js:36`, inside the existing `onAuthStateChange`
handler:

```javascript
	supabase.auth.onAuthStateChange((event, session) => {
		// ... existing body ...
		if (event === 'TOKEN_REFRESHED' || event === 'SIGNED_IN') {
			import('$lib/live-updates.js').then((m) => m.refreshAuth(session?.access_token ?? null));
		}
	});
```

### C6.2 Web — make lifecycle catch-up actually refetch

`frontend/src/lib/live-updates.js`. Add:

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

`frontend/src/routes/app/+layout.svelte`, in `onVisible` and in the `online` and
`focus` handlers, replace `liveUpdates.start(currentUid)` with:

```javascript
				liveUpdates.catchUp();
```

`start()` returns early when `userId === uid && channel` ([live-updates.js:104](../../frontend/src/lib/live-updates.js)),
which is why the current call does nothing.

### C6.3 Web — handle terminal channel states

`frontend/src/lib/live-updates.js`, in the `channel.subscribe` callback:

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
			// Rejoin with backoff, and catch up from the database on success —
			// the database is the source of truth, the channel is a hint.
			const delay = Math.min(1000 * 2 ** rejoinAttempts, 60000);
			rejoinAttempts += 1;
			setTimeout(() => {
				const uid = userId;
				if (!uid) return;
				stop().then(() => start(uid));
			}, delay);
		}
	});
```

Guard against `stop()` clearing `userId` before the rejoin reads it by
capturing `const uid = userId;` before calling `stop()`.

### C6.4 iOS — same three fixes

`ios/Selko/Core/LiveUpdates/LiveUpdateService.swift`:

- Add `func refreshAuth(_ token: String) async` calling
  `await supabase.realtimeV2.setAuth(token)`, and call it from wherever the app
  observes `AuthChangeEvent.tokenRefreshed`.
- Add `func catchUp() async` that emits a synthetic invalidation for every
  resource in `["events", "event_sources", "emails", "integrations"]`, and call
  it from the scene-active lifecycle hook instead of `start(userId:)`.
- `subscribeWithError()` currently sets `connectionStatus = "error: …"` and
  stops (line 69). Add a rejoin with the same capped exponential backoff.

### C6.5 Android — same three fixes

`android/app/src/main/java/net/melisma/selko/data/repository/LiveUpdateRepository.kt`:

- Re-call `supabaseClient.realtime.setAuth(token)` on session refresh; observe
  `supabaseClient.auth.sessionStatus` and re-auth on
  `SessionStatus.Authenticated`.
- Add a `catchUp()` that emits synthetic invalidations, called from
  `ON_START` in the lifecycle observer.
- Handle `RealtimeChannel.Status.CLOSED` / errors with a backoff rejoin.

### Tests

`frontend/src/lib/services/__tests__/` — add `live-updates.test.js`:

```javascript
it('re-authorizes realtime on TOKEN_REFRESHED', async () => {
	// assert supabase.realtime.setAuth called with the new token
});

it('catchUp refetches even when the channel is already open', async () => {
	// subscribe a listener, call start(uid) twice, then catchUp();
	// assert the listener fired for catchUp but not for the second start
});

it('rejoins after CHANNEL_ERROR', async () => {
	// drive the subscribe callback with CHANNEL_ERROR, advance timers,
	// assert stop+start were called
});
```

iOS: add cases to `ios/SelkoTests/` covering `catchUp()` emitting for all four
resources and `refreshAuth` calling through.

Android: add cases to
`android/app/src/test/java/net/melisma/selko/data/repository/LiveUpdateRepositoryTest.kt`
(create the file) for the same three behaviours.

### DoD

- `cd frontend && npm run test:unit` and `npm run check` pass.
- iOS: `xcodebuild test -project ios/iOS.xcodeproj -scheme iOS -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -resultBundlePath ios/TestResults.xcresult` passes. `rm -rf ios/TestResults.xcresult` first.
- Android: `cd android && ./gradlew testDebugUnitTest` passes.
- Screenshots: this increment changes no UI. **Skip screenshots.**
- Manual check, web only: sign in, open devtools, run
  `await supabase.auth.refreshSession()`, then approve an event from another
  browser and confirm the first tab updates.

### Rollback

Revert the PR per platform — the three platform changes are independent and can
be reverted individually.

---

## Increment C7 — Contain Broadcast fan-out

**Branch:** `fix/broadcast-fanout` · **Worktree:** `selko-fix-broadcast-fanout`

**Why:** the direct-pg spec relies on Postgres collapsing duplicate
`(channel, payload)` pairs per transaction for `pg_notify` (§3.1).
**`realtime.send` does not collapse.** The per-row triggers in
`20260809000003` emit one message per row, so any multi-row write —
retroactive sender-ignore, reconcile status sweeps, bulk reject — fans out one
Broadcast message per affected row against a 2,000,000/month quota. This is the
same cost shape the Aug 6–9 work was undertaken to remove.

### C7.1 Measure before changing

```sql
-- against local Supabase, after seeding
BEGIN;
UPDATE public.events SET status = 'rejected' WHERE user_id = '<uid>' AND status = 'pending_review';
COMMIT;
SELECT count(*) FROM realtime.messages WHERE topic = 'user:<uid>:selko-changes';
```

Record the row count and the message count in the PR body. If they are equal,
the defect is confirmed.

### C7.2 Collapse to one message per transaction per resource

New migration `supabase/migrations/20260811000001_broadcast_fanout_collapse.sql`.

Use a transaction-local guard so the first row of a statement sends and the rest
do not:

```sql
-- Broadcast fan-out collapse: one message per (transaction, resource, user).
-- realtime.send does NOT deduplicate the way pg_notify does, so per-row
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

    -- One send per (transaction, user, resource). A transaction-local GUC is
    -- the guard: it is reset automatically at commit or rollback.
    v_guard := 'selko.bc_' || replace(p_user_id::text, '-', '') || '_' || p_resource;
    IF current_setting(v_guard, true) = '1' THEN
        RETURN;
    END IF;
    PERFORM set_config(v_guard, '1', true);

    v_topic := 'user:' || p_user_id::text || ':selko-changes';
    v_payload := jsonb_build_object(
        'resource', p_resource,
        'operation', p_operation,
        -- entity_id is omitted for collapsed sends: consumers refetch the
        -- whole resource anyway, and a single id would be misleading when the
        -- transaction touched many rows.
        'occurred_at', (now() AT TIME ZONE 'utc')::text
    );
    PERFORM realtime.send(v_payload, 'invalidate', v_topic, true);
END;
$$;

REVOKE ALL ON FUNCTION public.broadcast_user_ui_change(uuid, text, text, uuid) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION public.broadcast_user_ui_change(uuid, text, text, uuid) TO service_role;
GRANT EXECUTE ON FUNCTION public.broadcast_user_ui_change(uuid, text, text, uuid) TO authenticated;
```

Consumers already treat the payload as an invalidation hint and refetch through
RLS queries, so dropping `entity_id` costs nothing. Confirm this by reading
`handleInvalidate` in `frontend/src/lib/live-updates.js:86` — it uses only
`inv.resource`.

### C7.3 Narrow the events UPDATE trigger

Same migration. `trg_events_broadcast_upd` is `AFTER UPDATE` with **no column
list**, so it fires on every column change including `lease_expires_at`
churn:

```sql
DROP TRIGGER IF EXISTS trg_events_broadcast_upd ON public.events;
CREATE TRIGGER trg_events_broadcast_upd
    AFTER UPDATE OF status, title, start_datetime, end_datetime, sync_status
    ON public.events
    FOR EACH ROW EXECUTE FUNCTION public.trg_events_broadcast();
```

### C7.4 Remove the duplicated condition

Same migration, in `trg_events_broadcast`. The body currently tests
`NEW.status IS DISTINCT FROM OLD.status` twice. Recreate the function with the
duplicate removed:

```sql
        IF (NEW.status IS DISTINCT FROM OLD.status
            OR NEW.title IS DISTINCT FROM OLD.title
            OR NEW.start_datetime IS DISTINCT FROM OLD.start_datetime
            OR NEW.end_datetime IS DISTINCT FROM OLD.end_datetime
            OR NEW.sync_status IS DISTINCT FROM OLD.sync_status) THEN
```

### Tests

New file `backend/tests/test_broadcast_fanout.py`, `@pytest.mark.integration`:

```python
@pytest.mark.integration
def test_bulk_update_emits_one_broadcast_per_resource(supabase_local):
    """C7: 50 rows updated in one transaction must produce one message."""
    # seed 50 pending events for one user
    # update all 50 in a single transaction
    # assert exactly 1 row in realtime.messages for that topic
```

### DoD

Run the C7.1 measurement again after the migration. Row count 50, message count
1. Paste both before and after into the PR body.

`uv run pytest backend/tests/ -m "not integration" -q` green.

Apply to staging first: `supabase db push` against staging, re-run the
measurement there, then production.

### Rollback

The migration replaces a function and a trigger. Write the inverse migration
(restore the pre-C7 function body from `20260809000003`) rather than reverting
the PR, since the schema has already moved.

---

## Increment C8 — Make the schema/code gate real

**Branch:** `fix/schema-compat-gate` · **Worktree:** `selko-fix-schema-compat-gate`

**Why:** [`scripts/assert-schema-code-compat.sh`](../../scripts/assert-schema-code-compat.sh)
claims the wrong deploy order is "mechanically impossible". It is not. Default
mode always exits 0. `--linked` exits 0 when the CLI is missing or when the list
command fails. It compares counts rather than versions, so a remote with the same
number of *different* migrations passes. It invokes
`supabase migration list --linked` twice, and `grep -c "\.sql"` counts against a
version table that contains no `.sql` strings.

This is the mechanism intended to prevent the code/schema divergence incident
recorded in [`egress-and-work-scheduling.md`](egress-and-work-scheduling.md).

### C8.1 Rewrite the script

Replace the file entirely:

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

# Local versions are the leading timestamp of each migration filename.
LOCAL_VERSIONS=$(ls -1 "$MIGR_DIR"/*.sql | xargs -n1 basename | cut -d_ -f1 | sort -u)
LOCAL_COUNT=$(echo "$LOCAL_VERSIONS" | grep -c . || true)
echo "Local migration versions: $LOCAL_COUNT"

if ! REMOTE_RAW=$(supabase migration list --linked 2>&1); then
  echo "❌ FAIL: could not list linked migrations."
  echo "   Run 'supabase link' and export SUPABASE_ACCESS_TOKEN."
  echo "$REMOTE_RAW"
  exit 1
fi

# The table prints the remote version in its own column; extract bare
# 14-digit timestamps wherever they appear.
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

`docs/ci-cd.md` already describes running this before a staging or production
`supabase db push`. Update that section to state that `--linked` is the only
supported invocation and that a non-zero exit blocks the deploy.

### Tests

Shell scripts are not covered by the Python suite. Verify by hand and record the
output in the PR body:

1. `./scripts/assert-schema-code-compat.sh` → must fail with the `--linked`
   message.
2. With `supabase link` pointed at staging and all migrations pushed →
   must print `✅` and exit 0.
3. Create an empty `supabase/migrations/29999999999999_probe.sql`, re-run →
   must fail and name `29999999999999`. Delete the probe file afterwards.

### DoD

All three manual checks produce the stated result. Paste all three outputs into
the PR body.

### Rollback

Revert the PR. The previous script always passed, so reverting cannot break a
deploy — it only removes the check.

---

## Increment C9 — Android test parity

**Branch:** `test/android-review-parity` · **Worktree:** `selko-test-android-review-parity`

**Why:** across `46750d5d..78d06bb2`, `ReviewQueueViewModel.kt` gained 163 lines
and `EventDetailViewModel.kt` 132, plus a new `LiveUpdateRepository.kt` — and
`ReviewQueueViewModelTest.kt` and `EventDetailViewModelTest.kt` were not touched
once. PR #278 fixed a race in Android's `showRejectUndo` and shipped only iOS
tests. `CLAUDE.md` requires a regression test in the module fixed.

### C9.1 Reject-undo tests

`android/app/src/test/java/net/melisma/selko/ui/screens/review/ReviewQueueViewModelTest.kt`.
Mirror the iOS cases in `ios/SelkoTests/Review/ReviewQueueViewModelTests.swift`:

- rejecting one event shows the snackbar with the singular string
- rejecting a second event within the 8 s window combines both and shows the
  plural string with count 2
- undo restores every combined event to the list
- `dismissUndo` after 8 s clears `showUndoSnackbar` and `lastRejectedEvents`
- **the #278 race:** two `showRejectUndo` calls in flight must not lose an event
  from `lastRejectedEvents` — this is the regression test that PR should have
  carried
- partial-success reject removes only the succeeded ids and still refetches

### C9.2 Live-update consumer tests

New file
`android/app/src/test/java/net/melisma/selko/data/repository/LiveUpdateRepositoryTest.kt`:

- an `invalidate` payload for `events` triggers exactly one refetch after debounce
- a payload for an unlisted resource is ignored
- a burst of five invalidations within the debounce window produces one refetch

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
green, with the new tests present in the report. Screenshots: **skip** — this
increment adds no UI.

### Rollback

Revert the PR. Tests only; no behaviour change.

---

## 4. After all increments land

1. Update the `Status:` line of
   [`direct-postgres-work-transport.md`](direct-postgres-work-transport.md) to
   name the PRs that actually completed Inc2–Inc5, replacing the current
   incorrect claim.
2. Update [`live-ui-updates.md`](live-ui-updates.md) with the auth-refresh and
   fan-out decisions from C6 and C7.
3. Add to `CLAUDE.md` under the DoD:
   - *Every new table in a migration must include `ENABLE ROW LEVEL SECURITY`
     in the same migration.* (`emails_body_html_backup` reached production
     without it, holding email bodies.)
   - *A PR may not mark a spec increment implemented unless its call sites are
     wired. "Next PR wires the call sites" is not a completed increment.*
4. Run the cutover verification in
   [`cutover-verification-20260807.md`](cutover-verification-20260807.md)
   against production, then re-measure `/health/egress` and Render
   `bandwidth_usage` for 24 hours and record `bytes_per_mailbox_per_day`.

## 5. Deferred, deliberately

- **Multi-instance.** `numInstances` stays 1, per D3 of the original spec. C3
  makes `LISTEN` strictly better than the in-process nudge if that changes, but
  claim contention at N>1 is still not exercised and is not claimed as supported.
- **Region colocation.** Render Oregon ↔ Supabase us-east-1 stays as-is, per D4.
- **Removing the PostgREST fallback in the repository.** Keep both transports
  until C1–C3 have run in production for one clean week; then collapse to one
  path per function in a follow-up.
