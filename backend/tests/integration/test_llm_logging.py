"""Integration tests for LLM call logging.

Tests that all LLM calls are logged to the llm_call_log table with
prompts, responses, metrics, and cost tracking.
"""

import pytest
from datetime import date

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
    def logging_service(self, service_client):
        """Create LLM logging service with service role client."""
        return LLMLoggingService(service_client)

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

        # Verify the log was created
        result = (
            logging_service.client.table("llm_call_log")
            .select("*")
            .eq("id", log_id)
            .single()
            .execute()
        )

        log = result.data
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

        # Verify the log was created
        result = (
            logging_service.client.table("llm_call_log")
            .select("*")
            .eq("id", log_id)
            .single()
            .execute()
        )

        log = result.data
        assert log["user_id"] == test_user_id
        assert log["operation_type"] == "compare_events"
        assert log["success"] is False
        assert log["error_message"] == "Rate limit exceeded"
        assert log["error_type"] == "rate_limit"
        assert log["response_text"] is None

    def test_log_call_with_email_id(self, logging_service, test_user_id, service_client):
        """Test logging a call with linked email ID."""
        # Create a test email first
        email_result = (
            service_client.table("emails")
            .insert({
                "user_id": test_user_id,
                "gmail_id": "test-email-for-logging",
                "subject": "Test Email",
                "snippet": "Test snippet",
                "from_email": "test@example.com",
            })
            .execute()
        )
        email_id = email_result.data[0]["id"]

        log_id = logging_service.log_success(
            user_id=test_user_id,
            operation_type=LLMOperationType.EXTRACT_EVENTS,
            model="gemini-3-flash-preview",
            prompt_text="Test prompt",
            response_text="Test response",
            latency_ms=1000,
            email_id=email_id,
        )

        # Verify email_id is linked
        result = (
            logging_service.client.table("llm_call_log")
            .select("email_id")
            .eq("id", log_id)
            .single()
            .execute()
        )

        assert result.data["email_id"] == email_id

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

        assert summary["total_calls"] >= 4
        assert summary["successful_calls"] >= 3
        assert summary["failed_calls"] >= 1
        assert summary["total_tokens"] >= 450  # 3 * 150

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


class TestLLMLoggingRLS:
    """Tests for RLS policies on llm_call_log table."""

    def test_user_can_view_own_logs(self, test_user_client, test_user_id, service_client):
        """Test that users can view their own LLM call logs."""
        # Create a log using service role
        logging_service = LLMLoggingService(service_client)
        log_id = logging_service.log_success(
            user_id=test_user_id,
            operation_type=LLMOperationType.EXTRACT_EVENTS,
            model="gemini-3-flash-preview",
            prompt_text="Test prompt",
            response_text="Test response",
            latency_ms=1000,
        )

        # User should be able to read their own log
        result = (
            test_user_client.table("llm_call_log")
            .select("id, user_id")
            .eq("id", log_id)
            .execute()
        )

        assert len(result.data) == 1
        assert result.data[0]["user_id"] == test_user_id

    def test_user_cannot_view_other_user_logs(self, test_user_client, service_client):
        """Test that users cannot view other users' LLM call logs."""
        # Create another user
        other_user_result = (
            service_client.table("users")
            .insert({"email": "other-llm-test@example.com"})
            .execute()
        )
        other_user_id = other_user_result.data[0]["id"]

        # Create a log for the other user
        logging_service = LLMLoggingService(service_client)
        log_id = logging_service.log_success(
            user_id=other_user_id,
            operation_type=LLMOperationType.EXTRACT_EVENTS,
            model="gemini-3-flash-preview",
            prompt_text="Other user's prompt",
            response_text="Other user's response",
            latency_ms=1000,
        )

        # First user should NOT be able to read the other user's log
        result = (
            test_user_client.table("llm_call_log")
            .select("id")
            .eq("id", log_id)
            .execute()
        )

        assert len(result.data) == 0
