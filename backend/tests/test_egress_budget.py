"""Proof that an idle runtime does not schedule a health polling loop."""

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
            assert len(runtime._managed) == 3
            evaluator_class.return_value.evaluate_once.assert_not_awaited()
            await runtime.stop()

    asyncio.run(scenario())


def test_watchdog_classifies_unknown_exceptions_as_unclassified():
    assert _exception_code(RuntimeError("unexpected provider failure")) == "unclassified"
