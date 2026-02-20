"""Simple circuit breaker for external service calls."""

import logging
import time
from collections import defaultdict
from enum import Enum

logger = logging.getLogger(__name__)


class CircuitState(Enum):
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, reject calls
    HALF_OPEN = "half_open"  # Testing recovery


class CircuitBreaker:
    """Track failure rates per external service."""

    def __init__(
        self,
        failure_threshold: float = 0.5,
        window_seconds: int = 300,
        cooldown_seconds: int = 60,
        min_calls: int = 5,
    ):
        self.failure_threshold = failure_threshold
        self.window_seconds = window_seconds
        self.cooldown_seconds = cooldown_seconds
        self.min_calls = min_calls
        self._calls: dict[str, list[tuple[float, bool]]] = defaultdict(list)
        self._state: dict[str, CircuitState] = defaultdict(lambda: CircuitState.CLOSED)
        self._opened_at: dict[str, float] = {}

    def is_available(self, service: str) -> bool:
        """Check if service is available (circuit not open)."""
        self._clean_old_entries(service)
        state = self._state[service]

        if state == CircuitState.CLOSED:
            return True
        if state == CircuitState.OPEN:
            if time.monotonic() - self._opened_at.get(service, 0) > self.cooldown_seconds:
                self._state[service] = CircuitState.HALF_OPEN
                logger.info("Circuit breaker half-open for %s", service)
                return True
            return False
        # HALF_OPEN - allow one test call
        return True

    def record_success(self, service: str) -> None:
        """Record a successful call to the service."""
        self._calls[service].append((time.monotonic(), True))
        if self._state[service] == CircuitState.HALF_OPEN:
            self._state[service] = CircuitState.CLOSED
            logger.info("Circuit breaker closed for %s (recovered)", service)

    def record_failure(self, service: str) -> None:
        """Record a failed call to the service."""
        self._calls[service].append((time.monotonic(), False))
        self._check_threshold(service)

    def get_state(self, service: str) -> CircuitState:
        """Get the current circuit state for a service."""
        return self._state[service]

    def _clean_old_entries(self, service: str) -> None:
        """Remove entries older than the window."""
        cutoff = time.monotonic() - self.window_seconds
        self._calls[service] = [(t, s) for t, s in self._calls[service] if t > cutoff]

    def _check_threshold(self, service: str) -> None:
        """Check if failure rate exceeds threshold and open circuit."""
        self._clean_old_entries(service)
        calls = self._calls[service]
        if len(calls) < self.min_calls:
            return
        failures = sum(1 for _, success in calls if not success)
        rate = failures / len(calls)
        if rate >= self.failure_threshold:
            self._state[service] = CircuitState.OPEN
            self._opened_at[service] = time.monotonic()
            logger.warning(
                "Circuit breaker OPEN for %s (failure rate: %.1f%%)",
                service,
                rate * 100,
            )


# Global instance
circuit_breaker = CircuitBreaker()
