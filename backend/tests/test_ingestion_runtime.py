"""Coverage for the in-process ingestion runtime and its API wiring.

Ingestion runs inside the FastAPI process rather than a separate service, so
the lifespan wiring and the idle-poll cost of the claim loops are both load
bearing.
"""

import asyncio
import inspect
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from selko.api.app import lifespan
from selko.services.email_sync_health import EmailSyncHealthEvaluator
from selko.workers.email_ingestion import EmailIngestionWorker
from selko.workers.ingestion_runtime import IngestionRuntime, build_notifier
from selko.services.email_ingestion import SyncClaim


def test_idle_backoff_grows_geometrically_and_is_capped(mock_config):
    """A flat retry made idle deployments issue a request per worker per second."""
    config = replace(
        mock_config, email_worker_idle_base_seconds=1.0, email_worker_idle_max_seconds=30.0
    )
    worker = EmailIngestionWorker(MagicMock(), config, "worker-1")

    assert worker.idle_backoff(1) == 1.0
    assert worker.idle_backoff(2) == 2.0
    assert worker.idle_backoff(3) == 4.0
    assert worker.idle_backoff(10) == 30.0
    assert worker.idle_backoff(100) == 30.0


def test_idle_backoff_resets_after_work_is_found(mock_config):
    """Backoff must not persist once the queue is busy again."""
    config = replace(
        mock_config, email_worker_idle_base_seconds=0.01, email_worker_idle_max_seconds=0.02
    )
    worker = EmailIngestionWorker(MagicMock(), config, "worker-1")
    waits: list[float] = []
    outcomes = [False, False, False, True, False]

    async def run_once():
        if not outcomes:
            worker.stop()
            return False
        return outcomes.pop(0)

    original = worker.idle_backoff

    def record(consecutive_idle):
        waits.append(consecutive_idle)
        return original(consecutive_idle)

    worker.idle_backoff = record
    asyncio.run(worker._claim_loop(run_once))

    # Three idle claims escalate, the successful claim resets, then the next
    # idle claim starts over at 1 rather than continuing from 4.
    assert waits[:3] == [1, 2, 3]
    assert waits[3] == 1


def test_runtime_spawns_configured_workers_and_stops_cleanly(mock_config):
    """One coordinator plus the configured acquisition/attachment workers.

    Plus one health evaluator, all managed by the watchdog so a task that
    exits is respawned rather than dying silently.
    """
    config = replace(
        mock_config, email_acquisition_concurrency=2, email_attachment_concurrency=3
    )

    async def scenario():
        runtime = IngestionRuntime(MagicMock(), config, instance_id="test-instance")
        with patch.object(EmailIngestionWorker, "coordinator_loop", new=AsyncMock()), \
             patch.object(EmailIngestionWorker, "acquisition_loop", new=AsyncMock()), \
             patch.object(EmailIngestionWorker, "attachment_loop", new=AsyncMock()), \
             patch("selko.workers.ingestion_runtime.EmailSyncHealthEvaluator") as health:
            health.return_value.run = AsyncMock()
            await runtime.start()
            spawned = len(runtime._managed)
            names = [w.worker_id for w in runtime._workers]
            await runtime.stop()
        return spawned, names, runtime._managed

    spawned, names, remaining = asyncio.run(scenario())

    assert spawned == 1 + 2 + 3 + 1  # workers + health evaluator
    assert names[0] == "test-instance-coordinator"
    assert "test-instance-attachment-2" in names
    assert remaining == []


def test_build_notifier_returns_none_when_unconfigured(mock_config):
    """Delivery is optional; incidents are still recorded without credentials."""
    assert build_notifier(mock_config) is None

    configured = replace(
        mock_config,
        operational_notification_api_key="key",
        operational_notification_sender="alerts@example.com",
        operational_notification_recipient="ops@example.com",
    )
    assert build_notifier(configured) is not None


def _lifespan_config(mock_config, **overrides):
    return replace(mock_config, **overrides)


def test_lifespan_runs_ingestion_in_process(mock_config):
    """Background processing means the pool plus ingestion, in this process.

    There is no implementation switch and no APScheduler: ingestion owns its
    own polling cadence.
    """
    config = _lifespan_config(mock_config, enable_background_processing=True)

    async def scenario():
        with patch("selko.api.app.load_config", return_value=config), \
             patch("selko.api.app.start_memory_monitor", return_value=None), \
             patch("selko.services.auth.get_service_client", return_value=MagicMock()), \
             patch("selko.services.emails.unlock_expired_email_locks", return_value=0), \
             patch("selko.services.events.unlock_expired_event_locks", return_value=0), \
             patch("selko.services.photos.unlock_expired_photo_locks", return_value=0), \
             patch("selko.services.scheduled_tasks.unlock_expired_scheduled_tasks", return_value=0), \
             patch("selko.services.integrations.unlock_expired_integration_recoveries", return_value=0), \
             patch("selko.api.app.WorkerPool") as pool_cls, \
             patch("selko.workers.ingestion_runtime.IngestionRuntime.start", new=AsyncMock()) as start, \
             patch("selko.workers.ingestion_runtime.IngestionRuntime.stop", new=AsyncMock()) as stop:
            pool_cls.return_value.start = AsyncMock()
            pool_cls.return_value.stop = AsyncMock()
            async with lifespan(MagicMock()):
                pass
            return pool_cls.return_value, start, stop

    pool, start, stop = asyncio.run(scenario())

    pool.start.assert_awaited_once()
    start.assert_awaited_once()
    stop.assert_awaited_once()
    pool.stop.assert_awaited_once()


def test_lifespan_recovers_stale_integration_recoveries_on_startup(mock_config):
    """A prior instance crash must not leave a recovery generation stuck
    `processing` forever — unlock_expired_integration_recoveries needs the
    same startup wiring as the other stale-job recovery calls.
    """
    config = _lifespan_config(mock_config, enable_background_processing=True)

    async def scenario():
        with patch("selko.api.app.load_config", return_value=config), \
             patch("selko.api.app.start_memory_monitor", return_value=None), \
             patch("selko.services.auth.get_service_client", return_value=MagicMock()), \
             patch("selko.services.emails.unlock_expired_email_locks", return_value=0), \
             patch("selko.services.events.unlock_expired_event_locks", return_value=0), \
             patch("selko.services.photos.unlock_expired_photo_locks", return_value=0), \
             patch("selko.services.scheduled_tasks.unlock_expired_scheduled_tasks", return_value=0), \
             patch(
                 "selko.services.integrations.unlock_expired_integration_recoveries",
                 return_value=2,
             ) as unlock_recoveries, \
             patch("selko.api.app.WorkerPool") as pool_cls, \
             patch("selko.workers.ingestion_runtime.IngestionRuntime.start", new=AsyncMock()), \
             patch("selko.workers.ingestion_runtime.IngestionRuntime.stop", new=AsyncMock()):
            pool_cls.return_value.start = AsyncMock()
            pool_cls.return_value.stop = AsyncMock()
            async with lifespan(MagicMock()):
                pass
            return unlock_recoveries

    unlock_recoveries = asyncio.run(scenario())

    unlock_recoveries.assert_called_once()


def test_lifespan_starts_nothing_when_background_processing_is_off(mock_config):
    """Local servers, tests and CI must never poll providers or spend quota."""
    config = _lifespan_config(mock_config, enable_background_processing=False)

    async def scenario():
        with patch("selko.api.app.load_config", return_value=config), \
             patch("selko.api.app.start_memory_monitor", return_value=None), \
             patch("selko.api.app.WorkerPool") as pool_cls, \
             patch("selko.workers.ingestion_runtime.IngestionRuntime.start", new=AsyncMock()) as start:
            async with lifespan(MagicMock()):
                pass
            return pool_cls, start

    pool_cls, start = asyncio.run(scenario())

    start.assert_not_awaited()
    pool_cls.assert_not_called()


def test_no_apscheduler_remains_in_the_api_module():
    """The legacy email_fetch scheduler is gone; nothing should re-add it."""
    import selko.api.app as app_module

    assert not hasattr(app_module, "scheduler")

    imports = [
        line
        for line in inspect.getsource(app_module).splitlines()
        if line.startswith(("import ", "from "))
    ]
    assert not [line for line in imports if "apscheduler" in line.lower()]
    assert not [line for line in imports if "email_fetch" in line]


# --- Loop supervision (top-up increment 3) -----------------------------------
#
# Pre-fix: claim calls sat *outside* the inner ``try`` in the ``run_*_once``
# bodies, ``coordinator_loop`` / ``_claim_loop`` caught nothing, and
# ``IngestionRuntime.stop()`` gathered with ``return_exceptions=True`` — so one
# transient Supabase error killed the loop forever, silently. The watchdog was
# not present. The tests below assert the inverse.

def _supervision_config(mock_config):
    """Tight intervals so the watchdog/loopback tests run in bounded time."""
    return replace(
        mock_config,
        email_runtime_watchdog_seconds=1,
        email_worker_error_backoff_seconds=0,
        email_worker_idle_base_seconds=0,
        email_worker_idle_max_seconds=0,
        email_coordinator_tick_seconds=0,
        email_health_interval_seconds=0,
    )


def test_claim_that_raises_once_leaves_loop_running_and_second_claim_attempted(mock_config):
    """The proof, inverted: one transient claim failure must not kill the loop.

    Pre-fix this ended the task after exactly one attempt. With ``_guarded`` the
    exception is logged, the loop backs off, and a second claim is attempted.
    """
    config = _supervision_config(mock_config)
    client = MagicMock()
    worker = EmailIngestionWorker(client, config, "worker-1")

    attempts = {"count": 0}

    def claim_due_sync(_worker_id):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise RuntimeError("Server disconnected without sending a response")
        worker.stop()  # let the loop exit after the successful second attempt
        return None

    async def run_under():
        await asyncio.wait_for(worker.coordinator_loop(), timeout=5.0)

    with patch.object(worker.repository, "claim_due_sync", side_effect=claim_due_sync), \
         patch.object(worker.repository, "claim_due_reconciliation", return_value=None):
        asyncio.run(run_under())

    assert attempts["count"] >= 2, "loop died after the first failure; expected a second attempt"


def test_killed_task_is_respawned_by_watchdog_within_one_tick(mock_config):
    """A task that exits mid-flight (done before stop) must be respawned."""
    config = _supervision_config(mock_config)
    runtime = IngestionRuntime(MagicMock(), config, instance_id="test")

    async def run_under():
        await runtime.start()
        try:
            entry = next(e for e in runtime._managed if e["name"] == "email-sync-coordinator")
            entry["task"].cancel()
            try:
                await entry["task"]
            except asyncio.CancelledError:
                pass
            # The watchdog ticks every 1s; wait up to 3s for a respawn.
            for _ in range(30):
                await asyncio.sleep(0.1)
                if not entry["task"].done():
                    break
            assert not entry["task"].done(), "watchdog did not respawn the killed task"
            assert entry["restarts"] >= 1
        finally:
            await runtime.stop()

    asyncio.run(asyncio.wait_for(run_under(), timeout=10.0))


def test_stop_shuts_down_cleanly_and_does_not_respawn(mock_config):
    """``stop()`` must not race the watchdog into respawning during shutdown."""
    runtime = IngestionRuntime(MagicMock(), _supervision_config(mock_config), instance_id="test")

    async def run_under():
        await runtime.start()
        await runtime.stop()
        for entry in runtime._managed:
            assert entry["task"].done()

    asyncio.run(asyncio.wait_for(run_under(), timeout=10.0))


def test_status_reports_alive_and_restart_counts(mock_config):
    runtime = IngestionRuntime(
        MagicMock(), _supervision_config(mock_config), instance_id="instance-1"
    )

    async def run_under():
        await runtime.start()
        try:
            st = runtime.status()
            assert st["instance_id"] == "instance-1"
            names = {t["name"] for t in st["tasks"]}
            assert "email-sync-coordinator" in names
            assert "email-sync-health" in names
            for t in st["tasks"]:
                assert t["alive"] is True
                assert t["restarts"] == 0
                assert t["last_exception_code"] is None
        finally:
            await runtime.stop()

    asyncio.run(asyncio.wait_for(run_under(), timeout=10.0))


def test_health_evaluator_survives_an_evaluate_once_exception(mock_config):
    """``EmailSyncHealthEvaluator.run`` must keep ticking after a failed cycle."""
    config = _supervision_config(mock_config)
    evaluator = EmailSyncHealthEvaluator(MagicMock(), config, None)
    stop = asyncio.Event()

    async def run_under():
        call_count = {"n": 0}

        async def flaky_evaluate():
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise RuntimeError("transient DB error during evaluation")
            if call_count["n"] >= 2:
                stop.set()

        with patch.object(evaluator, "evaluate_once", side_effect=flaky_evaluate):
            await asyncio.wait_for(evaluator.run(stop), timeout=5.0)

        assert call_count["n"] >= 2, "evaluator died after the first exception"

    asyncio.run(run_under())


def _state_table_client(*, states, items=None, attachments=None, incidents=None):
    """A MagicMock client whose health RPCs return counted values. Used to
    drive health_snapshot() without a real database.

    R1: health_snapshot() now uses counted RPCs (no 1000-row truncation).
    This helper drives those RPCs directly; the old table-sum path is removed.
    """
    client = MagicMock()

    # Count dead letters + pending (one RPC)
    items_dead = sum(1 for _, s in (items or []) if s == "dead_letter")
    items_pending = sum(1 for _, s in (items or []) if s in ("pending", "retry", "processing"))
    attachments_dead = sum(1 for _, s in (attachments or []) if s == "dead_letter")

    # SLO: integrations_due is not derivable from the thin `states` tuples
    # since prior tests treat any supplied `states` as one past-due integration.
    # For R1 we keep the same test semantics: len(states) counts as an SLO input
    # and the DL pending/dead counts are via RPCs. We simulate the SLO RPC
    # from the same `states` list, treating a far-future next_poll_at as 0 due.
    # If any state's next_poll_at is in the past (test injects future 2099),
    # due=0 — matching prior assertions.
    # Keep logic trivial: if states contains at least one entry with far future,
    # oldest is negative huge → oldest_next_poll_seconds will be 0 under new RPC
    # (since min(next_poll_at) is far future, now - min is negative → GREATEST(0,...)=0).
    # For tests this is equivalent to "not degraded on poll SLO".
    def _slo_payload():
        # Synthesize from states: only matters that due==0 and open_incidents==len(incidents)
        # and leases_held==0 for the test inputs.
        return {
            "integrations_due": 0,
            "leases_held": 0,
            "oldest_next_poll_seconds": 0,
            "open_incidents": len(incidents or []),
        }

    def rpc(name, params=None):
        handle = MagicMock()
        if name == "health_dead_letter_counts":
            handle.execute.return_value = MagicMock(
                data=[{
                    "items_dead_letter": items_dead,
                    "attachments_dead_letter": attachments_dead,
                    "items_pending": items_pending,
                }]
            )
        elif name == "health_poll_slo":
            handle.execute.return_value = MagicMock(data=[_slo_payload()])
        else:
            handle.execute.return_value = MagicMock(data=[])
        return handle

    client.rpc.side_effect = rpc

    # Back-compat: some older tests still poke table(); keep it harmless
    def table(name):
        handle = MagicMock()
        handle.select.return_value.execute.return_value = MagicMock(data=[], count=0)
        chain = handle.select.return_value
        # allow .eq().like().execute() chain without raising
        chain.eq.return_value = chain
        chain.like.return_value = chain
        chain.execute.return_value = MagicMock(data=[], count=0)
        return handle

    client.table.side_effect = table
    return client


def _state_table_client_with_counts(*, items_dead_letter=0, attachments_dead_letter=0, items_pending=0, integrations_due=0, leases_held=0, oldest_next_poll_seconds=0, open_incidents=0):
    """Direct counted helper for truncation regression test."""
    client = MagicMock()

    def rpc(name, params=None):
        handle = MagicMock()
        if name == "health_dead_letter_counts":
            handle.execute.return_value = MagicMock(
                data=[{
                    "items_dead_letter": items_dead_letter,
                    "attachments_dead_letter": attachments_dead_letter,
                    "items_pending": items_pending,
                }]
            )
        elif name == "health_poll_slo":
            handle.execute.return_value = MagicMock(
                data=[{
                    "integrations_due": integrations_due,
                    "leases_held": leases_held,
                    "oldest_next_poll_seconds": oldest_next_poll_seconds,
                    "open_incidents": open_incidents,
                }]
            )
        else:
            handle.execute.return_value = MagicMock(data=[])
        return handle

    client.rpc.side_effect = rpc

    def table(name):
        handle = MagicMock()
        handle.select.return_value.execute.return_value = MagicMock(data=[], count=0)
        chain = handle.select.return_value
        chain.eq.return_value = chain
        chain.like.return_value = chain
        chain.execute.return_value = MagicMock(data=[], count=0)
        return handle

    client.table.side_effect = table
    return client


def test_health_snapshot_marks_down_when_any_task_not_alive(mock_config):
    """A dead task must produce status=down regardless of DB counts.

    Seeds ``_managed`` directly so the assertion is timing-independent: the
    watchdog's *respawn* behavior is exercised separately; here we only verify
    the snapshot sees ``alive=False`` and rolls up to ``down``.
    """
    config = _supervision_config(mock_config)
    client = _state_table_client(
        states=[("2099-01-01T00:00:00+00:00", None)],
        items=[],
        attachments=[],
        incidents=[],
    )
    runtime = IngestionRuntime(client, config, instance_id="instance-1")

    async def run_under():
        await runtime.start()
        try:
            # Avoid racing the watchdog: replace one task with an already-done
            # one so health_snapshot() observes it as not alive right now.
            entry = next(e for e in runtime._managed if e["name"] == "email-sync-coordinator")

            async def _already_done():
                return

            done_task = asyncio.ensure_future(_already_done())
            await done_task  # mark done() with no exception
            entry["task"] = done_task
            snapshot = runtime.health_snapshot()
            assert snapshot["status"] == "down"
            assert any(t["alive"] is False for t in snapshot["tasks"])
        finally:
            await runtime.stop()

    asyncio.run(asyncio.wait_for(run_under(), timeout=15.0))


def test_health_snapshot_ok_when_everything_is_alive_and_clear(mock_config):
    """Healthy runtime + no dead letters + no open incidents + upcoming poll."""
    config = _supervision_config(mock_config)
    future = "2099-01-01T00:00:00+00:00"
    client = _state_table_client(
        states=[(future, None)],
        items=[],
        attachments=[],
        incidents=[],
    )
    runtime = IngestionRuntime(client, config, instance_id="instance-1")

    async def run_under():
        await runtime.start()
        try:
            snap = runtime.health_snapshot()
            assert snap["status"] == "ok"
            assert snap["integrations_due"] == 0
            assert snap["items_dead_letter"] == 0
            assert snap["open_incidents"] == 0
            # oldest_next_poll_seconds is 0 when there is no oldest past-due poll.
        finally:
            await runtime.stop()

    asyncio.run(asyncio.wait_for(run_under(), timeout=10.0))


def test_health_snapshot_degrades_on_dead_letters(mock_config):
    config = _supervision_config(mock_config)
    future = "2099-01-01T00:00:00+00:00"
    client = _state_table_client(
        states=[(future, None)],
        items=[("i1", "dead_letter"), ("i2", "pending")],
        attachments=[("a1", "dead_letter")],
        incidents=["email-sync:integration-1:stale_poll"],
    )
    runtime = IngestionRuntime(client, config, instance_id="instance-1")

    async def run_under():
        await runtime.start()
        try:
            snap = runtime.health_snapshot()
            assert snap["status"] == "degraded"
            assert snap["items_dead_letter"] == 1
            assert snap["attachments_dead_letter"] == 1
            assert snap["open_incidents"] == 1
        finally:
            await runtime.stop()

    asyncio.run(asyncio.wait_for(run_under(), timeout=10.0))


def test_health_snapshot_degrades_when_no_db_available(mock_config):
    """A transient DB failure must not crash the snapshot; it degrades."""
    config = _supervision_config(mock_config)
    client = MagicMock()
    client.rpc.side_effect = RuntimeError("Server disconnected")
    client.table.side_effect = RuntimeError("Server disconnected")

    runtime = IngestionRuntime(client, config, instance_id="instance-1")

    async def run_under():
        await runtime.start()
        try:
            snap = runtime.health_snapshot()
            assert snap["status"] == "degraded"
            assert snap["integrations_due"] is None
        finally:
            await runtime.stop()

    asyncio.run(asyncio.wait_for(run_under(), timeout=10.0))


def test_health_snapshot_counts_1500_dead_letters_without_truncation(mock_config):
    """R1 regression: 1500 dead letters must be counted, not truncated at 1000.

    The old sum() over `items.data` truncated at PostgREST's 1000-row cap and
    reported degraded=False. The counted RPC reports the true count.
    """
    config = _supervision_config(mock_config)
    client = _state_table_client_with_counts(
        items_dead_letter=1500,
        attachments_dead_letter=0,
        items_pending=0,
        integrations_due=0,
        leases_held=0,
        oldest_next_poll_seconds=0,
        open_incidents=0,
    )
    runtime = IngestionRuntime(client, config, instance_id="instance-1")

    async def run_under():
        await runtime.start()
        try:
            snap = runtime.health_snapshot()
            assert snap["status"] == "degraded"
            assert snap["items_dead_letter"] == 1500
            # Also ensure the snapshot was driven via RPC, not via truncated table
            assert client.rpc.call_count == 2
            assert client.rpc.call_args_list[0][0][0] == "health_dead_letter_counts"
        finally:
            await runtime.stop()

    asyncio.run(asyncio.wait_for(run_under(), timeout=10.0))


def test_sync_run_emits_one_structured_counter_line_per_run(mock_config, caplog):
    """One ``ingestion_sync_run`` log line per completed sync run with the
    stable key/value shape — Render log search answers 'is ingestion moving'
    without a metrics backend."""
    import logging as _logging
    config = _supervision_config(mock_config)
    worker = EmailIngestionWorker(MagicMock(), config, "worker-1")

    claim = SyncClaim(
        integration_id="integration-1", user_id="user-1", provider="gmail",
        run_id="run-1", run_kind="incremental",
    )

    def claim_due_sync(_worker_id):
        return claim

    def discover(_claim):
        return {"provider_ids_seen": 7, "items_inserted": 5, "items_existing": 2}

    def complete_sync(_claim, _worker_id, **_kw):
        return True

    with patch.object(worker.repository, "claim_due_sync", side_effect=claim_due_sync), \
         patch.object(worker.repository, "claim_due_reconciliation", return_value=None), \
         patch.object(worker, "discover", side_effect=discover), \
         patch.object(worker.repository, "complete_sync", side_effect=complete_sync):
        caplog.set_level(_logging.INFO, logger="selko.workers.email_ingestion")
        asyncio.run(asyncio.wait_for(worker.run_sync_once(), timeout=5.0))

    matches = [r for r in caplog.records if r.getMessage().startswith("ingestion_sync_run")]
    assert len(matches) == 1, "exactly one structured counter line per run"
    msg = matches[0].getMessage()
    assert "run_kind=incremental" in msg
    assert "provider=gmail" in msg
    assert "duration_ms=" in msg
    assert "provider_ids_seen=7" in msg
    assert "items_inserted=5" in msg
    assert "items_existing=2" in msg
    assert "error_code=" in msg


def test_sync_run_log_line_records_error_code_on_failure(mock_config, caplog):
    import logging as _logging
    config = _supervision_config(mock_config)
    worker = EmailIngestionWorker(MagicMock(), config, "worker-1")
    claim = SyncClaim(
        integration_id="integration-1", user_id="user-1", provider="gmail",
        run_id="run-1", run_kind="incremental",
    )

    def discover(_claim):
        from selko.services.gmail import GmailError
        raise GmailError("Gmail API error", status_code=429, reason="rateLimitExceeded")

    with patch.object(worker.repository, "claim_due_sync", return_value=claim), \
         patch.object(worker.repository, "claim_due_reconciliation", return_value=None), \
         patch.object(worker, "discover", side_effect=discover), \
         patch.object(worker.repository, "fail_sync", return_value=True), \
         patch.object(worker.repository, "complete_sync") as complete:
        caplog.set_level(_logging.INFO, logger="selko.workers.email_ingestion")
        asyncio.run(asyncio.wait_for(worker.run_sync_once(), timeout=5.0))

    complete.assert_not_called()
    matches = [r for r in caplog.records if r.getMessage().startswith("ingestion_sync_run")]
    assert len(matches) == 1
    msg = matches[0].getMessage()
    assert "error_code=provider_rate_limited" in msg


def test_claim_loop_nudge_wakes_acquisition(mock_config):
    """R3: discovery->acquisition must be <100ms, not 30s backoff. Claim loop is now nudge-aware."""
    import asyncio
    from dataclasses import replace
    from unittest.mock import MagicMock
    from selko.workers.email_ingestion import EmailIngestionWorker
    config = replace(mock_config, email_worker_idle_base_seconds=30.0, email_worker_idle_max_seconds=30.0)
    client = MagicMock()
    worker = EmailIngestionWorker(client, config, "w-1")
    calls = {"n": 0}
    async def run_once():
        calls["n"] += 1
        if calls["n"] == 1:
            return False  # first Idle triggers long backoff
        worker.stop()
        return False
    async def scenario():
        task = asyncio.create_task(worker._claim_loop(run_once))
        await asyncio.sleep(0.05)
        assert not task.done(), "loop should still be sleeping on 30s backoff"
        worker.nudge()
        await asyncio.wait_for(task, timeout=1.0)
        assert calls["n"] >= 2
    asyncio.run(scenario())
