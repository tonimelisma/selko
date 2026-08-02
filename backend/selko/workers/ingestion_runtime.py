"""Shared lifecycle for the durable email ingestion v2 worker set.

The same coordinator, acquisition, attachment and health tasks run either
inside the FastAPI process (the async monolith this deployment uses) or in a
standalone worker process. Keeping the wiring in one place means the two entry
points cannot drift apart.

Running in-process is safe because ownership is enforced by database leases,
not by process topology: `claim_due_email_sync` selects `FOR UPDATE SKIP
LOCKED` and refuses any integration whose lease is still live, so extra
instances contend harmlessly instead of double-writing.
"""

from __future__ import annotations

import asyncio
import logging
import os

from supabase import Client

from selko.config import Config
from selko.services.email_sync_health import (
    EmailSyncHealthEvaluator,
    ResendOperationalNotifier,
)
from selko.workers.email_ingestion import EmailIngestionWorker

logger = logging.getLogger(__name__)


def build_notifier(config: Config) -> ResendOperationalNotifier | None:
    """Return a notifier only when it can actually deliver.

    Incidents are always recorded in `operational_incidents`; email delivery is
    an optional extra. Constructing an unconfigured notifier would raise and log
    a traceback on every health cycle.
    """
    if ResendOperationalNotifier.is_configured(config):
        return ResendOperationalNotifier(config)
    logger.warning(
        "Operational notifier is not configured; email sync incidents will be "
        "recorded in operational_incidents but not emailed"
    )
    return None


class IngestionRuntime:
    """Owns the v2 task set and shuts it down without dropping leases."""

    def __init__(self, client: Client, config: Config, *, instance_id: str | None = None):
        self.client = client
        self.config = config
        self.instance_id = instance_id or f"poller-{os.getpid()}"
        self._workers: list[EmailIngestionWorker] = []
        self._tasks: list[asyncio.Task] = []
        self._health_stop = asyncio.Event()
        self._health_task: asyncio.Task | None = None

    def _spawn(self, suffix: str, loop_name: str, task_name: str) -> None:
        worker = EmailIngestionWorker(self.client, self.config, f"{self.instance_id}-{suffix}")
        self._workers.append(worker)
        self._tasks.append(asyncio.create_task(getattr(worker, loop_name)(), name=task_name))

    async def start(self) -> None:
        self._spawn("coordinator", "coordinator_loop", "email-sync-coordinator")
        for index in range(max(self.config.email_acquisition_concurrency, 1)):
            self._spawn(f"acquisition-{index}", "acquisition_loop", f"email-acquisition-{index}")
        for index in range(max(self.config.email_attachment_concurrency, 1)):
            self._spawn(f"attachment-{index}", "attachment_loop", f"email-attachment-{index}")

        health = EmailSyncHealthEvaluator(self.client, self.config, build_notifier(self.config))
        self._health_stop = asyncio.Event()
        self._health_task = asyncio.create_task(
            health.run(self._health_stop), name="email-sync-health"
        )
        logger.info(
            "Email ingestion v2 runtime started (%d tasks, instance=%s)",
            len(self._tasks) + 1,
            self.instance_id,
        )

    async def stop(self) -> None:
        for worker in self._workers:
            worker.stop()
        self._health_stop.set()
        for task in self._tasks:
            task.cancel()
        if self._health_task:
            self._health_task.cancel()
            await asyncio.gather(self._health_task, return_exceptions=True)
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._workers.clear()
        self._tasks.clear()
        self._health_task = None
        logger.info("Email ingestion v2 runtime stopped; unfinished leases remain reclaimable")
