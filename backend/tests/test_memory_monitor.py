"""Tests for the memory monitor instrumentation."""

import asyncio
import logging
import tracemalloc
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from selko.services.memory_monitor import (
    format_memory_stats,
    format_tracemalloc_diff,
    get_fd_count,
    get_rss_bytes,
    run_memory_monitor,
    sample_memory_stats,
    start_memory_monitor,
)


class TestSampling:
    """Test memory stat collection."""

    def test_rss_is_positive(self):
        """RSS reads as a plausible positive byte count."""
        rss = get_rss_bytes()
        assert rss is not None
        assert rss > 1024 * 1024  # any Python process exceeds 1 MB

    def test_fd_count_is_positive(self):
        """Open file descriptor count is available and positive."""
        fds = get_fd_count()
        assert fds is not None
        assert fds > 0

    def test_sample_contains_all_counters(self):
        """Snapshot includes every counter the log line reports."""
        stats = sample_memory_stats()
        assert stats["rss_bytes"] > 0
        assert stats["fd_count"] > 0
        assert stats["thread_count"] >= 1
        assert stats["gc_objects"] > 0


class TestFormatting:
    """Test log line formatting."""

    def test_format_full_stats(self):
        """All counters appear in the formatted line."""
        line = format_memory_stats(
            {
                "rss_bytes": 256 * 1024 * 1024,
                "fd_count": 42,
                "thread_count": 5,
                "gc_objects": 12345,
            }
        )
        assert line == (
            "memory: rss_mb=256.0 fds=42 threads=5 gc_gen2_objects=12345"
        )

    def test_format_handles_unavailable_counters(self):
        """None values render as 'unknown' instead of crashing."""
        line = format_memory_stats(
            {
                "rss_bytes": None,
                "fd_count": None,
                "thread_count": 5,
                "gc_objects": 12345,
            }
        )
        assert "rss_mb=unknown" in line
        assert "fds=unknown" in line


class TestTracemallocDiff:
    """Test tracemalloc snapshot diff formatting."""

    def test_first_snapshot_lists_top_allocations(self):
        """Without a previous snapshot, lists absolute top allocations."""
        tracemalloc.start(1)
        try:
            retained = [bytearray(4096) for _ in range(100)]
            snapshot = tracemalloc.take_snapshot()
            output = format_tracemalloc_diff(snapshot, None)
            assert output.startswith("tracemalloc top allocations:")
            assert "KiB" in output
            assert retained  # keep allocations alive through the snapshot
        finally:
            tracemalloc.stop()

    def test_diff_reports_growth_between_snapshots(self):
        """Growth between snapshots is attributed to this file."""
        tracemalloc.start(1)
        try:
            first = tracemalloc.take_snapshot()
            retained = [bytearray(4096) for _ in range(500)]
            second = tracemalloc.take_snapshot()
            output = format_tracemalloc_diff(second, first)
            assert output.startswith("tracemalloc growth since last interval:")
            assert "test_memory_monitor.py" in output
            assert retained
        finally:
            tracemalloc.stop()

    def test_growth_site_beyond_top_n_by_absolute_diff_is_not_masked(self):
        """Regression: compare_to() sorts by absolute size_diff, so large
        frees can fill the top N and crowd out real growth sites further
        down the (unfiltered) list. Filtering must happen before slicing."""
        # 10 large frees (negative diffs) exactly fill top_n=10 by absolute
        # value; the one real growth site sits just past that cutoff.
        frees = [
            SimpleNamespace(
                traceback=f"free_site_{i}", size_diff=-100_000, size=0, count_diff=-1
            )
            for i in range(10)
        ]
        growth = SimpleNamespace(
            traceback="growing_site", size_diff=4096, size=8192, count_diff=2
        )
        snapshot = MagicMock()
        snapshot.compare_to.return_value = frees + [growth]

        output = format_tracemalloc_diff(snapshot, MagicMock(), top_n=10)

        assert "growing_site" in output
        assert "no growth" not in output


class TestMonitorTask:
    """Test the background monitor loop."""

    @pytest.mark.asyncio
    async def test_start_disabled_returns_none(self):
        """Interval <= 0 disables the monitor."""
        assert start_memory_monitor(0) is None
        assert start_memory_monitor(-1) is None

    @pytest.mark.asyncio
    async def test_monitor_logs_and_cancels(self, caplog):
        """Monitor emits a stats line and shuts down via cancellation."""
        with caplog.at_level(logging.INFO, logger="selko.services.memory_monitor"):
            task = start_memory_monitor(interval_seconds=3600)
            assert task is not None
            await asyncio.sleep(0.05)  # let the first sample run
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task

        assert any("memory: rss_mb=" in r.message for r in caplog.records)
