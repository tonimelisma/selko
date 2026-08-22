"""The idle-runtime database call budget.

V6 deleted the unconditional 300s health poll. W4 put a bounded floor back
under it, because the notification-driven path never fires on a runtime that
cannot claim work -- the one state incidents exist to report. These tests pin
both halves: the floor exists, and it does not fire inside its own interval.
"""

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock, patch

from selko.workers.email_ingestion import EmailIngestionWorker
from selko.workers.ingestion_runtime import IngestionRuntime
from selko.workers.ingestion_runtime import _exception_code


def test_idle_runtime_stays_under_health_database_call_budget(mock_config):
    async def parked(worker):
        await worker.stop_event.wait()

    async def scenario():
        config = replace(
            mock_config,
            email_runtime_watchdog_seconds=0.01,
            egress_log_interval_seconds=0,
        )
        runtime = IngestionRuntime(MagicMock(), config, instance_id="idle-budget")
        with patch.object(EmailIngestionWorker, "coordinator_loop", parked), \
             patch.object(EmailIngestionWorker, "acquisition_loop", parked), \
             patch.object(EmailIngestionWorker, "attachment_loop", parked), \
             patch(
                 "selko.workers.ingestion_runtime.EmailSyncHealthEvaluator"
             ) as evaluator_class:
            evaluator_class.return_value.evaluate_once = AsyncMock()
            await runtime.start()
            await asyncio.sleep(0.05)
            # coordinator + acquisition + attachment + health floor
            assert len(runtime._managed) == 4
            # The floor's interval is far longer than this sleep, so an idle
            # runtime issues no health query at all in the first moments.
            evaluator_class.return_value.evaluate_once.assert_not_awaited()
            await runtime.stop()

    asyncio.run(scenario())


def test_idle_health_floor_costs_one_evaluation_per_interval_and_no_more(mock_config):
    """The ceiling, asserted rather than assumed.

    The old evaluator ran every 300s regardless of pending work: 2,025 cycles
    in 7 days against 2,026 operational_incidents reads in production. The
    floor's ceiling is one evaluation per EMAIL_HEALTH_FLOOR_SECONDS, and only
    when nothing else evaluated inside that interval.
    """
    async def scenario():
        config = replace(mock_config, email_health_floor_seconds=0.05)
        runtime = IngestionRuntime(MagicMock(), config, instance_id="floor-budget")
        evaluator = MagicMock()
        evaluator.evaluate_once = AsyncMock(return_value=0)
        evaluator.seconds_since_last_evaluation = MagicMock(return_value=None)
        runtime._health_evaluator = evaluator

        task = asyncio.create_task(runtime._health_floor())
        intervals = 4
        await asyncio.sleep(config.email_health_floor_seconds * (intervals + 0.5))
        runtime._stop_event.set()
        await asyncio.wait_for(task, timeout=2)
        return evaluator.evaluate_once.await_count

    calls = asyncio.run(scenario())
    assert 1 <= calls <= 6, f"idle floor issued {calls} evaluations over ~4 intervals"


def test_watchdog_classifies_unknown_exceptions_as_unclassified():
    assert _exception_code(RuntimeError("unexpected provider failure")) == "unclassified"
