"""Entry point for the dedicated Render worker process."""

from __future__ import annotations

import asyncio
import logging
import signal

from selko.config import load_config
from selko.services.auth import get_service_client
from selko.services.email_sync_health import EmailSyncHealthEvaluator, ResendOperationalNotifier
from selko.workers.email_ingestion import EmailIngestionWorker
from selko.workers.pool import WorkerPool

logger = logging.getLogger(__name__)


async def main() -> None:
    config = load_config()
    client = get_service_client(config)
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    def request_shutdown() -> None:
        logger.info("Worker shutdown requested")
        stop_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, request_shutdown)
        except NotImplementedError:
            signal.signal(sig, lambda *_args: request_shutdown())

    downstream_pool = WorkerPool(
        num_workers=config.worker_pool_size,
        idle_sleep_seconds=config.worker_idle_sleep_seconds,
        error_backoff_seconds=config.worker_error_backoff_seconds,
    )
    await downstream_pool.start()
    process_id = __import__("os").getpid()
    coordinator = EmailIngestionWorker(client, config, f"poller-{process_id}-coordinator")
    ingestion_workers = [coordinator]
    ingestion_tasks = [asyncio.create_task(coordinator.coordinator_loop(), name="email-sync-coordinator")]
    for index in range(max(config.email_acquisition_concurrency, 1)):
        worker = EmailIngestionWorker(client, config, f"poller-{process_id}-acquisition-{index}")
        ingestion_workers.append(worker)
        ingestion_tasks.append(asyncio.create_task(worker.acquisition_loop(), name=f"email-acquisition-{index}"))
    for index in range(max(config.email_attachment_concurrency, 1)):
        worker = EmailIngestionWorker(client, config, f"poller-{process_id}-attachment-{index}")
        ingestion_workers.append(worker)
        ingestion_tasks.append(asyncio.create_task(worker.attachment_loop(), name=f"email-attachment-{index}"))
    notifier = ResendOperationalNotifier(config)
    health = EmailSyncHealthEvaluator(client, config, notifier)
    health_task = asyncio.create_task(health.run(stop_event), name="email-sync-health")
    try:
        await stop_event.wait()
    finally:
        for worker in ingestion_workers:
            worker.stop()
        for task in ingestion_tasks:
            task.cancel()
        health_task.cancel()
        await asyncio.gather(*ingestion_tasks, return_exceptions=True)
        await asyncio.gather(health_task, return_exceptions=True)
        await downstream_pool.stop()
        logger.info("Dedicated worker stopped; unfinished leases remain reclaimable")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
