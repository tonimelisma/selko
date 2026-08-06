"""Process-local outbound traffic meter.

The platform bandwidth alert says *how much* egress a service spent; it cannot
say *what spent it*. This module closes that gap by attributing every outbound
byte to a destination and a bounded operation name, which separates the two
things that look identical on a bandwidth graph:

* **coordination chatter** — database polling that runs whether or not there is
  any work, and
* **payload** — mail bodies and attachments actually downloaded from a provider.

That distinction is the whole point. A flat, round-the-clock egress line with
no inbound requests is a polling loop, not user traffic, and the fix for each is
completely different.

Safety: operation names are templates only. URLs are reduced to method + path
with the query string discarded, because Gmail and Graph both put message and
attachment identifiers in query parameters. Nothing here records payloads,
addresses, tokens, or identifiers.

Counters are process-local and reset on restart. They are a diagnostic for "what
is this instance doing right now", not a billing ledger — the platform remains
the source of truth for the monthly total.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urlsplit

logger = logging.getLogger(__name__)

# Destinations. Kept coarse on purpose: the question is which *system* the bytes
# went to, not which host answered.
SUPABASE = "supabase"
GMAIL = "gmail"
GRAPH = "graph"
LLM = "llm"

# A runaway caller must not be able to grow this dict without bound. Operation
# names are already templates, so this ceiling is only a backstop against a
# future call site that forgets and passes something high-cardinality.
MAX_TRACKED_OPERATIONS = 200
_OVERFLOW_OPERATION = "other"


@dataclass
class EgressCounter:
    """Call and byte totals for one (destination, operation) pair."""

    calls: int = 0
    request_bytes: int = 0
    response_bytes: int = 0

    @property
    def total_bytes(self) -> int:
        return self.request_bytes + self.response_bytes


@dataclass
class EgressMeter:
    """Thread-safe counters for outbound traffic.

    The worker pool runs several threads against one shared service client, so
    every mutation takes the lock. The critical section is a couple of integer
    adds — far cheaper than the network call being measured.
    """

    _lock: threading.Lock = field(default_factory=threading.Lock)
    _counters: dict[tuple[str, str], EgressCounter] = field(default_factory=dict)
    _started_at: float = field(default_factory=time.monotonic)

    def record(
        self,
        destination: str,
        operation: str,
        *,
        request_bytes: int = 0,
        response_bytes: int = 0,
    ) -> None:
        with self._lock:
            key = (destination, operation)
            if key not in self._counters and len(self._counters) >= MAX_TRACKED_OPERATIONS:
                key = (destination, _OVERFLOW_OPERATION)
            counter = self._counters.get(key)
            if counter is None:
                counter = EgressCounter()
                self._counters[key] = counter
            counter.calls += 1
            counter.request_bytes += max(request_bytes, 0)
            counter.response_bytes += max(response_bytes, 0)

    def snapshot(self, *, top_n: int = 15) -> dict:
        """Totals plus the heaviest operations by bytes.

        Includes a projected monthly figure. It is a naive extrapolation of the
        rate since process start, which is exactly the right shape for catching
        a constant background leak (the case this module exists for) and the
        wrong shape for bursty traffic — so it is labelled as a projection, not
        a measurement.
        """
        with self._lock:
            counters = {key: EgressCounter(c.calls, c.request_bytes, c.response_bytes)
                        for key, c in self._counters.items()}
            uptime = max(time.monotonic() - self._started_at, 1e-6)

        total_bytes = sum(c.total_bytes for c in counters.values())
        total_calls = sum(c.calls for c in counters.values())

        by_destination: dict[str, dict] = {}
        for (destination, _operation), counter in counters.items():
            entry = by_destination.setdefault(
                destination, {"calls": 0, "bytes": 0}
            )
            entry["calls"] += counter.calls
            entry["bytes"] += counter.total_bytes

        ranked = sorted(
            (
                {
                    "destination": destination,
                    "operation": operation,
                    "calls": counter.calls,
                    "bytes": counter.total_bytes,
                    "calls_per_minute": round(counter.calls / uptime * 60, 2),
                }
                for (destination, operation), counter in counters.items()
            ),
            key=lambda row: row["bytes"],
            reverse=True,
        )

        bytes_per_hour = total_bytes / uptime * 3600
        return {
            "uptime_seconds": round(uptime, 1),
            "total_calls": total_calls,
            "total_bytes": total_bytes,
            "calls_per_second": round(total_calls / uptime, 2),
            "bytes_per_hour": round(bytes_per_hour),
            "projected_bytes_per_30d": round(bytes_per_hour * 24 * 30),
            "by_destination": by_destination,
            "top_operations": ranked[:top_n],
        }

    def reset(self) -> None:
        with self._lock:
            self._counters.clear()
            self._started_at = time.monotonic()


_METER = EgressMeter()


def record_egress(
    destination: str,
    operation: str,
    *,
    request_bytes: int = 0,
    response_bytes: int = 0,
) -> None:
    """Attribute one outbound call to a destination and operation template."""
    _METER.record(
        destination,
        operation,
        request_bytes=request_bytes,
        response_bytes=response_bytes,
    )


def egress_snapshot(*, top_n: int = 15) -> dict:
    return _METER.snapshot(top_n=top_n)


def reset_egress() -> None:
    """Reset counters. Used by tests; not wired to any request surface."""
    _METER.reset()


def operation_from_url(method: str, url: str) -> str:
    """Reduce a URL to a bounded, non-identifying operation name.

    The query string is dropped deliberately: Gmail and Graph both carry message
    and attachment ids there, and PostgREST carries row filters. Path segments
    that look like ids are collapsed so one operation does not fan out into
    thousands of counter keys.
    """
    path = urlsplit(url).path or "/"
    segments = []
    for segment in path.split("/"):
        if not segment:
            continue
        segments.append("{id}" if _looks_like_identifier(segment) else segment)
    return f"{method.upper()} /{'/'.join(segments)}"


def _looks_like_identifier(segment: str) -> bool:
    """True for segments that are values rather than route names.

    Deliberately conservative — a false negative only costs one extra counter
    key, while a false positive would hide a real route behind ``{id}``.
    """
    if len(segment) >= 32 and "-" in segment:
        return True  # uuid-ish
    if len(segment) >= 16 and segment.isalnum() and any(ch.isdigit() for ch in segment):
        return True  # provider message ids
    return segment.isdigit()


def log_egress_summary(*, top_n: int = 5) -> None:
    """Emit one structured summary line.

    Called on an interval so a bandwidth question can be answered from the
    service's own logs, without attaching a profiler to a live instance.
    """
    snapshot = egress_snapshot(top_n=top_n)
    logger.info(
        "egress summary calls=%d bytes=%d rate_bytes_per_hour=%d projected_30d_bytes=%d top=%s",
        snapshot["total_calls"],
        snapshot["total_bytes"],
        snapshot["bytes_per_hour"],
        snapshot["projected_bytes_per_30d"],
        [
            f"{row['destination']}:{row['operation']}={row['bytes']}B/{row['calls']}c"
            for row in snapshot["top_operations"]
        ],
    )
