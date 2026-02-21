"""Tests for retry_utils module."""

from selko.services.retry_utils import calculate_retry_delay


class TestCalculateRetryDelay:
    """Tests for calculate_retry_delay."""

    def test_first_attempt_default(self):
        delay, next_retry_at = calculate_retry_delay(1)
        assert delay == 60

    def test_second_attempt_default(self):
        delay, _ = calculate_retry_delay(2)
        assert delay == 120

    def test_third_attempt_default(self):
        delay, _ = calculate_retry_delay(3)
        assert delay == 240

    def test_max_delay_cap(self):
        delay, _ = calculate_retry_delay(20)
        assert delay == 3600

    def test_custom_base_delay(self):
        delay, _ = calculate_retry_delay(1, base_delay=30)
        assert delay == 30

    def test_custom_max_delay(self):
        delay, _ = calculate_retry_delay(10, base_delay=60, max_delay=500)
        assert delay == 500

    def test_returns_iso_string(self):
        _, next_retry_at = calculate_retry_delay(1)
        assert isinstance(next_retry_at, str)
        assert "T" in next_retry_at  # ISO format includes T separator

    def test_next_retry_at_is_in_future(self):
        from datetime import datetime, timezone
        _, next_retry_at = calculate_retry_delay(1)
        parsed = datetime.fromisoformat(next_retry_at)
        assert parsed > datetime.now(timezone.utc)
