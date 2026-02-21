"""Worker pool for continuously processing background work.

This module implements a pool of long-running asyncio tasks that continuously
poll for work from four sources:
1. Scheduled tasks (e.g., email_fetch, photo_fetch)
2. Pending emails (status-based claiming)
3. Pending photos (status-based claiming)
4. Approved events (status-based claiming)

This replaces the job queue with direct status-based polling of data tables.
"""

import asyncio
import logging
import os
from typing import Any, Optional

from selko.config import Config, load_config
from selko.services.auth import get_service_client
from selko.services.circuit_breaker import circuit_breaker
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
    complete_event_sync,
    fail_event_sync,
)
from selko.services.photos import (
    PhotosError,
    claim_pending_photo,
    complete_photo_processing,
    fail_photo_processing,
)

logger = logging.getLogger(__name__)


class WorkerPool:
    """Manages a pool of long-running worker tasks for background processing.

    The worker pool creates multiple asyncio tasks that continuously poll for
    work from scheduled tasks and data tables. This provides:
    - Low latency (work starts processing within ~1 second)
    - High throughput (multiple items processed concurrently)
    - Graceful shutdown (workers complete current work before stopping)
    - Single source of truth (data tables ARE the queue)
    """

    def __init__(
        self,
        num_workers: int = 3,
        idle_sleep_seconds: float = 1.0,
        error_backoff_seconds: float = 5.0,
    ):
        """Initialize the worker pool.

        Args:
            num_workers: Number of concurrent worker tasks (default: 3).
            idle_sleep_seconds: Time to sleep when no work available (default: 1.0).
            error_backoff_seconds: Time to sleep after errors (default: 5.0).
        """
        self.num_workers = num_workers
        self.idle_sleep_seconds = idle_sleep_seconds
        self.error_backoff_seconds = error_backoff_seconds
        self.tasks: list[asyncio.Task] = []
        self.running = False
        self.config: Optional[Config] = None

    async def start(self) -> None:
        """Start the worker pool by spawning worker tasks.

        Creates num_workers asyncio tasks that will run continuously
        until stop() is called.
        """
        if self.running:
            logger.warning("Worker pool already running")
            return

        logger.info(f"Starting worker pool with {self.num_workers} workers")
        self.running = True
        self.config = load_config()

        # Spawn worker tasks
        for i in range(self.num_workers):
            worker_id = f"worker-{os.getpid()}-{i}"
            task = asyncio.create_task(
                self._worker_loop(worker_id),
                name=worker_id,
            )
            self.tasks.append(task)

        logger.info(f"Worker pool started with {len(self.tasks)} workers")

    async def stop(self, timeout: float = 30.0) -> None:
        """Gracefully stop all workers.

        Sets the running flag to False and cancels all worker tasks,
        waiting for them to complete or timeout.

        Args:
            timeout: Maximum time to wait for workers to finish (default: 30 seconds).
        """
        if not self.running:
            logger.warning("Worker pool not running")
            return

        logger.info(f"Stopping worker pool ({len(self.tasks)} workers)...")
        self.running = False

        # Cancel all tasks
        for task in self.tasks:
            if not task.done():
                task.cancel()

        # Wait for tasks to finish with timeout
        try:
            await asyncio.wait_for(
                asyncio.gather(*self.tasks, return_exceptions=True),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(f"Worker pool shutdown timed out after {timeout}s")

        self.tasks.clear()
        logger.info("Worker pool stopped")

    async def _worker_loop(self, worker_id: str) -> None:
        """Main worker loop - continuously find and process work.

        This loop runs until self.running becomes False. It polls four sources:
        1. Scheduled tasks (email_fetch, photo_fetch)
        2. Pending emails (for LLM processing)
        3. Pending photos (for LLM processing)
        4. Approved events (for calendar sync)

        Args:
            worker_id: Unique identifier for this worker.
        """
        logger.info(f"{worker_id}: Started")

        while self.running:
            try:
                # Try to find and process any work
                processed = await self._process_any_work(worker_id)

                if not processed:
                    # No work available, sleep briefly
                    await asyncio.sleep(self.idle_sleep_seconds)

            except asyncio.CancelledError:
                # Graceful shutdown
                logger.info(f"{worker_id}: Cancelled, shutting down")
                break

            except Exception as e:
                # Unexpected error in worker loop
                logger.error(f"{worker_id}: Unexpected error: {e}", exc_info=True)
                await asyncio.sleep(self.error_backoff_seconds)

        logger.info(f"{worker_id}: Stopped")

    async def _process_any_work(self, worker_id: str) -> bool:
        """Try to find and process work from any source.

        Polls in priority order:
        1. Scheduled tasks (periodic operations like email_fetch, photo_fetch)
        2. Pending emails (need LLM processing)
        3. Pending photos (need LLM processing)
        4. Approved events (need calendar sync)

        Args:
            worker_id: Unique identifier for this worker.

        Returns:
            True if work was processed, False if no work available.
        """
        if not self.config:
            raise RuntimeError("Worker pool config not initialized")

        client = get_service_client(self.config)

        # 1. Try scheduled tasks first (email_fetch, photo_fetch)
        task_types = []
        if circuit_breaker.is_available("gmail"):
            task_types.append("email_fetch")
        if circuit_breaker.is_available("google_photos"):
            task_types.append("photo_fetch")

        if task_types:
            try:
                task = claim_scheduled_task(client, task_types, worker_id)
                if task:
                    await self._process_scheduled_task(client, worker_id, task)
                    return True
            except ScheduledTasksError as e:
                logger.error(f"{worker_id}: Error claiming scheduled task: {e}")

        # 2. Try pending emails - requires LLM
        if circuit_breaker.is_available("llm"):
            try:
                email = claim_pending_email(
                    client, worker_id, lock_duration_seconds=600,
                )
                if email:
                    await self._process_email(client, worker_id, email)
                    return True
            except EmailError as e:
                logger.error(f"{worker_id}: Error claiming email: {e}")

        # 3. Try pending photos - requires LLM and Google Photos
        if circuit_breaker.is_available("llm") and circuit_breaker.is_available("google_photos"):
            try:
                photo = claim_pending_photo(
                    client, worker_id, lock_duration_seconds=600,
                )
                if photo:
                    await self._process_photo(client, worker_id, photo)
                    return True
            except PhotosError as e:
                logger.error(f"{worker_id}: Error claiming photo: {e}")

        # 4. Try approved events - requires Google Calendar
        if circuit_breaker.is_available("google_calendar"):
            try:
                event = claim_approved_event_for_sync(
                    client, worker_id, lock_duration_seconds=300,
                )
                if event:
                    await self._process_event_sync(client, worker_id, event)
                    return True
            except EventsError as e:
                logger.error(f"{worker_id}: Error claiming event: {e}")

        return False

    async def _process_scheduled_task(
        self,
        client: Any,
        worker_id: str,
        task: dict[str, Any],
    ) -> None:
        """Process a scheduled task (e.g., email_fetch, photo_fetch).

        Args:
            client: Supabase client.
            worker_id: Unique identifier for this worker.
            task: The claimed scheduled task.
        """
        from selko.workers.email_fetch import process_email_fetch_task
        from selko.workers.photo_fetch import process_photo_fetch_task

        task_id = task["id"]
        task_type = task["task_type"]
        payload = task["payload"]

        # Map task types to their circuit breaker service
        task_service_map = {
            "email_fetch": "gmail",
            "photo_fetch": "google_photos",
        }

        logger.info(f"{worker_id}: Processing scheduled task {task_id}: {task_type}")

        service_name = task_service_map.get(task_type, task_type)

        try:
            if task_type == "email_fetch":
                await process_email_fetch_task(client, self.config, payload)
            elif task_type == "photo_fetch":
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
            async with asyncio.timeout(self.config.email_processing_timeout):
                await process_email(client, self.config, email)
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
            async with asyncio.timeout(self.config.photo_processing_timeout):
                await process_photo(client, self.config, photo)
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
            async with asyncio.timeout(self.config.event_sync_timeout):
                google_event_id = await sync_event(client, self.config, event)
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
            circuit_breaker.record_failure("google_calendar")
            logger.error(f"{worker_id}: Event {event_id} sync failed: {e}", exc_info=True)
            try:
                fail_event_sync(client, event_id, str(e))
            except Exception as fail_error:
                logger.error(f"{worker_id}: Failed to mark event sync as failed: {fail_error}")
