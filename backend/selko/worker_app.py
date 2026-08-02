"""Standalone entry point for a dedicated ingestion worker process.

The deployed topology runs ingestion inside the API process (see
`selko.api.app`), which is why this module is not required in production. It
stays supported for local staging drills and for splitting ingestion onto its
own service later; both paths share `IngestionRuntime`, so they cannot drift.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from selko.config import load_config
from selko.services.auth import get_service_client
from selko.workers.ingestion_runtime import IngestionRuntime
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
    runtime = IngestionRuntime(client, config)
    await runtime.start()
    try:
        await stop_event.wait()
    finally:
        await runtime.stop()
        await downstream_pool.stop()
        logger.info("Dedicated worker stopped; unfinished leases remain reclaimable")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
