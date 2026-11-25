"""Integration tests for LLM call logging.

Tests that all LLM calls are logged to the llm_call_log table with
prompts, responses, metrics, and cost tracking, on a real SQLite database.
"""

import pytest

pytestmark = [pytest.mark.integration]

from selko.services.llm_logging import (
    LLMLoggingService,
    LLMOperationType,
    LLMErrorType,
    LLMCallRecord,
    LLMCallMetrics,
    estimate_cost,
)


class TestEstimateCost:
    """Tests for cost estimation function."""

    def test_estimate_cost_with_known_model(self):
        """Test cost estimation for known model."""
        # gemini-3-flash-preview: $0.15/1M input, $0.60/1M output
        cost = estimate_cost("gemini-3-flash-preview", 1000, 500)
        expected = (1000 / 1_000_000) * 0.15 + (500 / 1_000_000) * 0.60
        assert cost == pytest.approx(expected, rel=1e-6)

    def test_estimate_cost_with_unknown_model(self):
        """Test cost estimation falls back to default pricing."""
        cost = estimate_cost("unknown-model", 1000, 500)
        expected = (1000 / 1_000_000) * 0.15 + (500 / 1_000_000) * 0.60
        assert cost == pytest.approx(expected, rel=1e-6)

    def test_estimate_cost_returns_none_when_missing_tokens(self):
        """Test returns None when token counts are missing."""
        assert estimate_cost("gemini-3-flash-preview", None, 500) is None
        assert estimate_cost("gemini-3-flash-preview", 1000, None) is None
        assert estimate_cost("gemini-3-flash-preview", None, None) is None


class TestLLMLoggingService:
    """Integration tests for LLM logging service."""

    @pytest.fixture
    def logging_service(self, db):
        return LLMLoggingService(db)

    @pytest.fixture
    def test_user_id(self, factory):
        return factory.user()

    @staticmethod
    def _log(service, log_id):
        row = service.client.query_one("SELECT * FROM llm_call_log WHERE id = ?", (log_id,))
        return service.client.schema.decode("llm_call_log", row)

    def test_log_successful_call(self, logging_service, test_user_id):
        """Test logging a successful LLM call."""
        log_id = logging_service.log_success(
            user_id=test_user_id,
            operation_type=LLMOperationType.EXTRACT_EVENTS,
            model="gemini-3-flash-preview",
            prompt_text="Test prompt for event extraction",
            response_text='{"events_found": true, "events": []}',
            latency_ms=1500,
            prompt_tokens=100,
            completion_tokens=50,
        )

        assert log_id is not None

        log = self._log(logging_service, log_id)
        assert log["user_id"] == test_user_id
        assert log["operation_type"] == "extract_events"
        assert log["model"] == "gemini-3-flash-preview"
        assert log["prompt_text"] == "Test prompt for event extraction"
        assert log["response_text"] == '{"events_found": true, "events": []}'
        assert log["latency_ms"] == 1500
        assert log["prompt_tokens"] == 100
        assert log["completion_tokens"] == 50
        assert log["total_tokens"] == 150
        assert log["success"] is True
        assert log["error_message"] is None
        assert log["estimated_cost_usd"] is not None

    def test_log_failed_call(self, logging_service, test_user_id):
        """Test logging a failed LLM call."""
        log_id = logging_service.log_failure(
            user_id=test_user_id,
            operation_type=LLMOperationType.COMPARE_EVENTS,
            model="gemini-3-flash-preview",
            prompt_text="Test comparison prompt",
            error_message="Rate limit exceeded",
            latency_ms=500,
            error_type=LLMErrorType.RATE_LIMIT,
        )

        assert log_id is not None

        log = self._log(logging_service, log_id)
        assert log["user_id"] == test_user_id
        assert log["operation_type"] == "compare_events"
        assert log["success"] is False
        assert log["error_message"] == "Rate limit exceeded"
        assert log["error_type"] == "rate_limit"
        assert log["response_text"] is None

    def test_log_call_with_email_id(self, logging_service, test_user_id, factory):
        """Test logging a call with linked email ID."""
        email_id = factory.email(test_user_id)

        log_id = logging_service.log_success(
            user_id=test_user_id,
            operation_type=LLMOperationType.EXTRACT_EVENTS,
            model="gemini-3-flash-preview",
            prompt_text="Test prompt",
            response_text="Test response",
            latency_ms=1000,
            email_id=email_id,
        )

        assert self._log(logging_service, log_id)["email_id"] == email_id

    def test_log_all_operation_types(self, logging_service, test_user_id):
        """Test that all operation types can be logged."""
        for op_type in LLMOperationType:
            log_id = logging_service.log_success(
                user_id=test_user_id,
                operation_type=op_type,
                model="gemini-3-flash-preview",
                prompt_text=f"Test prompt for {op_type.value}",
                response_text="Test response",
                latency_ms=100,
            )
            assert log_id is not None

    def test_get_user_usage_summary(self, logging_service, test_user_id):
        """Test getting usage summary for a user."""
        # Create a few test logs
        for i in range(3):
            logging_service.log_success(
                user_id=test_user_id,
                operation_type=LLMOperationType.EXTRACT_EVENTS,
                model="gemini-3-flash-preview",
                prompt_text=f"Test prompt {i}",
                response_text=f"Test response {i}",
                latency_ms=1000 + i * 100,
                prompt_tokens=100,
                completion_tokens=50,
            )

        # Add one failed call
        logging_service.log_failure(
            user_id=test_user_id,
            operation_type=LLMOperationType.COMPARE_EVENTS,
            model="gemini-3-flash-preview",
            prompt_text="Failed test",
            error_message="Test error",
            latency_ms=200,
        )

        # Get summary
        summary = logging_service.get_user_usage_summary(test_user_id)

        assert summary["total_calls"] == 4
        assert summary["successful_calls"] == 3
        assert summary["failed_calls"] == 1
        assert summary["total_tokens"] == 450  # 3 * 150
        assert summary["calls_by_operation"] == {"extract_events": 3, "compare_events": 1}

    def test_logging_handles_errors_gracefully(self, logging_service):
        """Test that logging errors don't crash the application."""
        # Try to log with invalid user_id (non-existent UUID)
        result = logging_service.log_success(
            user_id="00000000-0000-0000-0000-000000000000",
            operation_type=LLMOperationType.EXTRACT_EVENTS,
            model="test",
            prompt_text="test",
            response_text="test",
            latency_ms=100,
        )

        # Should return None (failed) but not raise exception
        assert result is None


class TestLLMCallRecord:
    """Tests for LLMCallRecord dataclass."""

    def test_record_defaults(self):
        """Test that record has sensible defaults."""
        record = LLMCallRecord(
            user_id="test-user",
            operation_type=LLMOperationType.EXTRACT_EVENTS,
            model="test-model",
            prompt_text="test prompt",
        )

        assert record.success is True
        assert record.response_text is None
        assert record.error_message is None
        assert record.started_at is not None

    def test_record_with_metrics(self):
        """Test record with full metrics."""
        metrics = LLMCallMetrics(
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=150,
            latency_ms=1000,
        )

        record = LLMCallRecord(
            user_id="test-user",
            operation_type=LLMOperationType.EXTRACT_EVENTS,
            model="test-model",
            prompt_text="test prompt",
            response_text="test response",
            metrics=metrics,
        )

        assert record.metrics.prompt_tokens == 100
        assert record.metrics.completion_tokens == 50
        assert record.metrics.total_tokens == 150
        assert record.metrics.latency_ms == 1000


class TestLLMLoggingOwnership:
    """Successor of the RLS tests: a user's log rows are read by user_id, and
    no client route exposes the log at all (05-verification.md §A.2 row 41)."""

    def test_user_reads_own_logs_only(self, db, factory):
        from selko.db import ops

        alice, bob = factory.user(), factory.user()
        log_id = LLMLoggingService(db).log_success(
            user_id=alice, operation_type=LLMOperationType.EXTRACT_EVENTS, model="m",
            prompt_text="p", response_text="r", latency_ms=1,
        )
        assert ops.get_llm_call(db, alice, log_id)["id"] == log_id
        assert ops.get_llm_call(db, bob, log_id) is None

    def test_no_client_route_reads_the_llm_log(self):
        from pathlib import Path

        routes = Path(__file__).resolve().parents[2] / "selko" / "api" / "routes"
        files = list(routes.glob("*.py"))
        assert len(files) > 3
        assert [f.name for f in files if "llm_call_log" in f.read_text() or "get_llm_call" in f.read_text()] == []
