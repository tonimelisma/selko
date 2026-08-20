"""Worker pool for continuously processing background work.

One scheduler task drains the queue in priority order:

1. Approved events → calendar sync (semaphore-bounded executor tasks)
2. Pending emails → LLM event extraction (semaphore-bounded executor tasks)
3. Calendar OAuth recovery bookkeeping (claim/tag/refresh)

Photo ingestion is parked (egress inc 1). Email ingestion *discovery* is
owned solely by IngestionRuntime; the LLM extraction of already-saved emails
runs here. Work arrives by NOTIFY through the WorkListener; the safety-net
poll is a floor, not a schedule. Durability stays in SQL leases.
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
from selko.services.emails import (
    EmailError,
    claim_pending_email,
    fail_email_processing,
)
from selko.services.events import (
    EventsError,
    claim_approved_event_for_sync,
    complete_event_cancellation,
    complete_event_sync,
    defer_event_sync_for_quota,
    fail_event_sync,
    park_event_for_oauth_reauth,
)
from selko.services.quotas import QuotaService
from selko.workers.concurrency import _try_acquire

logger = logging.getLogger(__name__)


class WorkerPool:
    """Manages a single scheduler that drains the calendar queue.

    Egress inc 3+4: previously this spawned N independent busy-polling workers,
    each issuing up to 6 RPCs/sec. Now one scheduler drains the queue (claim
    and process until empty) then sleeps to the next tick. An in-process
    asyncio.Event nudges the scheduler immediately for user-initiated work
    (approve/retry). If the nudge is missed, the next tick catches it — degraded
    latency, never lost.

    R3: single scheduler with Semaphore concurrency for calendar sync; the
    real knob is config.worker_calendar_sync_concurrency. Durability stays in
    SQL leases.
    """

    def __init__(
        self,
        pg_pool,
        work_listener,
        idle_sleep_seconds: float = 1.0,
        error_backoff_seconds: float = 5.0,
    ):
        """Initialize the worker pool.

        Args:
            idle_sleep_seconds: Idle tick interval (the fixed sleep between
                drain passes; previously the busy-poll sleep).
            error_backoff_seconds: Time to sleep after errors.
        """
        self.idle_sleep_seconds = idle_sleep_seconds
        self.error_backoff_seconds = error_backoff_seconds
        self.pg_pool = pg_pool
        self._work_listener = work_listener
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
        # C4: executor semaphores. Created here — since Python 3.10 asyncio
        # primitives do not bind to a loop at construction, so direct
        # construction in tests works. Acquired BEFORE the claim so a claimed
        # row never waits in a queue holding its lease.
        self._llm_semaphore = asyncio.Semaphore(
            max(int(getattr(self.config, "llm_extraction_concurrency", 8) or 8), 1)
        )
        self._calendar_semaphore = asyncio.Semaphore(
            max(int(getattr(self.config, "worker_calendar_sync_concurrency", 2) or 2), 1)
        )
        self._email_tasks: set[asyncio.Task] = set()
        self._event_sync_tasks: set[asyncio.Task] = set()

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

        One scheduler task drains the queue and sleeps to the next tick, with
        an in-process nudge for approve/retry paths.
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
        self._email_tasks = set()
        self._event_sync_tasks = set()

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

        # Also cancel any in-flight executor tasks (LLM extraction + calendar sync)
        for task in list(self._email_tasks) + list(self._event_sync_tasks):
            if not task.done():
                task.cancel()

        try:
            await asyncio.wait_for(
                asyncio.gather(
                    *self.tasks, *self._email_tasks, *self._event_sync_tasks,
                    return_exceptions=True,
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(f"Worker pool shutdown timed out after {timeout}s")

        self.tasks.clear()
        self._email_tasks.clear()
        self._event_sync_tasks.clear()
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
        Concurrency comes from the semaphore-bounded executor tasks (calendar
        sync and LLM extraction) fanned out by each pass.

        The nudge (approve/retry) and the WorkListener NOTIFY wake the idle
        sleep immediately; if missed, the next tick catches it.
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

                # --- idle: wait for nudge, notification, or safety poll ---
                waiters = [asyncio.create_task(self._nudge_event.wait())]
                for work_type in ("event_approved", "email_pending"):
                    waiters.append(
                        asyncio.create_task(self._work_listener.event_for(work_type).wait())
                    )
                _, pending = await asyncio.wait(
                    waiters,
                    timeout=float(self.config.worker_safety_poll_seconds),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                if self._nudge_event.is_set():
                    self._nudge_event.clear()
                for work_type in ("event_approved", "email_pending"):
                    self._work_listener.event_for(work_type).clear()

            except asyncio.CancelledError:
                logger.info(f"{worker_id}: scheduler cancelled, shutting down")
                break
            except Exception as exc:
                logger.error(f"{worker_id}: scheduler error: {exc}", exc_info=True)
                await asyncio.sleep(self.error_backoff_seconds)

        logger.info(f"{worker_id}: scheduler stopped")

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
        # C4: acquire the calendar executor slot BEFORE claiming so a claimed
        # event never waits in a queue holding its lease.
        if circuit_breaker.is_available("google_calendar"):
            try:
                if await _try_acquire(self._calendar_semaphore):
                    try:
                        event = await claim_approved_event_for_sync(
                            self.pg_pool, worker_id,
                            lock_duration_seconds=getattr(
                                self.config, "llm_claim_lease_seconds", 900
                            ),
                        )
                    except BaseException:
                        self._calendar_semaphore.release()
                        raise
                    if event:
                        task = asyncio.create_task(
                            self._process_event_sync(client, worker_id, event)
                        )
                        self._event_sync_tasks.add(task)
                        task.add_done_callback(self._event_sync_tasks.discard)
                        task.add_done_callback(lambda _: self._calendar_semaphore.release())
                        return True
                    self._calendar_semaphore.release()
            except EventsError as e:
                logger.error(f"{worker_id}: Error claiming event: {e}")

        # 2. LLM email extraction — single claim loop keeps DB polling at
        # tick speed (no 18/s storm), semaphore fans out the LLM work. C4:
        # non-blocking acquire so a full executor pool does not stall the
        # other work types; the claim happens only when a slot is free.
        if circuit_breaker.is_available("llm"):
            try:
                if await _try_acquire(self._llm_semaphore):
                    try:
                        email = await claim_pending_email(
                            self.pg_pool, worker_id,
                            lock_duration_seconds=getattr(
                                self.config, "llm_claim_lease_seconds", 900
                            ),
                        )
                    except BaseException:
                        self._llm_semaphore.release()
                        raise
                    if email:
                        # Fire-and-forget behind the already-held semaphore;
                        # the scheduler immediately re-drains to fill up to N.
                        task = asyncio.create_task(
                            self._process_email(client, worker_id, email)
                        )
                        self._email_tasks.add(task)
                        task.add_done_callback(lambda t: self._email_tasks.discard(t))
                        task.add_done_callback(lambda _: self._llm_semaphore.release())
                        return True
                    self._llm_semaphore.release()
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

        6d: this runs on every idle tick. Unthrottled, the old multi-worker
        topology issued roughly two no-op RPCs per worker per second — about
        500k round-trips a day with nothing recovering. Both probes are
        therefore gated on `recovery_refresh_interval_seconds`, tracked on
        the pool instance.

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
            recovery = await claim_integration_recovery(self.pg_pool, worker_id, lock_seconds=120)
        except IntegrationError as e:
            logger.error(f"{worker_id}: Error claiming integration recovery: {e}")
            recovery = None

        if recovery:
            # Real work in flight — drop the gate so the next tick probes again.
            self._last_recovery_probe_at = 0.0
            try:
                tagged = await requeue_calendar_recovery_batch(
                    self.pg_pool, recovery["id"], worker_id
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
            refreshed = await refresh_waiting_calendar_recoveries(self.pg_pool)
        except CalendarsError as e:
            logger.error(f"{worker_id}: Error refreshing waiting calendar recoveries: {e}")
            return False
        if refreshed > 0:
            # Generations completed this pass; keep probing at full speed.
            self._last_recovery_probe_at = 0.0
        return refreshed > 0

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
        generation = int(email.get("lock_generation") or 0)

        logger.info(f"{worker_id}: Processing email {email_id}: {subject}")

        try:
            result = await asyncio.wait_for(
                process_email(client, self.config, email),
                timeout=self.config.email_processing_timeout,
            )
            # The extraction RPC terminalizes the email atomically with its
            # event decisions.  A fenced outcome is normal: a replacement
            # worker owns the lease and this timed-out/zombie worker must not
            # retry or overwrite it.
            logger.info(f"{worker_id}: Completed email {email_id}")
            circuit_breaker.record_success("llm")

        except asyncio.TimeoutError:
            error_msg = f"Email processing timed out after {self.config.email_processing_timeout}s"
            circuit_breaker.record_failure("llm")
            logger.error(f"{worker_id}: {error_msg} for email {email_id}")
            try:
                await fail_email_processing(
                    self.pg_pool, email_id, worker_id, generation, error_msg,
                    self.config.email_retry_base_seconds, self.config.email_retry_max_seconds,
                )
            except Exception as fail_error:
                logger.error(f"{worker_id}: Failed to mark email as failed: {fail_error}")

        except Exception as e:
            circuit_breaker.record_failure("llm")
            logger.error(f"{worker_id}: Email {email_id} failed: {e}", exc_info=True)
            try:
                await fail_email_processing(
                    self.pg_pool, email_id, worker_id, generation, str(e),
                    self.config.email_retry_base_seconds, self.config.email_retry_max_seconds,
                )
            except Exception as fail_error:
                logger.error(f"{worker_id}: Failed to mark email as failed: {fail_error}")

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
        from selko.workers.calendar_sync import cancel_event, sync_event

        event_id = event["id"]
        work_item_id = event.get("calendar_work_item_id", event_id)
        title = event.get("title", "(no title)")[:50]

        logger.info(f"{worker_id}: Syncing event {event_id}: {title}")
        is_cancellation = event.get("calendar_sync_action") == "cancel"
        generation = int(event.get("calendar_work_generation") or 0)
        fenced_claim = "calendar_work_generation" in event or "locked_by" in event

        try:
            quota_result = QuotaService(client).check_and_increment(
                event["user_id"], "calendar_syncs"
            )
            if not quota_result.allowed:
                defer_args = [
                    self.pg_pool, work_item_id, event["sync_attempts"], quota_result.resets_at
                ]
                if fenced_claim:
                    defer_args.extend([worker_id, generation])
                await defer_event_sync_for_quota(*defer_args)
                return

            if is_cancellation:
                await asyncio.wait_for(
                    cancel_event(client, self.config, event),
                    timeout=self.config.event_sync_timeout,
                )
                if fenced_claim:
                    await complete_event_cancellation(
                        self.pg_pool, work_item_id, worker_id, generation
                    )
                logger.info(f"{worker_id}: Completed event cancellation {event_id}")
            else:
                google_event_id = await asyncio.wait_for(
                    sync_event(client, self.config, event),
                    timeout=self.config.event_sync_timeout,
                )
                if fenced_claim:
                    await complete_event_sync(
                        self.pg_pool, work_item_id, google_event_id, worker_id, generation
                    )
                else:
                    await complete_event_sync(self.pg_pool, work_item_id, google_event_id)
                logger.info(f"{worker_id}: Completed event sync {event_id}")
            circuit_breaker.record_success("google_calendar")

        except asyncio.TimeoutError:
            error_msg = f"Event {'cancellation' if is_cancellation else 'sync'} timed out after {self.config.event_sync_timeout}s"
            circuit_breaker.record_failure("google_calendar")
            logger.error(f"{worker_id}: {error_msg} for event {event_id}")
            try:
                if fenced_claim:
                    await fail_event_sync(
                        self.pg_pool, work_item_id, error_msg, worker_id, generation
                    )
                else:
                    await fail_event_sync(self.pg_pool, work_item_id, error_msg)
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
                    park_args = [
                        self.pg_pool,
                        work_item_id,
                        event["sync_attempts"],
                        classification.code,
                        classification.user_message,
                    ]
                    if fenced_claim:
                        park_args.extend([worker_id, generation])
                    await park_event_for_oauth_reauth(*park_args)
                else:
                    if fenced_claim:
                        await fail_event_sync(
                            self.pg_pool, work_item_id, str(e), worker_id, generation
                        )
                    else:
                        await fail_event_sync(self.pg_pool, work_item_id, str(e))
            except Exception as fail_error:
                logger.error(f"{worker_id}: Failed to mark event sync as failed: {fail_error}")
