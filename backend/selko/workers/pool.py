"""Worker pool for continuously processing background jobs.

This module implements a pool of long-running asyncio tasks that continuously
poll the job queue and process jobs as they become available, replacing the
scheduled polling approach with immediate job processing.
"""

import asyncio
import logging
import os
from typing import Any, Optional

from selko.config import Config, load_config
from selko.services.auth import get_service_client
from selko.services.jobs import JobsError, claim_job, complete_job, fail_job

logger = logging.getLogger(__name__)


class WorkerPool:
    """Manages a pool of long-running worker tasks for background job processing.
    
    The worker pool creates multiple asyncio tasks that continuously poll the
    job queue and process jobs as they become available. This provides:
    - Low latency (jobs start processing within ~1 second)
    - High throughput (multiple jobs processed concurrently)
    - Graceful shutdown (workers complete current jobs before stopping)
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
            idle_sleep_seconds: Time to sleep when no jobs available (default: 1.0).
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
        """Main worker loop - continuously claim and process jobs.
        
        This loop runs until self.running becomes False. It:
        1. Claims the next available job from the queue
        2. Processes the job by dispatching to the appropriate handler
        3. Marks the job as completed or failed
        4. Sleeps briefly if no jobs available or on error
        
        Args:
            worker_id: Unique identifier for this worker.
        """
        logger.info(f"{worker_id}: Started")

        # Import worker functions here to avoid circular imports
        from selko.workers.email_fetch import process_email_fetch_job
        from selko.workers.email_process import process_email_process_job
        from selko.workers.calendar_sync import process_calendar_sync_job

        # Map job types to handler functions
        handlers = {
            "email_fetch": process_email_fetch_job,
            "email_process": process_email_process_job,
            "calendar_sync": process_calendar_sync_job,
        }

        while self.running:
            try:
                # Try to claim a job
                job = await self._claim_and_process_job(worker_id, handlers)

                if not job:
                    # No jobs available, sleep briefly
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

    async def _claim_and_process_job(
        self,
        worker_id: str,
        handlers: dict[str, Any],
    ) -> Optional[dict[str, Any]]:
        """Claim and process a single job.
        
        Args:
            worker_id: Unique identifier for this worker.
            handlers: Dict mapping job_type to handler function.
        
        Returns:
            Job dict if processed, None if no jobs available.
        """
        if not self.config:
            raise RuntimeError("Worker pool config not initialized")

        # Get service client for this job
        client = get_service_client(self.config)

        try:
            # Atomically claim next job
            job = claim_job(
                client,
                list(handlers.keys()),
                worker_id,
                lock_duration_seconds=300,  # 5 minute lock
            )

            if not job:
                return None

            job_id = job["id"]
            job_type = job["job_type"]
            payload = job["payload"]

            logger.info(f"{worker_id}: Processing job {job_id}: {job_type}")

            # Dispatch to appropriate handler
            handler = handlers.get(job_type)
            if not handler:
                raise JobsError(f"Unknown job type: {job_type}")

            # Execute the job
            await handler(client, self.config, job_id, payload)

            # Mark as completed
            complete_job(client, job_id)
            logger.info(f"{worker_id}: Completed job {job_id}")

            return job

        except Exception as e:
            # Job failed - mark it and let retry logic handle it
            logger.error(f"{worker_id}: Job {job_id} failed: {e}", exc_info=True)
            try:
                fail_job(client, job_id, str(e), retry=True)
            except Exception as fail_error:
                logger.error(
                    f"{worker_id}: Failed to mark job as failed: {fail_error}"
                )

            return job  # Return job so we don't sleep
