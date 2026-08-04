"""Shared lifecycle for the durable email ingestion v2 worker set.

The same coordinator, acquisition, attachment and health tasks run either
inside the FastAPI process (the async monolith this deployment uses) or in a
standalone worker process. Keeping the wiring in one place means the two entry
points cannot drift apart.

Running in-process is safe because ownership is enforced by database leases,
not by process topology: `claim_due_email_sync` selects `FOR UPDATE SKIP
LOCKED` and refuses any integration whose lease is still live, so extra
instances contend harmlessly instead of double-writing.

A watchdog supervises every spawned task: any task that ends ``done()`` while
the runtime is not stopping is logged with its traceback and respawned from its
factory. This is the safety net above the per-iteration ``_guarded`` wrapper in
``EmailIngestionWorker`` — together they make a single transient DB error a
logged-and-recovered event instead of a silent total outage.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

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
        # Per-task {name, factory, task, restarts, last_exception_code}. The
        # factory lets the watchdog respawn a task that exits unexpectedly.
        self._managed: list[dict[str, Any]] = []
        self._stop_event = asyncio.Event()
        self._health_stop: asyncio.Event | None = None
        self._watchdog_task: asyncio.Task | None = None

    def _spawn(self, suffix: str, loop_name: str, task_name: str) -> None:
        def factory() -> asyncio.Task:
            worker = EmailIngestionWorker(self.client, self.config, f"{self.instance_id}-{suffix}")
            self._workers.append(worker)
            return asyncio.create_task(getattr(worker, loop_name)(), name=task_name)

        self._managed.append({
            "name": task_name,
            "factory": factory,
            "task": factory(),
            "restarts": 0,
            "last_exception_code": None,
        })

    def _spawn_health(self) -> None:
        def factory() -> asyncio.Task:
            self._health_stop = asyncio.Event()
            health = EmailSyncHealthEvaluator(self.client, self.config, build_notifier(self.config))
            return asyncio.create_task(health.run(self._health_stop), name="email-sync-health")

        self._managed.append({
            "name": "email-sync-health",
            "factory": factory,
            "task": factory(),
            "restarts": 0,
            "last_exception_code": None,
        })

    async def start(self) -> None:
        self._stop_event.clear()
        self._spawn("coordinator", "coordinator_loop", "email-sync-coordinator")
        for index in range(max(self.config.email_acquisition_concurrency, 1)):
            self._spawn(f"acquisition-{index}", "acquisition_loop", f"email-acquisition-{index}")
        for index in range(max(self.config.email_attachment_concurrency, 1)):
            self._spawn(f"attachment-{index}", "attachment_loop", f"email-attachment-{index}")
        self._spawn_health()
        self._watchdog_task = asyncio.create_task(self._watchdog(), name="ingestion-watchdog")
        logger.info(
            "Email ingestion v2 runtime started (%d tasks, instance=%s)",
            len(self._managed),
            self.instance_id,
        )

    async def _watchdog(self) -> None:
        """Respawn any task that exits while the runtime is not stopping.

        Ticks every ``email_runtime_watchdog_seconds``. A task that is
        ``done()`` (exception or clean exit) before ``stop()`` was requested is
        logged with its traceback and respawned from its factory; restart and
        last-exception counters are bumped for ``status()``. This is deliberate
        belt-and-braces over ``EmailIngestionWorker._guarded``: if a task ever
        escapes that guard (e.g. CancelledError mis-handled, a coroutine that
        returns before its loop), the loop still does not stay dead.
        """
        interval = max(self.config.email_runtime_watchdog_seconds, 1)
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
            if self._stop_event.is_set():
                break
            for entry in self._managed:
                task: asyncio.Task = entry["task"]
                if not task.done():
                    continue
                exc = task.exception() if not task.cancelled() else None
                entry["restarts"] += 1
                entry["last_exception_code"] = _exception_code(exc)
                if exc is not None:
                    logger.exception(
                        "Ingestion task %s exited unexpectedly; respawning",
                        entry["name"],
                        exc_info=exc,
                    )
                else:
                    logger.warning(
                        "Ingestion task %s exited cleanly before stop; respawning",
                        entry["name"],
                    )
                entry["task"] = entry["factory"]()

    async def stop(self) -> None:
        # Signal the watchdog first so it does not respawn during shutdown.
        self._stop_event.set()
        for worker in self._workers:
            worker.stop()
        if self._health_stop is not None:
            self._health_stop.set()
        if self._watchdog_task is not None:
            self._watchdog_task.cancel()
            await asyncio.gather(self._watchdog_task, return_exceptions=True)
            self._watchdog_task = None
        for entry in self._managed:
            entry["task"].cancel()
        await asyncio.gather(*(entry["task"] for entry in self._managed), return_exceptions=True)
        self._managed.clear()
        self._workers.clear()
        self._health_stop = None
        logger.info("Email ingestion v2 runtime stopped; unfinished leases remain reclaimable")

    def status(self) -> dict[str, Any]:
        """Live task health, consumed by ``/health/ingestion``.

        Returns per-task ``{name, alive, restarts, last_exception_code}`` plus
        ``instance_id``. Safe codes only — never payloads, tokens or addresses.
        """
        return {
            "instance_id": self.instance_id,
            "tasks": [
                {
                    "name": entry["name"],
                    "alive": not entry["task"].done(),
                    "restarts": entry["restarts"],
                    "last_exception_code": entry["last_exception_code"],
                }
                for entry in self._managed
            ],
        }


def _exception_code(exc: BaseException | None) -> str | None:
    """Stable safe code for the watchdog's restart counter; never raises."""
    if exc is None:
        return None
    # Lazy import avoids a cycle (email_ingestion imports workers; watchdog is
    # at the runtime layer and only needs the classifier helper).
    try:
        from selko.services.email_ingestion import classify_email_error

        return classify_email_error(exc).code
    except Exception:
        return "unknown"