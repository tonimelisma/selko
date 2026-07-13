"""Process memory instrumentation for diagnosing leaks in production.

Logs a compact one-line memory summary (RSS, file descriptors, threads,
GC-tracked objects) at a fixed interval so Render logs show how memory
evolves between OOM restarts. When tracemalloc mode is enabled, also logs
the top allocation sites that grew since the previous interval, which
attributes a leak to specific file:line locations.

Stdlib-only by design (no psutil) to keep the production image unchanged.
"""

import asyncio
import gc
import logging
import os
import resource
import sys
import threading
import tracemalloc
from typing import Optional

logger = logging.getLogger(__name__)

# Number of stack frames tracemalloc records per allocation. Higher values
# cost more memory; one frame is enough to name the allocating file:line.
TRACEMALLOC_FRAMES = 1

# How many allocation sites to log per tracemalloc diff.
TRACEMALLOC_TOP_N = 10


def get_rss_bytes() -> Optional[int]:
    """Return current resident set size in bytes, or None if unavailable.

    Reads VmRSS from /proc/self/status on Linux (current RSS). Falls back
    to ru_maxrss (peak RSS) elsewhere, e.g. macOS development machines.
    """
    try:
        with open("/proc/self/status", encoding="ascii") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) * 1024
    except OSError:
        pass

    try:
        ru_maxrss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        # ru_maxrss is bytes on macOS, kilobytes on Linux
        if sys.platform == "darwin":
            return ru_maxrss
        return ru_maxrss * 1024
    except (OSError, ValueError):
        return None


def get_fd_count() -> Optional[int]:
    """Return the number of open file descriptors, or None if unavailable.

    A steadily climbing FD count alongside RSS points at leaked sockets or
    HTTP clients rather than plain object retention.
    """
    try:
        return len(os.listdir("/proc/self/fd"))
    except OSError:
        try:
            return len(os.listdir("/dev/fd"))
        except OSError:
            return None


def sample_memory_stats() -> dict:
    """Collect a snapshot of process memory-related counters."""
    return {
        "rss_bytes": get_rss_bytes(),
        "fd_count": get_fd_count(),
        "thread_count": threading.active_count(),
        "gc_objects": len(gc.get_objects(generation=2)),
    }


def format_memory_stats(stats: dict) -> str:
    """Format a stats snapshot as a single log line."""
    rss = stats.get("rss_bytes")
    rss_mb = f"{rss / 1024 / 1024:.1f}" if rss is not None else "unknown"
    fd_count = stats.get("fd_count")
    fds = str(fd_count) if fd_count is not None else "unknown"
    return (
        f"memory: rss_mb={rss_mb} fds={fds} "
        f"threads={stats.get('thread_count')} "
        f"gc_gen2_objects={stats.get('gc_objects')}"
    )


def format_tracemalloc_diff(
    snapshot: tracemalloc.Snapshot,
    previous: Optional[tracemalloc.Snapshot],
    top_n: int = TRACEMALLOC_TOP_N,
) -> str:
    """Format the top allocation sites (growth since previous snapshot)."""
    if previous is not None:
        stats = snapshot.compare_to(previous, "lineno")
        lines = [
            f"  {stat.traceback}: +{stat.size_diff / 1024:.0f} KiB "
            f"(total {stat.size / 1024:.0f} KiB, count +{stat.count_diff})"
            for stat in stats[:top_n]
            if stat.size_diff > 0
        ]
        header = "tracemalloc growth since last interval:"
    else:
        stats = snapshot.statistics("lineno")
        lines = [
            f"  {stat.traceback}: {stat.size / 1024:.0f} KiB (count {stat.count})"
            for stat in stats[:top_n]
        ]
        header = "tracemalloc top allocations:"

    if not lines:
        return f"{header} (no growth)"
    return "\n".join([header, *lines])


async def run_memory_monitor(
    interval_seconds: float,
    tracemalloc_enabled: bool = False,
) -> None:
    """Log memory stats forever at the given interval.

    Runs as a background asyncio task for the lifetime of the app and exits
    via task cancellation on shutdown.

    Args:
        interval_seconds: Seconds between samples.
        tracemalloc_enabled: Also log per-file:line allocation growth.
            Adds noticeable overhead; enable only while chasing a leak.
    """
    if tracemalloc_enabled and not tracemalloc.is_tracing():
        tracemalloc.start(TRACEMALLOC_FRAMES)
        logger.info("tracemalloc enabled (%d frames per allocation)", TRACEMALLOC_FRAMES)

    previous_snapshot: Optional[tracemalloc.Snapshot] = None

    while True:
        try:
            logger.info(format_memory_stats(sample_memory_stats()))

            if tracemalloc_enabled:
                snapshot = tracemalloc.take_snapshot()
                logger.info(format_tracemalloc_diff(snapshot, previous_snapshot))
                previous_snapshot = snapshot

        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Memory monitor sampling failed")

        await asyncio.sleep(interval_seconds)


def start_memory_monitor(
    interval_seconds: float,
    tracemalloc_enabled: bool = False,
) -> Optional[asyncio.Task]:
    """Start the memory monitor as a background task.

    Args:
        interval_seconds: Seconds between samples; <= 0 disables monitoring.
        tracemalloc_enabled: Also log allocation-site growth per interval.

    Returns:
        The monitor task, or None when disabled.
    """
    if interval_seconds <= 0:
        logger.info("Memory monitor disabled (MEMORY_LOG_INTERVAL_SECONDS <= 0)")
        return None

    logger.info(
        "Starting memory monitor (interval=%.0fs, tracemalloc=%s)",
        interval_seconds,
        tracemalloc_enabled,
    )
    return asyncio.create_task(
        run_memory_monitor(interval_seconds, tracemalloc_enabled),
        name="memory-monitor",
    )
