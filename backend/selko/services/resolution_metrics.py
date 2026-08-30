"""Process-local observability for fenced event resolution."""

from __future__ import annotations

from collections import Counter, deque
from datetime import datetime, timezone
from threading import Lock


class ResolutionMetrics:
    """Content-free counters for the extraction resolution fence."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._started_at = datetime.now(timezone.utc)

        self._conflict_times: deque[datetime] = deque()
        self._retries_per_email: Counter[int] = Counter()
        self._fenced_writes = 0
        self._conflict_exhaustions = 0

    @property
    def started_at(self) -> datetime:
        """When this process began recording, as an absolute instant.

        Exposed on /health so a probe can tell *which* process answered.
        A duration cannot do that: production once returned two uptimes 3.19
        days apart within fifteen minutes while Render reported one instance,
        and there was no way to distinguish a second process from a broken
        counter.
        """
        return self._started_at

    def record_conflict(self) -> None:
        with self._lock:
            self._conflict_times.append(datetime.now(timezone.utc))

    def record_retries_per_email(self, retry_count: int) -> None:
        with self._lock:
            self._retries_per_email[max(retry_count, 1)] += 1

    def record_fenced_write(self) -> None:
        with self._lock:
            self._fenced_writes += 1

    def record_conflict_exhaustion(self) -> None:
        with self._lock:
            self._conflict_exhaustions += 1

    def snapshot(self) -> dict[str, object]:
        cutoff = datetime.now(timezone.utc).timestamp() - 3600
        with self._lock:
            while self._conflict_times and self._conflict_times[0].timestamp() < cutoff:
                self._conflict_times.popleft()
            return {
                "conflicts_per_hour": len(self._conflict_times),
                "retries_per_email_histogram": {
                    str(retries): count
                    for retries, count in sorted(self._retries_per_email.items())
                },
                "fenced_writes_since_start": self._fenced_writes,
                "conflict_exhaustion_count": self._conflict_exhaustions,
                "uptime_seconds": max(
                    0, int((datetime.now(timezone.utc) - self._started_at).total_seconds())
                ),
            }


resolution_metrics = ResolutionMetrics()
