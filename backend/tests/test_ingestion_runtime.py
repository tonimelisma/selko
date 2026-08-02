"""Coverage for the in-process ingestion runtime and its API wiring.

Ingestion runs inside the FastAPI process rather than a separate service, so
the lifespan wiring and the idle-poll cost of the claim loops are both load
bearing.
"""

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from selko.api.app import lifespan
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
    """One coordinator plus the configured acquisition/attachment workers."""
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
            spawned = len(runtime._tasks)
            names = [w.worker_id for w in runtime._workers]
            await runtime.stop()
        return spawned, names, runtime._tasks

    spawned, names, remaining = asyncio.run(scenario())

    assert spawned == 1 + 2 + 3
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


def test_lifespan_runs_ingestion_in_process_without_apscheduler(mock_config):
    """v2 mode must start the pool and runtime here, and leave APScheduler off."""
    config = _lifespan_config(
        mock_config, enable_email_ingestion_v2=True, enable_background_processing=False
    )

    async def scenario():
        with patch("selko.api.app.load_config", return_value=config), \
             patch("selko.api.app.start_memory_monitor", return_value=None), \
             patch("selko.services.auth.get_service_client", return_value=MagicMock()), \
             patch("selko.api.app.WorkerPool") as pool_cls, \
             patch("selko.workers.ingestion_runtime.IngestionRuntime.start", new=AsyncMock()) as start, \
             patch("selko.workers.ingestion_runtime.IngestionRuntime.stop", new=AsyncMock()) as stop, \
             patch("selko.api.app.scheduler") as scheduler:
            pool_cls.return_value.start = AsyncMock()
            pool_cls.return_value.stop = AsyncMock()
            async with lifespan(MagicMock()):
                pass
            return pool_cls.return_value, start, stop, scheduler

    pool, start, stop, scheduler = asyncio.run(scenario())

    pool.start.assert_awaited_once()
    start.assert_awaited_once()
    stop.assert_awaited_once()
    pool.stop.assert_awaited_once()
    scheduler.start.assert_not_called()
    scheduler.add_job.assert_not_called()


def test_lifespan_leaves_ingestion_off_when_flag_is_disabled(mock_config):
    """Without the flag the legacy path is untouched."""
    config = _lifespan_config(
        mock_config, enable_email_ingestion_v2=False, enable_background_processing=False
    )

    async def scenario():
        with patch("selko.api.app.load_config", return_value=config), \
             patch("selko.api.app.start_memory_monitor", return_value=None), \
             patch("selko.workers.ingestion_runtime.IngestionRuntime.start", new=AsyncMock()) as start, \
             patch("selko.api.app.scheduler") as scheduler:
            async with lifespan(MagicMock()):
                pass
            return start, scheduler

    start, scheduler = asyncio.run(scenario())

    start.assert_not_awaited()
    scheduler.start.assert_not_called()
