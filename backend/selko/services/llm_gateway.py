"""Unified LLM Gateway for all LLM operations.

Provides a single entry point for all LLM calls with:
- Rate limit checking (per-call quota enforcement)
- Automatic timing and logging
- Retry logic with exponential backoff
- Error classification and handling
"""

import logging
import time
from typing import Any, Optional

from google import genai
from google.genai.types import GenerateContentConfig, GenerateContentResponse

from selko.config import Config
from selko.services.llm_logging import (
    LLMErrorType,
    LLMLoggingService,
    LLMOperationType,
)
from selko.services.quotas import QuotaExceededError, QuotaService

logger = logging.getLogger(__name__)


class LLMGatewayError(Exception):
    """Base exception for LLM gateway errors."""

    pass


class LLMRateLimitError(LLMGatewayError):
    """Raised when rate limit is exceeded."""

    pass


class LLMAPIError(LLMGatewayError):
    """Raised when LLM API call fails."""

    pass


def get_gemini_client(config: Config) -> genai.Client:
    """Initialize Gemini client with API key.

    Args:
        config: Application configuration with gemini_api_key.

    Returns:
        Initialized Gemini client.

    Raises:
        LLMGatewayError: If API key is missing or client initialization fails.
    """
    if not config.gemini_api_key:
        raise LLMGatewayError(
            "GEMINI_API_KEY not configured. "
            "Get your API key from https://aistudio.google.com/apikey"
        )

    try:
        client = genai.Client(api_key=config.gemini_api_key)
        logger.debug("Initialized Gemini client")
        return client
    except Exception as e:
        raise LLMGatewayError(f"Failed to initialize Gemini client: {e}") from e


class LLMGateway:
    """Unified gateway for all LLM operations.

    Handles all LLM execution concerns:
    - Rate limit checking (increments quota on each call)
    - Automatic timing
    - Retry logic with exponential backoff
    - Success/failure logging
    - Error classification

    Created per-request via dependency injection. Callers set context
    (user, email) and then call operations directly.

    Example:
        gateway = LLMGateway(config, logging_service, quota_service)
        gateway.for_user(user_id).for_email(email_id)
        response = gateway.call(
            operation=LLMOperationType.EXTRACT_EVENTS,
            contents=prompt,
            config=generate_config,
        )
    """

    def __init__(
        self,
        config: Config,
        logging_service: Optional[LLMLoggingService] = None,
        quota_service: Optional[QuotaService] = None,
    ):
        """Initialize LLMGateway.

        Args:
            config: Application configuration with Gemini API key.
            logging_service: Optional service for logging LLM calls.
            quota_service: Optional service for rate limiting.
        """
        self.client = get_gemini_client(config)
        self.model = config.gemini_model or "gemini-3-flash-preview"
        self.logging_service = logging_service
        self.quota_service = quota_service
        self.user_id: Optional[str] = None
        self.email_id: Optional[str] = None

    def for_user(self, user_id: str) -> "LLMGateway":
        """Set user context for logging and rate limiting.

        Args:
            user_id: UUID of the user making the request.

        Returns:
            Self for method chaining.
        """
        self.user_id = user_id
        return self

    def for_email(self, email_id: str) -> "LLMGateway":
        """Set email context for logging correlation.

        Args:
            email_id: UUID of the email being processed.

        Returns:
            Self for method chaining.
        """
        self.email_id = email_id
        return self

    def call(
        self,
        operation: LLMOperationType,
        contents: str | list,
        config: Optional[GenerateContentConfig] = None,
        max_retries: int = 1,
    ) -> GenerateContentResponse:
        """Execute LLM call with rate limiting, timing, retries, and logging.

        Args:
            operation: Type of LLM operation for logging/metrics.
            contents: Prompt content (string or list of content parts).
            config: Optional Gemini generation config.
            max_retries: Maximum retry attempts for rate-limited requests.

        Returns:
            GenerateContentResponse from Gemini.

        Raises:
            LLMRateLimitError: If quota is exceeded or rate limit exhausted.
            LLMAPIError: If API call fails for other reasons.
            QuotaExceededError: If user's daily quota is exceeded.
        """
        # Check rate limit BEFORE making the call
        if self.quota_service and self.user_id:
            quota_result = self.quota_service.check_and_increment(
                self.user_id, "llm_calls"
            )
            if not quota_result.allowed:
                raise QuotaExceededError(
                    quota_type="llm_calls",
                    current_count=quota_result.current_count,
                    limit=quota_result.limit,
                    message=(
                        f"Daily LLM quota exceeded: {quota_result.current_count}/"
                        f"{quota_result.limit}"
                    ),
                )

        # Build prompt text for logging
        prompt_for_logging = self._build_prompt_for_logging(contents)

        # Retry loop for rate limiting
        for attempt in range(max_retries):
            start_time = time.time()
            try:
                logger.info(f"Calling Gemini {self.model} for {operation.value}...")
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=contents,
                    config=config,
                )

                latency_ms = int((time.time() - start_time) * 1000)

                # Log successful call
                self._log_success(
                    operation=operation,
                    prompt_text=prompt_for_logging,
                    response=response,
                    latency_ms=latency_ms,
                )

                return response

            except Exception as e:
                latency_ms = int((time.time() - start_time) * 1000)
                error_str = str(e).lower()

                # Check for rate limiting from Gemini API
                if self._is_rate_limit_error(error_str):
                    if attempt < max_retries - 1:
                        wait_time = (2**attempt) + 1  # 1, 3, 5 seconds
                        logger.warning(
                            f"Rate limited by Gemini API, waiting {wait_time}s "
                            f"(attempt {attempt + 1}/{max_retries})"
                        )
                        time.sleep(wait_time)
                        continue
                    else:
                        # Log rate limit failure on final attempt
                        self._log_failure(
                            operation=operation,
                            prompt_text=prompt_for_logging,
                            error_message=str(e),
                            latency_ms=latency_ms,
                            error_type=LLMErrorType.RATE_LIMIT,
                        )
                        raise LLMRateLimitError(
                            f"Failed after {max_retries} retries (rate limited)"
                        ) from e
                else:
                    # Other errors - log and fail immediately
                    error_type = self._classify_error(error_str)
                    self._log_failure(
                        operation=operation,
                        prompt_text=prompt_for_logging,
                        error_message=str(e),
                        latency_ms=latency_ms,
                        error_type=error_type,
                    )
                    raise LLMAPIError(f"Gemini API error: {e}") from e

        # Should not reach here, but just in case
        raise LLMRateLimitError(f"Failed after {max_retries} retries")

    def _build_prompt_for_logging(self, contents: str | list) -> str:
        """Build a string representation of the prompt for logging.

        Args:
            contents: Prompt content.

        Returns:
            String suitable for logging.
        """
        if isinstance(contents, str):
            return contents
        elif isinstance(contents, list):
            parts = []
            attachment_count = 0
            for item in contents:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict) and "inline_data" in item:
                    attachment_count += 1
                else:
                    parts.append(str(item))

            result = "".join(parts)
            if attachment_count > 0:
                result += f"\n[{attachment_count} attachment(s) included]"
            return result
        else:
            return str(contents)

    def _is_rate_limit_error(self, error_str: str) -> bool:
        """Check if error is a rate limit error.

        Args:
            error_str: Lowercase error string.

        Returns:
            True if rate limit error.
        """
        return (
            "429" in error_str
            or "rate limit" in error_str
            or "quota" in error_str
        )

    def _classify_error(self, error_str: str) -> LLMErrorType:
        """Classify an error into a type.

        Args:
            error_str: Lowercase error string.

        Returns:
            Error type classification.
        """
        if self._is_rate_limit_error(error_str):
            return LLMErrorType.RATE_LIMIT
        elif "timeout" in error_str:
            return LLMErrorType.TIMEOUT
        elif "invalid" in error_str or "parse" in error_str:
            return LLMErrorType.INVALID_RESPONSE
        elif "api" in error_str or "500" in error_str or "503" in error_str:
            return LLMErrorType.API_ERROR
        else:
            return LLMErrorType.UNKNOWN

    def _log_success(
        self,
        operation: LLMOperationType,
        prompt_text: str,
        response: GenerateContentResponse,
        latency_ms: int,
    ) -> None:
        """Log a successful LLM call.

        Args:
            operation: Type of operation.
            prompt_text: The prompt sent.
            response: The response received.
            latency_ms: Call duration in milliseconds.
        """
        if not self.logging_service or not self.user_id:
            return

        # Extract token counts if available
        prompt_tokens = None
        completion_tokens = None
        if hasattr(response, "usage_metadata") and response.usage_metadata:
            prompt_tokens = getattr(
                response.usage_metadata, "prompt_token_count", None
            )
            completion_tokens = getattr(
                response.usage_metadata, "candidates_token_count", None
            )

        response_text = response.text if hasattr(response, "text") else str(response)

        self.logging_service.log_success(
            user_id=self.user_id,
            operation_type=operation,
            model=self.model,
            prompt_text=prompt_text,
            response_text=response_text,
            latency_ms=latency_ms,
            email_id=self.email_id,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        )

    def _log_failure(
        self,
        operation: LLMOperationType,
        prompt_text: str,
        error_message: str,
        latency_ms: int,
        error_type: LLMErrorType,
    ) -> None:
        """Log a failed LLM call.

        Args:
            operation: Type of operation.
            prompt_text: The prompt sent.
            error_message: Error description.
            latency_ms: Call duration until failure.
            error_type: Classification of the error.
        """
        if not self.logging_service or not self.user_id:
            return

        self.logging_service.log_failure(
            user_id=self.user_id,
            operation_type=operation,
            model=self.model,
            prompt_text=prompt_text,
            error_message=error_message,
            latency_ms=latency_ms,
            error_type=error_type,
            email_id=self.email_id,
        )
