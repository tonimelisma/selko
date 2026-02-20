"""Tests for LLM Gateway."""

import time
from unittest.mock import MagicMock, patch

import pytest

from selko.config import Config
from selko.services.llm_gateway import (
    LLMAPIError,
    LLMGateway,
    LLMGatewayError,
    LLMRateLimitError,
)
from selko.services.llm_logging import LLMLoggingService, LLMOperationType
from selko.services.llm_provider import ImageContent, LLMProvider, LLMResponse
from selko.services.quotas import QuotaCheckResult, QuotaExceededError, QuotaService


@pytest.fixture
def mock_provider():
    """Create a mock LLMProvider."""
    provider = MagicMock(spec=LLMProvider)
    provider.provider_name = "gemini"
    provider.model = "gemini-3-flash-preview"
    provider.supports_vision = True
    provider.supports_json_schema = True
    return provider


@pytest.fixture
def mock_logging_service():
    """Create a mock LLM logging service."""
    return MagicMock(spec=LLMLoggingService)


@pytest.fixture
def mock_quota_service():
    """Create a mock quota service."""
    return MagicMock(spec=QuotaService)


class TestLLMGateway:
    """Tests for LLMGateway class."""

    def test_initialization(self, mock_provider):
        """Test gateway initialization."""
        gateway = LLMGateway(mock_provider)

        assert gateway.provider == mock_provider
        assert gateway.model == "gemini-3-flash-preview"
        assert gateway.logging_service is None
        assert gateway.quota_service is None

    def test_for_user_chaining(self, mock_provider):
        """Test for_user returns self for chaining."""
        gateway = LLMGateway(mock_provider)

        result = gateway.for_user("user-123")

        assert result is gateway
        assert gateway.user_id == "user-123"

    def test_for_email_chaining(self, mock_provider):
        """Test for_email returns self for chaining."""
        gateway = LLMGateway(mock_provider)

        result = gateway.for_email("email-456")

        assert result is gateway
        assert gateway.email_id == "email-456"

    def test_method_chaining(self, mock_provider):
        """Test method chaining works as expected."""
        gateway = LLMGateway(mock_provider)

        gateway.for_user("user-123").for_email("email-456")

        assert gateway.user_id == "user-123"
        assert gateway.email_id == "email-456"


class TestLLMGatewayCall:
    """Tests for LLMGateway.call method."""

    def test_successful_call(self, mock_provider):
        """Test successful LLM call."""
        mock_response = LLMResponse(text="test response", prompt_tokens=10, completion_tokens=5)
        mock_provider.generate.return_value = mock_response

        gateway = LLMGateway(mock_provider)
        response = gateway.call(
            operation=LLMOperationType.EXTRACT_EVENTS,
            contents=["test prompt"],
        )

        assert response == mock_response
        mock_provider.generate.assert_called_once()

    def test_call_with_quota_check(self, mock_provider, mock_quota_service):
        """Test that quota is checked before making call."""
        mock_response = LLMResponse(text="ok", prompt_tokens=10, completion_tokens=5)
        mock_provider.generate.return_value = mock_response

        # Configure quota service to allow the call
        mock_quota_service.check_and_increment.return_value = QuotaCheckResult(
            allowed=True, current_count=1, limit=100, remaining=99
        )

        gateway = LLMGateway(mock_provider, quota_service=mock_quota_service)
        gateway.for_user("user-123")

        gateway.call(
            operation=LLMOperationType.EXTRACT_EVENTS,
            contents=["test prompt"],
        )

        mock_quota_service.check_and_increment.assert_called_once_with(
            "user-123", "llm_calls"
        )

    def test_call_quota_exceeded(self, mock_provider, mock_quota_service):
        """Test QuotaExceededError when quota is exceeded."""
        # Configure quota service to deny the call
        mock_quota_service.check_and_increment.return_value = QuotaCheckResult(
            allowed=False, current_count=100, limit=100, remaining=0
        )

        gateway = LLMGateway(mock_provider, quota_service=mock_quota_service)
        gateway.for_user("user-123")

        with pytest.raises(QuotaExceededError) as exc_info:
            gateway.call(
                operation=LLMOperationType.EXTRACT_EVENTS,
                contents=["test prompt"],
            )

        assert exc_info.value.quota_type == "llm_calls"
        assert exc_info.value.current_count == 100
        assert exc_info.value.limit == 100

    def test_call_logs_success(self, mock_provider, mock_logging_service):
        """Test that successful calls are logged."""
        mock_response = LLMResponse(text="test response", prompt_tokens=100, completion_tokens=50)
        mock_provider.generate.return_value = mock_response

        gateway = LLMGateway(mock_provider, logging_service=mock_logging_service)
        gateway.for_user("user-123").for_email("email-456")

        gateway.call(
            operation=LLMOperationType.EXTRACT_EVENTS,
            contents=["test prompt"],
        )

        mock_logging_service.log_success.assert_called_once()
        call_args = mock_logging_service.log_success.call_args
        assert call_args.kwargs["user_id"] == "user-123"
        assert call_args.kwargs["operation_type"] == LLMOperationType.EXTRACT_EVENTS
        assert call_args.kwargs["email_id"] == "email-456"
        assert call_args.kwargs["prompt_tokens"] == 100
        assert call_args.kwargs["completion_tokens"] == 50
        assert call_args.kwargs["provider"] == "gemini"

    def test_call_logs_failure(self, mock_provider, mock_logging_service):
        """Test that failed calls are logged."""
        mock_provider.generate.side_effect = Exception("API Error")

        gateway = LLMGateway(mock_provider, logging_service=mock_logging_service)
        gateway.for_user("user-123")

        with pytest.raises(LLMAPIError):
            gateway.call(
                operation=LLMOperationType.EXTRACT_EVENTS,
                contents=["test prompt"],
            )

        mock_logging_service.log_failure.assert_called_once()
        call_args = mock_logging_service.log_failure.call_args
        assert call_args.kwargs["provider"] == "gemini"

    def test_rate_limit_retry(self, mock_provider):
        """Test retry logic on rate limit errors."""
        mock_response = LLMResponse(text="success", prompt_tokens=10, completion_tokens=5)

        # First call raises rate limit, second succeeds
        mock_provider.generate.side_effect = [
            Exception("429 Rate limit exceeded"),
            mock_response,
        ]

        gateway = LLMGateway(mock_provider)

        with patch("selko.services.llm_gateway.time.sleep"):
            response = gateway.call(
                operation=LLMOperationType.EXTRACT_EVENTS,
                contents=["test prompt"],
                max_retries=3,
            )

        assert response == mock_response
        assert mock_provider.generate.call_count == 2

    def test_rate_limit_exhausted(self, mock_provider):
        """Test failure after exhausting retries."""
        mock_provider.generate.side_effect = Exception("429 Rate limit exceeded")

        gateway = LLMGateway(mock_provider)

        with patch("selko.services.llm_gateway.time.sleep"):
            with pytest.raises(LLMRateLimitError) as exc_info:
                gateway.call(
                    operation=LLMOperationType.EXTRACT_EVENTS,
                    contents=["test prompt"],
                    max_retries=2,
                )

        assert "rate limited" in str(exc_info.value).lower()
        assert mock_provider.generate.call_count == 2

    def test_non_rate_limit_error_no_retry(self, mock_provider):
        """Test immediate failure on non-rate-limit errors."""
        mock_provider.generate.side_effect = Exception("Invalid API key")

        gateway = LLMGateway(mock_provider)

        with pytest.raises(LLMAPIError) as exc_info:
            gateway.call(
                operation=LLMOperationType.EXTRACT_EVENTS,
                contents=["test prompt"],
                max_retries=3,
            )

        # Should fail immediately without retries
        assert mock_provider.generate.call_count == 1
        assert "Invalid API key" in str(exc_info.value)


class TestLLMGatewayPromptLogging:
    """Tests for prompt logging functionality."""

    def test_build_prompt_list_content(self, mock_provider):
        """Test that list content is logged correctly."""
        gateway = LLMGateway(mock_provider)

        content = ["part1", "part2", "part3"]
        result = gateway._build_prompt_for_logging(content)

        assert result == "part1part2part3"

    def test_build_prompt_with_attachments(self, mock_provider):
        """Test that attachments are noted in logging."""
        gateway = LLMGateway(mock_provider)

        content = [
            "prompt text",
            ImageContent(data=b"fake image", mime_type="image/jpeg"),
        ]
        result = gateway._build_prompt_for_logging(content)

        assert "prompt text" in result
        assert "[1 attachment(s) included]" in result


class TestErrorClassification:
    """Tests for error classification."""

    def test_classify_rate_limit_429(self, mock_provider):
        """Test retryable error classification for 429 errors."""
        gateway = LLMGateway(mock_provider)

        assert gateway._is_retryable_error("429 too many requests")

    def test_classify_rate_limit_quota(self, mock_provider):
        """Test retryable error classification for quota errors."""
        gateway = LLMGateway(mock_provider)

        assert gateway._is_retryable_error("quota exceeded")

    def test_classify_not_rate_limit(self, mock_provider):
        """Test non-retryable error classification."""
        gateway = LLMGateway(mock_provider)

        assert not gateway._is_retryable_error("invalid api key")

    def test_classify_503_unavailable(self, mock_provider):
        """Test retryable error classification for 503 errors."""
        gateway = LLMGateway(mock_provider)

        assert gateway._is_retryable_error("503 unavailable")
        assert gateway._is_retryable_error("this model is currently experiencing high demand")
        assert gateway._is_retryable_error("service overloaded")
