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
import time
from datetime import datetime, timezone
from typing import Any

from supabase import Client

from selko.config import Config
from selko.services.egress import log_egress_summary
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

    def __init__(self, client: Client, config: Config, *, pg_pool=None, work_listener=None, instance_id: str | None = None):
        self.client = client
        self.config = config
        self.pg_pool = pg_pool
        self.work_listener = work_listener
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
            worker = EmailIngestionWorker(
                self.client, self.config, f"{self.instance_id}-{suffix}",
                pg_pool=self.pg_pool, work_listener=self.work_listener,
            )
            self._workers.append(worker)
            return asyncio.create_task(getattr(worker, loop_name)(), name=task_name)

        self._managed.append({
            "name": task_name,
            "factory": factory,
            "task": factory(),
            "restarts": 0,
            "last_exception_code": None,
        })

    def nudge(self) -> None:
        """Wake the coordinator and claim loops (email path).

        Safe to call from the API process (same event loop as the runtime) or
        from tests. If the runtime is not running, it is a no-op. Each worker's
        own nudge is level-triggered and cleared on wake, so repeated nudges
        while draining are coalesced, and a missed nudge degrades to the next
        tick — never lost work.
        """
        for worker in list(self._workers):
            try:
                nudge_fn = getattr(worker, "nudge", None)
                if callable(nudge_fn):
                    nudge_fn()
                # Acquisition/attachment workers use _claim_loop with idle_backoff;
                # waking them is likewise useful when new items appear. Their nudge
                # is not yet wired — the coordinator's discovery is the producer, so
                # waking the coordinator is sufficient for now.
            except Exception:
                pass

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
        # Inc2: one claim loop per type, concurrency via Semaphore in worker (not pollers)
        self._spawn("acquisition", "acquisition_loop", "email-acquisition")
        self._spawn("attachment", "attachment_loop", "email-attachment")
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
        # The egress summary rides this already-supervised tick rather than
        # spawning another task: one more loop to keep alive would be a worse
        # trade than a throttled log line on an existing one.
        egress_interval = max(float(self.config.egress_log_interval_seconds or 0.0), 0.0)
        last_egress_log = time.monotonic()
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
            except asyncio.TimeoutError:
                pass
            if self._stop_event.is_set():
                break
            if egress_interval and (time.monotonic() - last_egress_log) >= egress_interval:
                last_egress_log = time.monotonic()
                try:
                    log_egress_summary()
                except Exception:  # pragma: no cover - never break the watchdog
                    logger.debug("Egress summary logging failed", exc_info=True)
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
                    # An unexpectedly exited task is exactly the event with no
                    # other reporting path today. Capture to Sentry when the
                    # DSN is configured; the import is local so a missing
                    # sentry-sdk never breaks the watchdog.
                    try:
                        import sentry_sdk
                        sentry_sdk.capture_exception(exc)
                    except Exception:
                        pass
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

    def health_snapshot(self) -> dict[str, Any]:
        """One-shot ingestion health for ``GET /health/ingestion``.

        Combines the live task state from ``status()`` with a small set of
        service-role DB aggregates: due/lease/pending/dead-letter/open-incident
        counts plus the oldest scheduled poll. Computes a single ``status``
        string:

          * ``down``     — any managed task is not alive
          * ``degraded`` — any dead letters, any open email-sync incidents, or
            the oldest pending poll is past the warning SLO
          * ``ok``       — otherwise

        Safe codes only; never payloads, addresses, message ids or tokens. The
        DB calls are best-effort: a transient failure degrades to ``unknown``
        counts rather than failing the route.

        R1: counted RPCs — one call, no Python sum() over a truncated
        response. At 100k rows the old sum() truncated at 1000 and reported
        ok while dead.
        """
        snapshot = {
            "status": "ok",
            "background_processing_enabled": True,
            "instance_id": self.instance_id,
            "tasks": self.status()["tasks"],
            "integrations_due": None,
            "oldest_next_poll_seconds": None,
            "leases_held": None,
            "items_pending": None,
            "items_dead_letter": None,
            "attachments_dead_letter": None,
            "open_incidents": None,
        }
        try:
            # R1: two counted RPCs — fixed cost regardless of scale
            dead = self.client.rpc("health_dead_letter_counts").execute()
            dead_row = (getattr(dead, "data", None) or [None])[0] if isinstance(getattr(dead, "data", None), list) else getattr(dead, "data", None)
            if isinstance(dead_row, dict):
                snapshot["items_pending"] = int(dead_row.get("items_pending") or 0)
                snapshot["items_dead_letter"] = int(dead_row.get("items_dead_letter") or 0)
                snapshot["attachments_dead_letter"] = int(dead_row.get("attachments_dead_letter") or 0)
            else:
                # Fallback for PostgREST shape where RETURNS TABLE is list[dict]
                dl = getattr(dead, "data", None) or []
                if dl and isinstance(dl[0], dict):
                    snapshot["items_pending"] = int(dl[0].get("items_pending") or 0)
                    snapshot["items_dead_letter"] = int(dl[0].get("items_dead_letter") or 0)
                    snapshot["attachments_dead_letter"] = int(dl[0].get("attachments_dead_letter") or 0)

            slo = self.client.rpc(
                "health_poll_slo",
                {"p_warning_seconds": int(self.config.email_health_warning_seconds or 1800)},
            ).execute()
            slo_row = (getattr(slo, "data", None) or [None])[0] if isinstance(getattr(slo, "data", None), list) else getattr(slo, "data", None)
            if isinstance(slo_row, dict):
                snapshot["integrations_due"] = int(slo_row.get("integrations_due") or 0)
                snapshot["leases_held"] = int(slo_row.get("leases_held") or 0)
                snapshot["oldest_next_poll_seconds"] = int(slo_row.get("oldest_next_poll_seconds") or 0) if slo_row.get("oldest_next_poll_seconds") is not None else None
                snapshot["open_incidents"] = int(slo_row.get("open_incidents") or 0)
            else:
                sl = getattr(slo, "data", None) or []
                if sl and isinstance(sl[0], dict):
                    snapshot["integrations_due"] = int(sl[0].get("integrations_due") or 0)
                    snapshot["leases_held"] = int(sl[0].get("leases_held") or 0)
                    snapshot["oldest_next_poll_seconds"] = int(sl[0].get("oldest_next_poll_seconds") or 0) if sl[0].get("oldest_next_poll_seconds") is not None else None
                    snapshot["open_incidents"] = int(sl[0].get("open_incidents") or 0)
        except Exception:
            logger.exception("Ingestion health snapshot DB queries failed")
            snapshot["status"] = "degraded"
            return snapshot

        # Roll up. ``down`` beats ``degraded``.
        alive = all(t["alive"] for t in snapshot["tasks"])
        if not alive:
            snapshot["status"] = "down"
        else:
            degraded = (
                (snapshot["items_dead_letter"] or 0) > 0
                or (snapshot["attachments_dead_letter"] or 0) > 0
                or (snapshot["open_incidents"] or 0) > 0
            )
            if (
                snapshot["oldest_next_poll_seconds"] is not None
                and snapshot["oldest_next_poll_seconds"] > self.config.email_health_warning_seconds
            ):
                degraded = True
            if degraded:
                snapshot["status"] = "degraded"
        return snapshot


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


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None