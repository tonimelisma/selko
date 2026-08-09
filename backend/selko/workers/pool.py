"""Worker pool for continuously processing background work.

This module implements a pool of long-running asyncio tasks that continuously
poll for work from one source:
1. Approved events (status-based claiming)
2. Calendar OAuth recovery bookkeeping

Photo ingestion is parked (egress inc 1). Email ingestion is owned solely by
IngestionRuntime (egress inc 2) — WorkerPool no longer claims emails. The
_process_email helper is retained for hardening inc 8 cleanup only.

This replaces the job queue with direct status-based polling of data tables.
"""

import asyncio
import logging
import os
import time
from typing import Any, Optional

from selko.config import Config, load_config
from selko.services.auth import get_service_client
from selko.services.calendars import (
    CalendarsError,
    classify_calendar_error,
    refresh_waiting_calendar_recoveries,
    requeue_calendar_recovery_batch,
)
from selko.services.circuit_breaker import circuit_breaker
from selko.services.integrations import IntegrationError, claim_integration_recovery
from selko.services.scheduled_tasks import (
    ScheduledTasksError,
    claim_scheduled_task,
    complete_scheduled_task,
    fail_scheduled_task,
)
from selko.services.emails import (
    EmailError,
    claim_pending_email,
    complete_email_processing,
    fail_email_processing,
)
from selko.services.events import (
    EventsError,
    claim_approved_event_for_sync,
    claim_approved_event_for_sync_via_pool,
    complete_event_sync,
    defer_event_sync_for_quota,
    fail_event_sync,
    park_event_for_oauth_reauth,
)
from selko.services.photos import (
    PhotosError,
    claim_pending_photo,
    complete_photo_processing,
    fail_photo_processing,
)
from selko.services.quotas import QuotaService

logger = logging.getLogger(__name__)


class WorkerPool:
    """Manages a single scheduler that drains the calendar queue.

    Egress inc 3+4: previously this spawned N independent busy-polling workers,
    each issuing up to 6 RPCs/sec. Now one scheduler drains the queue (claim
    and process until empty) then sleeps to the next tick. An in-process
    asyncio.Event nudges the scheduler immediately for user-initiated work
    (approve/retry). If the nudge is missed, the next tick catches it — degraded
    latency, never lost.

    R3: single scheduler with Semaphore concurrency for calendar sync.
    worker_pool_size is a deprecated alias for worker_calendar_sync_concurrency;
    num_workers is kept for compat but the real knob is
    config.worker_calendar_sync_concurrency. Durability stays in SQL leases.
    """

    def __init__(
        self,
        num_workers: int = 3,
        idle_sleep_seconds: float = 1.0,
        error_backoff_seconds: float = 5.0,
        pg_pool=None,
    ):
        """Initialize the worker pool.

        Args:
            num_workers: Concurrency for the executor pool (kept for compat;
                actual scheduler is single — workers are executors, not pollers).
            idle_sleep_seconds: Idle tick interval (now the fixed sleep between
                drain passes; previously the busy-poll sleep).
            error_backoff_seconds: Time to sleep after errors.
        """
        self.num_workers = num_workers
        self.idle_sleep_seconds = idle_sleep_seconds
        self.error_backoff_seconds = error_backoff_seconds
        self.pg_pool = pg_pool
        self.pg_pool = pg_pool
        self.tasks: list[asyncio.Task] = []
        self.running = False
        self.config: Optional[Config] = None
        self._client: Optional[Any] = None
        # 6d: gates the idle recovery probe in _process_integration_recovery.
        # Monotonic, shared across the pool's workers; 0.0 means "probe now".
        self._last_recovery_probe_at: float = 0.0
        # Egress 3+4+5: single scheduler + nudge. The event is created in start()
        # so it is bound to the running loop (asyncio.Event is loop-bound).
        self._nudge_event: Optional[asyncio.Event] = None
        self._scheduler_task: Optional[asyncio.Task] = None
        # LLM extraction parallelism — single claim loop + semaphore fan-out
        # keeps polling at tick speed (no egress storm) while emails
        # themselves run in parallel. 8 drains 578 pending in ~6 min,
        # 1 would be 29 min. Paid gemini is 60-1000 RPM so 8 is safe.
        self._llm_semaphore: Optional[asyncio.Semaphore] = None
        self._email_tasks: set[asyncio.Task] = set()

    def nudge(self) -> None:
        """Wake the scheduler immediately (in-process, same FastAPI process).

        Called from the approve/sync route and from tests. If the scheduler is
        draining, the nudge will be observed on the next idle wait. If no
        scheduler is running (e.g. ENABLE_BACKGROUND_PROCESSING=false), it is a
        no-op. Never raises.
        """
        try:
            if self._nudge_event is not None and not self._nudge_event.is_set():
                self._nudge_event.set()
        except Exception:
            pass

    def _tick_seconds(self) -> float:
        """Fixed sleep between drain passes when no nudge arrives.

        Uses the configured worker_idle_max_seconds as the tick (default 30s),
        floored at the legacy idle_sleep_seconds so a misconfigured small max
        cannot accidentally re-create a busy-wait. Geometric backoff (PR #247)
        is retained only as the safety-net poll inside _process_integration_recovery.

        R3: floor at 5.0s is intentional — prevents WORKER_IDLE_MAX_SECONDS=1
        from recreating a busy-wait. A clamp is logged once at DEBUG.
        """
        if self.config is not None:
            # Prefer explicit tick if caller passed it; otherwise use max.
            base = float(getattr(self.config, "worker_idle_max_seconds", 0) or 0)
            floor = float(self.idle_sleep_seconds or 1.0)
            tick = max(base, floor, 5.0)
            # R3: visible clamp — if the configured max is below the floor,
            # log once so latency debugging is not silent.
            if base > 0 and base < 5.0 and tick == 5.0:
                logger.debug(
                    "WorkerPool tick clamped to 5.0s (configured worker_idle_max_seconds=%.1fs below floor)",
                    base,
                )
            return tick
        return max(float(self.idle_sleep_seconds or 1.0), 5.0)

    async def start(self) -> None:
        """Start the single scheduler (arch A).

        Previously this spawned num_workers independent pollers. Now it spawns
        one scheduler task that drains the queue and sleeps to the next tick,
        with an in-process nudge for approve/retry paths.
        """
        if self.running:
            logger.warning("Worker pool already running")
            return

        logger.info(f"Starting worker pool scheduler (arch A, tick={self._tick_seconds() if self.config else self.idle_sleep_seconds}s)")
        self.running = True
        if self.config is None:
            self.config = load_config()
        self._client = None
        self._nudge_event = asyncio.Event()
        # LLM parallelism semaphore — bound to this loop
        _conc = int(getattr(self.config, "llm_extraction_concurrency", 8) or 8)
        self._llm_semaphore = asyncio.Semaphore(max(_conc, 1))
        self._email_tasks = set()

        worker_id = f"worker-{os.getpid()}-scheduler"
        self._scheduler_task = asyncio.create_task(
            self._scheduler_loop(worker_id),
            name=worker_id,
        )
        self.tasks = [self._scheduler_task]

        logger.info(f"Worker pool scheduler started (task={worker_id})")

    async def stop(self, timeout: float = 30.0) -> None:
        """Gracefully stop the scheduler.

        Cancels the single scheduler task and waits for it. The nudge event is
        set so a scheduler blocked on `wait_for(nudge)` wakes immediately.
        """
        if not self.running:
            logger.warning("Worker pool not running")
            return

        logger.info(f"Stopping worker pool scheduler ({len(self.tasks)} tasks)...")
        self.running = False
        # Wake the scheduler if it is sleeping on the nudge event
        try:
            if self._nudge_event is not None and not self._nudge_event.is_set():
                self._nudge_event.set()
        except Exception:
            pass

        for task in list(self.tasks):
            if not task.done():
                task.cancel()

        # Also cancel any in-flight LLM email tasks
        for task in list(self._email_tasks):
            if not task.done():
                task.cancel()

        try:
            await asyncio.wait_for(
                asyncio.gather(*self.tasks, *self._email_tasks, return_exceptions=True),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(f"Worker pool shutdown timed out after {timeout}s")

        self.tasks.clear()
        self._email_tasks.clear()
        self._scheduler_task = None
        # Keep _nudge_event but clear it so a restarted pool starts clean
        try:
            if self._nudge_event is not None:
                self._nudge_event.clear()
        except Exception:
            pass
        logger.info("Worker pool stopped")

    async def _scheduler_loop(self, worker_id: str) -> None:
        """Single scheduler: drain the queue, then sleep to next tick or nudge.

        A pass drains: call _process_any_work until it returns False, then sleep.
        Processing is sequential today; concurrency comes from the caller awaiting
        each sync (calendar writes are idempotent and lease-protected). If a
        future pass needs parallelism, fan out here behind a Semaphore sized by
        num_workers.

        The nudge (approve/retry) wakes the idle sleep immediately; if missed,
        the next tick catches it.
        """
        logger.info(f"{worker_id}: scheduler started (tick={self._tick_seconds()}s)")

        while self.running:
            try:
                # --- drain ---
                drained = 0
                while self.running:
                    processed = await self._process_any_work(worker_id)
                    if not processed:
                        break
                    drained += 1

                if drained:
                    logger.debug(f"{worker_id}: drained {drained} items, re-draining")
                    continue

                # --- idle: wait for tick or nudge ---
                if self._nudge_event is None:
                    await asyncio.sleep(self._tick_seconds())
                else:
                    try:
                        await asyncio.wait_for(
                            self._nudge_event.wait(), timeout=self._tick_seconds()
                        )
                    except asyncio.TimeoutError:
                        pass
                    # Consume the nudge (level-triggered -> edge)
                    if self._nudge_event.is_set():
                        self._nudge_event.clear()

            except asyncio.CancelledError:
                logger.info(f"{worker_id}: scheduler cancelled, shutting down")
                break
            except Exception as exc:
                logger.error(f"{worker_id}: scheduler error: {exc}", exc_info=True)
                await asyncio.sleep(self.error_backoff_seconds)

        logger.info(f"{worker_id}: scheduler stopped")

    # Legacy alias: previously N workers called _worker_loop. Keep for tests that
    # patch it, but it now delegates to the scheduler.
    async def _worker_loop(self, worker_id: str) -> None:
        await self._scheduler_loop(worker_id)

    def _idle_backoff(self, consecutive_idle: int) -> float:
        """Retained for compat; geometric backoff now only for recovery polling.

        The scheduler no longer uses this — it sleeps a fixed tick. Recovery
        throttling in _process_integration_recovery still gates on wall-clock
        interval (arch A keeps that). This helper remains so external callers
        and tests that import it do not break.
        """
        ceiling = self.idle_sleep_seconds
        if self.config:
            ceiling = max(
                float(self.config.worker_idle_max_seconds or 0.0),
                self.idle_sleep_seconds,
            )
        step = min(max(consecutive_idle - 1, 0), 20)
        return min(self.idle_sleep_seconds * (2**step), ceiling)

    def _get_client(self) -> Any:
        """Return the shared service client, creating it on first use.

        Workers must reuse one client: creating a fresh supabase client per
        poll iteration leaks its unclosed httpx pools and SSL contexts
        (~2 MB/min at 3 workers polling every second), which OOM-killed the
        512 MB production instance every ~3 hours.
        """
        if self._client is None:
            self._client = get_service_client(self.config)
        return self._client

    async def _process_email_with_semaphore(self, email: dict, worker_id: str) -> None:
        """LLM extraction for one email, gated by the 8-wide semaphore."""
        sem = self._llm_semaphore
        if sem is None:
            await self._process_email(self._get_client(), worker_id, email)
            return
        async with sem:
            await self._process_email(self._get_client(), worker_id, email)

    async def _process_any_work(self, worker_id: str) -> bool:
        """Try to find and process work from any source.

        Polls in priority order:
        1. Approved events (need calendar sync)
        2. LLM email extraction (8-wide, single claim loop + semaphore)
        3. Calendar OAuth reconnect recovery (tagging/progress bookkeeping)

        Photo polling removed in inc 1.

        Args:
            worker_id: Unique identifier for this worker.

        Returns:
            True if work was processed, False if no work available.
        """
        if not self.config:
            raise RuntimeError("Worker pool config not initialized")

        client = self._get_client()

        # 1. Try approved events - requires Google Calendar (sole writer is worker)
        # Inc4: try direct pg pool first, fallback to PostgREST RPC
        if circuit_breaker.is_available("google_calendar"):
            try:
                if self.pg_pool is not None:
                    event = await claim_approved_event_for_sync_via_pool(
                        self.pg_pool, worker_id, lock_duration_seconds=300,
                    )
                else:
                    event = claim_approved_event_for_sync(
                        client, worker_id, lock_duration_seconds=300,
                    )
                if event:
                    await self._process_event_sync(client, worker_id, event)
                    return True
            except EventsError as e:
                logger.error(f"{worker_id}: Error claiming event: {e}")

        # 2. LLM email extraction — single claim loop keeps DB polling at
        # tick speed (no 18/s storm), semaphore fans out the LLM work to 8.
        if circuit_breaker.is_available("llm"):
            try:
                if self.pg_pool is not None:
                    email = await claim_pending_email_via_pool(self.pg_pool, worker_id, lock_duration_seconds=300)
                else:
                    email = claim_pending_email(client, worker_id, lock_duration_seconds=300)
                if email:
                    # Fire-and-forget behind semaphore; scheduler immediately
                    # re-drains to fill up to 8 in parallel.
                    task = asyncio.create_task(
                        self._process_email_with_semaphore(email, worker_id)
                    )
                    self._email_tasks.add(task)
                    task.add_done_callback(lambda t: self._email_tasks.discard(t))
                    return True
            except EmailError as e:
                logger.error(f"{worker_id}: Error claiming email: {e}")

        # 3. Advance calendar OAuth reconnect recovery. Pure DB bookkeeping
        # (no Calendar API calls), so it doesn't need the circuit breaker gate.
        if await self._process_integration_recovery(client, worker_id):
            return True

        return False

    async def _process_integration_recovery(self, client: Any, worker_id: str) -> bool:
        """Advance one pending/waiting google_calendar OAuth recovery generation.

        The actual retry of a parked event happens for free through the
        normal approved-event claim path once its integration is active
        again (see `claim_approved_event`'s active-integration check). This
        step only tags blocked events with `recovery_id` and tracks
        completion, so the UI can show "Catching up" instead of "Connected".

        6d: this runs on every idle tick of every worker. At
        `worker_pool_size=3` and `worker_idle_sleep_seconds=1.0` the
        unthrottled version issued roughly two no-op RPCs per worker per
        second — about 500k round-trips a day with nothing recovering. Both
        probes are therefore gated on `recovery_refresh_interval_seconds`,
        tracked on the pool instance.

        The gate is released the moment a pass finds real work, so an active
        catch-up still advances at full tick speed; only the idle case slows
        down. The cost is up to one interval of extra latency before a freshly
        created recovery is first noticed, which is immaterial for a progress
        indicator whose events retry through the normal claim path anyway.
        """
        # `config` is only populated once start() runs; an unconfigured pool
        # (direct unit-test construction) simply does not throttle.
        interval = (
            max(float(self.config.recovery_refresh_interval_seconds or 0.0), 0.0)
            if self.config
            else 0.0
        )
        now_monotonic = time.monotonic()
        if interval > 0 and (now_monotonic - self._last_recovery_probe_at) < interval:
            return False
        self._last_recovery_probe_at = now_monotonic

        try:
            recovery = claim_integration_recovery(client, worker_id, lock_seconds=120)
        except IntegrationError as e:
            logger.error(f"{worker_id}: Error claiming integration recovery: {e}")
            recovery = None

        if recovery:
            # Real work in flight — drop the gate so the next tick probes again.
            self._last_recovery_probe_at = 0.0
            try:
                tagged = requeue_calendar_recovery_batch(
                    client, recovery["id"], worker_id
                )
            except CalendarsError as e:
                logger.error(f"{worker_id}: Error requeuing calendar recovery batch: {e}")
                return False

            if tagged < 0:
                # The claim was lost (lock expired or another worker reclaimed
                # it) before tagging ran. The recovery stays 'processing' with
                # an expired lock and is picked back up by the next claim.
                logger.warning(
                    f"{worker_id}: Lost claim on calendar recovery "
                    f"{recovery['id']} before tagging (will self-heal on next claim)"
                )
                return False

            logger.info(
                f"{worker_id}: Tagged {tagged} event(s) for "
                f"calendar recovery {recovery['id']}"
            )
            return True

        try:
            refreshed = refresh_waiting_calendar_recoveries(client)
        except CalendarsError as e:
            logger.error(f"{worker_id}: Error refreshing waiting calendar recoveries: {e}")
            return False
        if refreshed > 0:
            # Generations completed this pass; keep probing at full speed.
            self._last_recovery_probe_at = 0.0
        return refreshed > 0

    async def _process_scheduled_task(
        self,
        client: Any,
        worker_id: str,
        task: dict[str, Any],
    ) -> None:
        """Process a scheduled task (currently photo_fetch only).

        Args:
            client: Supabase client.
            worker_id: Unique identifier for this worker.
            task: The claimed scheduled task.
        """
        from selko.workers.photo_fetch import process_photo_fetch_task

        task_id = task["id"]
        task_type = task["task_type"]
        payload = task["payload"]

        logger.info(f"{worker_id}: Processing scheduled task {task_id}: {task_type}")

        service_name = "google_photos" if task_type == "photo_fetch" else task_type

        try:
            if task_type == "photo_fetch":
                await process_photo_fetch_task(client, self.config, payload)
            else:
                raise ValueError(f"Unknown scheduled task type: {task_type}")

            complete_scheduled_task(client, task_id)
            circuit_breaker.record_success(service_name)
            logger.info(f"{worker_id}: Completed scheduled task {task_id}")

        except Exception as e:
            circuit_breaker.record_failure(service_name)
            logger.error(f"{worker_id}: Scheduled task {task_id} failed: {e}", exc_info=True)
            try:
                fail_scheduled_task(client, task_id, str(e))
            except Exception as fail_error:
                logger.error(f"{worker_id}: Failed to mark task as failed: {fail_error}")

    async def _process_email(
        self,
        client: Any,
        worker_id: str,
        email: dict[str, Any],
    ) -> None:
        """Process an email for event extraction.

        Args:
            client: Supabase client.
            worker_id: Unique identifier for this worker.
            email: The claimed email record.
        """
        from selko.workers.email_process import process_email

        email_id = email["id"]
        subject = email.get("subject", "(no subject)")[:50]

        logger.info(f"{worker_id}: Processing email {email_id}: {subject}")

        try:
            result = await asyncio.wait_for(
                process_email(client, self.config, email),
                timeout=self.config.email_processing_timeout,
            )
            # Sender-ignored and calendar-invite emails are already left in a
            # terminal "skipped" state by process_email_for_events; don't
            # overwrite that back to "processed".
            if not (result or {}).get("skipped"):
                complete_email_processing(client, email_id)
            logger.info(f"{worker_id}: Completed email {email_id}")
            circuit_breaker.record_success("llm")

        except asyncio.TimeoutError:
            error_msg = f"Email processing timed out after {self.config.email_processing_timeout}s"
            circuit_breaker.record_failure("llm")
            logger.error(f"{worker_id}: {error_msg} for email {email_id}")
            try:
                fail_email_processing(client, email_id, error_msg)
            except Exception as fail_error:
                logger.error(f"{worker_id}: Failed to mark email as failed: {fail_error}")

        except Exception as e:
            circuit_breaker.record_failure("llm")
            logger.error(f"{worker_id}: Email {email_id} failed: {e}", exc_info=True)
            try:
                fail_email_processing(client, email_id, str(e))
            except Exception as fail_error:
                logger.error(f"{worker_id}: Failed to mark email as failed: {fail_error}")

    async def _process_photo(
        self,
        client: Any,
        worker_id: str,
        photo: dict[str, Any],
    ) -> None:
        """Process a photo for event extraction.

        Args:
            client: Supabase client.
            worker_id: Unique identifier for this worker.
            photo: The claimed photo record.
        """
        from selko.workers.photo_process import process_photo

        photo_id = photo["id"]
        filename = photo.get("filename", "(unknown)")[:50]

        logger.info(f"{worker_id}: Processing photo {photo_id}: {filename}")

        try:
            await asyncio.wait_for(
                process_photo(client, self.config, photo),
                timeout=self.config.photo_processing_timeout,
            )
            complete_photo_processing(client, photo_id)
            logger.info(f"{worker_id}: Completed photo {photo_id}")
            circuit_breaker.record_success("llm")
            circuit_breaker.record_success("google_photos")

        except asyncio.TimeoutError:
            error_msg = f"Photo processing timed out after {self.config.photo_processing_timeout}s"
            circuit_breaker.record_failure("llm")
            logger.error(f"{worker_id}: {error_msg} for photo {photo_id}")
            try:
                fail_photo_processing(client, photo_id, error_msg)
            except Exception as fail_error:
                logger.error(f"{worker_id}: Failed to mark photo as failed: {fail_error}")

        except Exception as e:
            circuit_breaker.record_failure("llm")
            logger.error(f"{worker_id}: Photo {photo_id} failed: {e}", exc_info=True)
            try:
                fail_photo_processing(client, photo_id, str(e))
            except Exception as fail_error:
                logger.error(f"{worker_id}: Failed to mark photo as failed: {fail_error}")

    async def _process_event_sync(
        self,
        client: Any,
        worker_id: str,
        event: dict[str, Any],
    ) -> None:
        """Sync an approved event to Google Calendar.

        Args:
            client: Supabase client.
            worker_id: Unique identifier for this worker.
            event: The claimed event record.
        """
        from selko.workers.calendar_sync import sync_event

        event_id = event["id"]
        title = event.get("title", "(no title)")[:50]

        logger.info(f"{worker_id}: Syncing event {event_id}: {title}")

        try:
            quota_result = QuotaService(client).check_and_increment(
                event["user_id"], "calendar_syncs"
            )
            if not quota_result.allowed:
                defer_event_sync_for_quota(
                    client,
                    event_id,
                    event["sync_attempts"],
                    quota_result.resets_at,
                )
                return

            google_event_id = await asyncio.wait_for(
                sync_event(client, self.config, event),
                timeout=self.config.event_sync_timeout,
            )
            complete_event_sync(client, event_id, google_event_id)
            logger.info(f"{worker_id}: Completed event sync {event_id}")
            circuit_breaker.record_success("google_calendar")

        except asyncio.TimeoutError:
            error_msg = f"Event sync timed out after {self.config.event_sync_timeout}s"
            circuit_breaker.record_failure("google_calendar")
            logger.error(f"{worker_id}: {error_msg} for event {event_id}")
            try:
                fail_event_sync(client, event_id, error_msg)
            except Exception as fail_error:
                logger.error(f"{worker_id}: Failed to mark event sync as failed: {fail_error}")

        except Exception as e:
            classification = getattr(e, "classification", None) or classify_calendar_error(e)
            if classification.counts_toward_circuit_breaker:
                circuit_breaker.record_failure("google_calendar")
            logger.error(
                f"{worker_id}: Event {event_id} sync failed "
                f"({classification.code}): {e}",
                exc_info=True,
            )
            try:
                if classification.code in ("oauth_required", "oauth_scope_required"):
                    # Not a real sync attempt against the user's calendar:
                    # park it so it resumes automatically once the user
                    # reauthorizes, instead of burning retries toward
                    # dead-letter.
                    park_event_for_oauth_reauth(
                        client,
                        event_id,
                        event["sync_attempts"],
                        classification.code,
                        classification.user_message,
                    )
                else:
                    fail_event_sync(client, event_id, str(e))
            except Exception as fail_error:
                logger.error(f"{worker_id}: Failed to mark event sync as failed: {fail_error}")
