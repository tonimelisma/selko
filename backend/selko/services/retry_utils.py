"""Shared retry utilities for exponential backoff calculations."""

from datetime import datetime, timedelta, timezone


def calculate_retry_delay(
    attempt: int,
    base_delay: int = 60,
    max_delay: int = 3600,
) -> tuple[int, str]:
    """Calculate exponential backoff delay and next retry timestamp.

    Args:
        attempt: Current attempt number (1-based).
        base_delay: Base delay in seconds (default 60).
        max_delay: Maximum delay in seconds (default 3600 = 1 hour).

    Returns:
        Tuple of (delay_seconds, next_retry_at_iso_string).
    """
    delay = min(base_delay * (2 ** (attempt - 1)), max_delay)
    next_retry_at = datetime.now(timezone.utc) + timedelta(seconds=delay)
    return delay, next_retry_at.isoformat()
