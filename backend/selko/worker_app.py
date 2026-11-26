"""Standalone entry point for the worker set without the API.

The deployed topology runs ingestion inside the API process (see
`selko.api.app`), which is why this module is not required in production. It
runs the same `WorkerPool` and `IngestionRuntime` over the same SQLite
database, so the two entry points cannot drift. Only one process may own the
database: never run this next to the API on the same data directory.
"""

from __future__ import annotations

import asyncio
import logging
import signal

from selko.config import load_config
from selko.db.runtime import close_database, open_database
from selko.db.startup import reset_leases_at_startup
from selko.workers.ingestion_runtime import IngestionRuntime
from selko.workers.pool import WorkerPool

logger = logging.getLogger(__name__)


async def main() -> None:
    config = load_config()
    db = open_database(config.data_dir, owner="selko.worker_app")
    await db.signals.start()
    # One process owns every lease, so any lease present now belongs to a
    # dead run. Release them before a single worker starts.
    released = await db.run(reset_leases_at_startup, db)
    if any(released.values()):
        logger.info("Released stale leases on startup: %s", {k: v for k, v in released.items() if v})
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
        idle_sleep_seconds=config.worker_idle_sleep_seconds,
        error_backoff_seconds=config.worker_error_backoff_seconds,
        pg_pool=db,
        work_listener=db.signals,
    )
    await downstream_pool.start()
    runtime = IngestionRuntime(db, config, pg_pool=db, work_listener=db.signals)
    await runtime.start()
    try:
        await stop_event.wait()
    finally:
        await runtime.stop()
        await downstream_pool.stop()
        await db.signals.stop()
        close_database()
        logger.info("Dedicated worker stopped; unfinished leases are released at the next start")


if __name__ == "__main__":
    from selko.logging import setup_logging

    setup_logging()
    asyncio.run(main())
