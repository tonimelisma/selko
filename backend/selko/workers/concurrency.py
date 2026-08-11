"""Small concurrency primitives shared by worker executors."""

from __future__ import annotations

import asyncio


async def _try_acquire(sem: asyncio.Semaphore, timeout: float = 0.01) -> bool:
    """Acquire without parking the shared drain loop.

    Every executor path acquires before claiming, so a claimed row never waits
    in a queue while holding its lease. A saturated executor for one work type
    therefore cannot stall the other work types. Python 3.14 correctly rolls
    back a cancelled ``Semaphore.acquire``; this bounded wait relies on that
    cancellation-safe behaviour.
    """
    try:
        await asyncio.wait_for(sem.acquire(), timeout=timeout)
        return True
    except asyncio.TimeoutError:
        return False
