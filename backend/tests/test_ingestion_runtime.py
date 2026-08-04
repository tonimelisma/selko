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
