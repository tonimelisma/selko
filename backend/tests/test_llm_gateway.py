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
    get_gemini_client,
)
from selko.services.llm_logging import LLMLoggingService, LLMOperationType
from selko.services.quotas import QuotaCheckResult, QuotaExceededError, QuotaService


@pytest.fixture
def mock_config():
    """Create a mock Config with Gemini API key."""
    return Config(
        environment="development",
        supabase_url="http://localhost:54321",
        supabase_key="test-key",
        gemini_api_key="test-gemini-key",
        gemini_model="gemini-3-flash-preview",
    )


@pytest.fixture
def mock_logging_service():
    """Create a mock LLM logging service."""
    return MagicMock(spec=LLMLoggingService)


@pytest.fixture
def mock_quota_service():
    """Create a mock quota service."""
    return MagicMock(spec=QuotaService)


class TestGetGeminiClient:
    """Tests for get_gemini_client function."""

    def test_success(self, mock_config):
        """Test successful client initialization."""
        with patch("selko.services.llm_gateway.genai.Client") as mock_client_class:
            mock_client = MagicMock()
            mock_client_class.return_value = mock_client

            client = get_gemini_client(mock_config)

            assert client == mock_client
            mock_client_class.assert_called_once_with(api_key="test-gemini-key")

    def test_missing_api_key(self):
        """Test error when API key is missing."""
        config = Config(
            environment="development",
            supabase_url="http://localhost:54321",
            supabase_key="test-key",
            gemini_api_key=None,
        )

        with pytest.raises(LLMGatewayError) as exc_info:
            get_gemini_client(config)

        assert "GEMINI_API_KEY not configured" in str(exc_info.value)

    def test_client_initialization_failure(self, mock_config):
        """Test error handling when client initialization fails."""
        with patch("selko.services.llm_gateway.genai.Client") as mock_client_class:
            mock_client_class.side_effect = Exception("API connection failed")

            with pytest.raises(LLMGatewayError) as exc_info:
                get_gemini_client(mock_config)

            assert "Failed to initialize Gemini client" in str(exc_info.value)


class TestLLMGateway:
    """Tests for LLMGateway class."""

    def test_initialization(self, mock_config):
        """Test gateway initialization."""
        with patch("selko.services.llm_gateway.get_gemini_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            gateway = LLMGateway(mock_config)

            assert gateway.client == mock_client
            assert gateway.model == "gemini-3-flash-preview"
            assert gateway.logging_service is None
            assert gateway.quota_service is None

    def test_for_user_chaining(self, mock_config):
        """Test for_user returns self for chaining."""
        with patch("selko.services.llm_gateway.get_gemini_client"):
            gateway = LLMGateway(mock_config)

            result = gateway.for_user("user-123")

            assert result is gateway
            assert gateway.user_id == "user-123"

    def test_for_email_chaining(self, mock_config):
        """Test for_email returns self for chaining."""
        with patch("selko.services.llm_gateway.get_gemini_client"):
            gateway = LLMGateway(mock_config)

            result = gateway.for_email("email-456")

            assert result is gateway
            assert gateway.email_id == "email-456"

    def test_method_chaining(self, mock_config):
        """Test method chaining works as expected."""
        with patch("selko.services.llm_gateway.get_gemini_client"):
            gateway = LLMGateway(mock_config)

            gateway.for_user("user-123").for_email("email-456")

            assert gateway.user_id == "user-123"
            assert gateway.email_id == "email-456"


class TestLLMGatewayCall:
    """Tests for LLMGateway.call method."""

    def test_successful_call(self, mock_config):
        """Test successful LLM call."""
        with patch("selko.services.llm_gateway.get_gemini_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            mock_response = MagicMock()
            mock_response.text = "test response"
            mock_client.models.generate_content.return_value = mock_response

            gateway = LLMGateway(mock_config)
            response = gateway.call(
                operation=LLMOperationType.EXTRACT_EVENTS,
                contents="test prompt",
            )

            assert response == mock_response
            mock_client.models.generate_content.assert_called_once()

    def test_call_with_quota_check(self, mock_config, mock_quota_service):
        """Test that quota is checked before making call."""
        with patch("selko.services.llm_gateway.get_gemini_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            mock_response = MagicMock()
            mock_client.models.generate_content.return_value = mock_response

            # Configure quota service to allow the call
            mock_quota_service.check_and_increment.return_value = QuotaCheckResult(
                allowed=True, current_count=1, limit=100, remaining=99
            )

            gateway = LLMGateway(mock_config, quota_service=mock_quota_service)
            gateway.for_user("user-123")

            gateway.call(
                operation=LLMOperationType.EXTRACT_EVENTS,
                contents="test prompt",
            )

            mock_quota_service.check_and_increment.assert_called_once_with(
                "user-123", "llm_calls"
            )

    def test_call_quota_exceeded(self, mock_config, mock_quota_service):
        """Test QuotaExceededError when quota is exceeded."""
        with patch("selko.services.llm_gateway.get_gemini_client"):
            # Configure quota service to deny the call
            mock_quota_service.check_and_increment.return_value = QuotaCheckResult(
                allowed=False, current_count=100, limit=100, remaining=0
            )

            gateway = LLMGateway(mock_config, quota_service=mock_quota_service)
            gateway.for_user("user-123")

            with pytest.raises(QuotaExceededError) as exc_info:
                gateway.call(
                    operation=LLMOperationType.EXTRACT_EVENTS,
                    contents="test prompt",
                )

            assert exc_info.value.quota_type == "llm_calls"
            assert exc_info.value.current_count == 100
            assert exc_info.value.limit == 100

    def test_call_logs_success(self, mock_config, mock_logging_service):
        """Test that successful calls are logged."""
        with patch("selko.services.llm_gateway.get_gemini_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            mock_response = MagicMock()
            mock_response.text = "test response"
            mock_response.usage_metadata = MagicMock()
            mock_response.usage_metadata.prompt_token_count = 100
            mock_response.usage_metadata.candidates_token_count = 50
            mock_client.models.generate_content.return_value = mock_response

            gateway = LLMGateway(mock_config, logging_service=mock_logging_service)
            gateway.for_user("user-123").for_email("email-456")

            gateway.call(
                operation=LLMOperationType.EXTRACT_EVENTS,
                contents="test prompt",
            )

            mock_logging_service.log_success.assert_called_once()
            call_args = mock_logging_service.log_success.call_args
            assert call_args.kwargs["user_id"] == "user-123"
            assert call_args.kwargs["operation_type"] == LLMOperationType.EXTRACT_EVENTS
            assert call_args.kwargs["email_id"] == "email-456"
            assert call_args.kwargs["prompt_tokens"] == 100
            assert call_args.kwargs["completion_tokens"] == 50

    def test_call_logs_failure(self, mock_config, mock_logging_service):
        """Test that failed calls are logged."""
        with patch("selko.services.llm_gateway.get_gemini_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.models.generate_content.side_effect = Exception("API Error")

            gateway = LLMGateway(mock_config, logging_service=mock_logging_service)
            gateway.for_user("user-123")

            with pytest.raises(LLMAPIError):
                gateway.call(
                    operation=LLMOperationType.EXTRACT_EVENTS,
                    contents="test prompt",
                )

            mock_logging_service.log_failure.assert_called_once()

    def test_rate_limit_retry(self, mock_config):
        """Test retry logic on rate limit errors."""
        with patch("selko.services.llm_gateway.get_gemini_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client

            # First call raises rate limit, second succeeds
            mock_response = MagicMock()
            mock_response.text = "success"
            mock_client.models.generate_content.side_effect = [
                Exception("429 Rate limit exceeded"),
                mock_response,
            ]

            gateway = LLMGateway(mock_config)

            with patch("selko.services.llm_gateway.time.sleep"):
                response = gateway.call(
                    operation=LLMOperationType.EXTRACT_EVENTS,
                    contents="test prompt",
                    max_retries=3,
                )

            assert response == mock_response
            assert mock_client.models.generate_content.call_count == 2

    def test_rate_limit_exhausted(self, mock_config):
        """Test failure after exhausting retries."""
        with patch("selko.services.llm_gateway.get_gemini_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.models.generate_content.side_effect = Exception(
                "429 Rate limit exceeded"
            )

            gateway = LLMGateway(mock_config)

            with patch("selko.services.llm_gateway.time.sleep"):
                with pytest.raises(LLMRateLimitError) as exc_info:
                    gateway.call(
                        operation=LLMOperationType.EXTRACT_EVENTS,
                        contents="test prompt",
                        max_retries=2,
                    )

            assert "rate limited" in str(exc_info.value).lower()
            assert mock_client.models.generate_content.call_count == 2

    def test_non_rate_limit_error_no_retry(self, mock_config):
        """Test immediate failure on non-rate-limit errors."""
        with patch("selko.services.llm_gateway.get_gemini_client") as mock_get_client:
            mock_client = MagicMock()
            mock_get_client.return_value = mock_client
            mock_client.models.generate_content.side_effect = Exception("Invalid API key")

            gateway = LLMGateway(mock_config)

            with pytest.raises(LLMAPIError) as exc_info:
                gateway.call(
                    operation=LLMOperationType.EXTRACT_EVENTS,
                    contents="test prompt",
                    max_retries=3,
                )

            # Should fail immediately without retries
            assert mock_client.models.generate_content.call_count == 1
            assert "Invalid API key" in str(exc_info.value)


class TestLLMGatewayPromptLogging:
    """Tests for prompt logging functionality."""

    def test_build_prompt_string_content(self, mock_config):
        """Test that string content is logged correctly."""
        with patch("selko.services.llm_gateway.get_gemini_client"):
            gateway = LLMGateway(mock_config)

            result = gateway._build_prompt_for_logging("simple prompt")

            assert result == "simple prompt"

    def test_build_prompt_list_content(self, mock_config):
        """Test that list content is logged correctly."""
        with patch("selko.services.llm_gateway.get_gemini_client"):
            gateway = LLMGateway(mock_config)

            content = ["part1", "part2", "part3"]
            result = gateway._build_prompt_for_logging(content)

            assert result == "part1part2part3"

    def test_build_prompt_with_attachments(self, mock_config):
        """Test that attachments are noted in logging."""
        with patch("selko.services.llm_gateway.get_gemini_client"):
            gateway = LLMGateway(mock_config)

            content = [
                "prompt text",
                {"inline_data": {"mime_type": "image/jpeg", "data": "base64data"}},
            ]
            result = gateway._build_prompt_for_logging(content)

            assert "prompt text" in result
            assert "[1 attachment(s) included]" in result


class TestErrorClassification:
    """Tests for error classification."""

    def test_classify_rate_limit_429(self, mock_config):
        """Test rate limit classification for 429 errors."""
        with patch("selko.services.llm_gateway.get_gemini_client"):
            gateway = LLMGateway(mock_config)

            assert gateway._is_rate_limit_error("429 too many requests")

    def test_classify_rate_limit_quota(self, mock_config):
        """Test rate limit classification for quota errors."""
        with patch("selko.services.llm_gateway.get_gemini_client"):
            gateway = LLMGateway(mock_config)

            assert gateway._is_rate_limit_error("quota exceeded")

    def test_classify_not_rate_limit(self, mock_config):
        """Test non-rate-limit error classification."""
        with patch("selko.services.llm_gateway.get_gemini_client"):
            gateway = LLMGateway(mock_config)

            assert not gateway._is_rate_limit_error("invalid api key")
