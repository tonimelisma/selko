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
from selko.services import calendar_mirror
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
        self._health_evaluator: EmailSyncHealthEvaluator | None = None
        self._watchdog_task: asyncio.Task | None = None

    def _spawn(self, suffix: str, loop_name: str, task_name: str) -> None:
        def factory() -> asyncio.Task:
            worker = EmailIngestionWorker(
                self.client, self.config, f"{self.instance_id}-{suffix}",
                pg_pool=self.pg_pool,
                work_listener=self.work_listener,
                health_evaluator=self._health_evaluator,
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

    async def start(self) -> None:
        self._stop_event.clear()
        self._health_evaluator = EmailSyncHealthEvaluator(
            self.client, self.config, build_notifier(self.config)
        )
        self._spawn("coordinator", "coordinator_loop", "email-sync-coordinator")
        # Inc2: one claim loop per type, concurrency via Semaphore in worker (not pollers)
        self._spawn("acquisition", "acquisition_loop", "email-acquisition")
        self._spawn("attachment", "attachment_loop", "email-attachment")
        self._managed.append({
            "name": "email-sync-health-floor",
            "factory": lambda: asyncio.create_task(
                self._health_floor(), name="email-sync-health-floor"
            ),
            "task": asyncio.create_task(self._health_floor(), name="email-sync-health-floor"),
            "restarts": 0,
            "last_exception_code": None,
        })
        self._managed.append({
            "name": "calendar-mirror",
            "factory": lambda: asyncio.create_task(
                self._calendar_mirror_floor(), name="calendar-mirror"
            ),
            "task": asyncio.create_task(
                self._calendar_mirror_floor(), name="calendar-mirror"
            ),
            "restarts": 0,
            "last_exception_code": None,
        })
        self._watchdog_task = asyncio.create_task(self._watchdog(), name="ingestion-watchdog")
        logger.info(
            "Email ingestion v2 runtime started (%d tasks, instance=%s)",
            len(self._managed),
            self.instance_id,
        )

    async def _health_floor(self) -> None:
        """A floor under notification-driven health evaluation, not a schedule.

        V6 deleted the unconditional 300s evaluator and drove incident
        evaluation from work activity instead. That is correct for *work* --
        work announces itself. Health is the absence-of-work detector, and
        absence announces nothing: if the coordinator cannot claim anything
        (every integration OAuth-blocked, the claim path itself broken, or no
        active integrations at all) then ``evaluate_once`` never runs, no
        incident is ever opened, and no notification is ever sent. The stall
        detector ends up depending on the thing it exists to detect.

        The architecture principle already says what to do here: work arrives
        by notification, and the safety-net poll is a floor rather than a
        schedule. V6 removed the schedule without leaving the floor.

        This fires only when a whole interval has passed with no work-activity
        evaluation, so a busy system pays nothing for it and the egress budget
        is unchanged.
        """
        # Float, and clamped only against a zero/negative busy-loop. An int()
        # coercion here would silently round every sub-second value up to 1.
        interval = max(0.01, float(self.config.email_health_floor_seconds))
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
                return
            except asyncio.TimeoutError:
                pass
            evaluator = self._health_evaluator
            if evaluator is None:
                continue
            since = evaluator.seconds_since_last_evaluation()
            if since is not None and since < interval:
                # Work activity already evaluated inside this interval.
                continue
            try:
                await evaluator.evaluate_once()
            except Exception:
                logger.exception("Floor health evaluation failed")

    async def _calendar_mirror_floor(self) -> None:
        """Keep `calendar_entries` current for every active calendar.

        A floor, not a schedule. The first pass for a calendar reads its rolling
        window; every pass after that sends the stored sync token, so Google
        returns only what changed and a quiet calendar costs one near-empty
        request per interval. That is what keeps a mirror inside the egress
        rule -- a projection that re-read everything would be the shape of both
        the #191 OOM and the 942 MB bandwidth bill.
        """
        interval = max(60.0, float(self.config.calendar_mirror_floor_seconds))
        while not self._stop_event.is_set():
            try:
                await asyncio.wait_for(self._stop_event.wait(), timeout=interval)
                return
            except asyncio.TimeoutError:
                pass
            try:
                rows = (
                    self.client.table("integrations")
                    .select("id,user_id")
                    .eq("provider", "google_calendar")
                    .eq("status", "active")
                    .execute()
                    .data
                    or []
                )
            except Exception:
                logger.exception("Could not list calendars to mirror")
                continue
            for row in rows:
                if self._stop_event.is_set():
                    return
                try:
                    summary = await asyncio.to_thread(
                        calendar_mirror.sync_all_calendars,
                        self.client,
                        row["user_id"],
                        row["id"],
                    )
                    logger.info(
                        "Calendar mirror synced %d entries across %d calendars (%d failed)",
                        summary["entries"],
                        summary["calendars"],
                        summary["failed"],
                    )
                    if summary["failed"]:
                        # A calendar we cannot read is a calendar whose events
                        # look absent, which is indistinguishable from the user
                        # not having them. Say so rather than counting silently.
                        logger.warning(
                            "Calendar mirror could not read %d of %d calendars; "
                            "events on those calendars will appear as new",
                            summary["failed"],
                            summary["failed"] + summary["calendars"],
                        )
                except Exception:
                    # One user's expired token must not stop the others.
                    logger.exception("Calendar mirror sync failed for one integration")

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
        if self._watchdog_task is not None:
            self._watchdog_task.cancel()
            await asyncio.gather(self._watchdog_task, return_exceptions=True)
            self._watchdog_task = None
        for entry in self._managed:
            entry["task"].cancel()
        await asyncio.gather(*(entry["task"] for entry in self._managed), return_exceptions=True)
        self._managed.clear()
        self._workers.clear()
        self._health_evaluator = None
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

        Combines the live task state from ``status()`` with one service-role
        RPC, ``health_work_state``: ready/processing/stale/unclaimable email
        counts, stale sync runs, due/lease/pending/dead-letter/open-incident
        counts, and the oldest scheduled poll. That RPC's own ``status``
        already reflects DB-side degradation; this method only adds the
        process-local ``down`` case, since only Python knows task aliveness.
        ``down`` beats ``degraded``.

        Safe codes only; never payloads, addresses, message ids or tokens. The
        DB call is best-effort: a transient failure degrades to ``unknown``
        counts rather than failing the route.

        S1.4: one counted RPC — no Python sum() over a truncated response. At
        100k rows the old sum() truncated at 1000 and reported ok while dead.
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
            "ready_emails": None,
            "processing_emails": None,
            "stale_processing_emails": None,
            "mirrored_calendars": None,
            "unclaimable_pending": None,
            "failed_emails": None,
            "stale_sync_runs": None,
        }
        try:
            result = self.client.rpc(
                "health_work_state",
                {"p_warning_seconds": int(self.config.email_health_warning_seconds or 1800)},
            ).execute()
            data = getattr(result, "data", None)
            row = (data or [None])[0] if isinstance(data, list) else data
            if not isinstance(row, dict):
                raise ValueError("health_work_state returned no row")

            oldest = row.get("oldest_next_poll_seconds")
            snapshot["integrations_due"] = int(row.get("integrations_due") or 0)
            snapshot["leases_held"] = int(row.get("leases_held") or 0)
            snapshot["oldest_next_poll_seconds"] = int(oldest) if oldest is not None else None
            snapshot["open_incidents"] = int(row.get("open_incidents") or 0)
            snapshot["items_pending"] = int(row.get("items_pending") or 0)
            snapshot["items_dead_letter"] = int(row.get("items_dead_letter") or 0)
            snapshot["attachments_dead_letter"] = int(row.get("attachments_dead_letter") or 0)
            snapshot["ready_emails"] = int(row.get("ready_emails") or 0)
            snapshot["processing_emails"] = int(row.get("processing_emails") or 0)
            snapshot["stale_processing_emails"] = int(row.get("stale_processing_emails") or 0)
            snapshot["unclaimable_pending"] = int(row.get("unclaimable_pending") or 0)
            snapshot["failed_emails"] = int(row.get("failed_emails") or 0)
            snapshot["stale_sync_runs"] = int(row.get("stale_sync_runs") or 0)
            db_degraded = row.get("status") != "ok"
        except Exception:
            logger.exception("Ingestion health snapshot DB query failed")
            snapshot["status"] = "degraded"
            return snapshot

        # Roll up. ``down`` beats ``degraded``.
        alive = all(t["alive"] for t in snapshot["tasks"])
        if not alive:
            snapshot["status"] = "down"
        elif db_degraded:
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

        code = classify_email_error(exc).code
        return "unclassified" if code == "unknown" else code
    except Exception:
        return "unclassified"


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
    except (TypeError, ValueError):
        return None
