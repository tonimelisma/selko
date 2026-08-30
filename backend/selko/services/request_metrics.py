"""Process-local counters for what the API actually returns to callers.

Every health invariant this service had measured internal state: dead letters,
stale rows, worker liveness, listener connectivity, transport. None of them
looked at responses. So when /events/{id}/apply-change began raising KeyError on
every call, production answered 500 to every accept for eight days while
/health, /health/ingestion and the whole assert-health.sh invariant set stayed
green. The workers were fine. The queues were fine. Nobody was measuring whether
requests were failing.

Content-free by construction: status classes and a bounded set of route
templates, never paths with identifiers, bodies, or user data.
"""

from __future__ import annotations

from collections import Counter, deque
from datetime import datetime, timedelta, timezone
from threading import Lock

_WINDOW = timedelta(hours=1)


class RequestMetrics:
    """A rolling one-hour view of response outcomes."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._server_errors: deque[datetime] = deque()
        self._requests: deque[datetime] = deque()
        self._error_routes: Counter[str] = Counter()

    def record(self, *, status_code: int, route: str) -> None:
        now = datetime.now(timezone.utc)
        with self._lock:
            self._requests.append(now)
            if status_code >= 500:
                self._server_errors.append(now)
                # The route *template* ("/events/{event_id}/apply-change"), not
                # the request path, so no identifier is ever recorded.
                self._error_routes[route] += 1
            self._trim(now)

    def _trim(self, now: datetime) -> None:
        cutoff = now - _WINDOW
        while self._server_errors and self._server_errors[0] < cutoff:
            self._server_errors.popleft()
        while self._requests and self._requests[0] < cutoff:
            self._requests.popleft()

    def snapshot(self) -> dict[str, object]:
        now = datetime.now(timezone.utc)
        with self._lock:
            self._trim(now)
            return {
                "requests_per_hour": len(self._requests),
                "server_errors_per_hour": len(self._server_errors),
                # Bounded: only routes that actually failed, most frequent first.
                "server_error_routes": dict(self._error_routes.most_common(10)),
            }


request_metrics = RequestMetrics()
