"""Unified LLM Gateway for all LLM operations.

Provides a single entry point for all LLM calls with:
- Rate limit checking (per-call quota enforcement)
- Automatic timing and logging
- Retry logic with exponential backoff
- Error classification and handling

Supports multiple LLM providers via the LLMProvider abstraction.
"""

import logging
import traceback
import time
from typing import Any, Optional

from selko.services.llm_logging import (
    LLMErrorType,
    LLMLoggingService,
    LLMOperationType,
)
from selko.services.llm_provider import (
    ContentPart,
    ImageContent,
    LLMProvider,
    LLMResponse,
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
        provider = create_provider(config)
        gateway = LLMGateway(provider, logging_service, quota_service)
        gateway.for_user(user_id).for_email(email_id)
        response = gateway.call(
            operation=LLMOperationType.EXTRACT_EVENTS,
            contents=content_parts,
            json_schema=schema,
        )
    """

    def __init__(
        self,
        provider: LLMProvider,
        logging_service: Optional[LLMLoggingService] = None,
        quota_service: Optional[QuotaService] = None,
    ):
        """Initialize LLMGateway.

        Args:
            provider: LLM provider instance.
            logging_service: Optional service for logging LLM calls.
            quota_service: Optional service for rate limiting.
        """
        self.provider = provider
        self.model = provider.model
        self.logging_service = logging_service
        self.quota_service = quota_service
        self.user_id: Optional[str] = None
        self.email_id: Optional[str] = None
        # Last call token counts (for eval/observability)
        self._last_prompt_tokens: Optional[int] = None
        self._last_completion_tokens: Optional[int] = None
        # Optional tracing — set to {} to enable, None to disable
        self.trace: Optional[dict[str, Any]] = None

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
        contents: list[ContentPart],
        json_schema: Optional[dict] = None,
        max_retries: int = 1,
    ) -> LLMResponse:
        """Execute LLM call with rate limiting, timing, retries, and logging.

        Args:
            operation: Type of LLM operation for logging/metrics.
            contents: List of ContentPart (text strings and ImageContent).
            json_schema: Optional JSON schema for structured output.
            max_retries: Maximum retry attempts for rate-limited requests.

        Returns:
            LLMResponse with text and token counts.

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

        # Populate trace with pre-call data if tracing is enabled
        if self.trace is not None:
            self.trace["content_parts"] = self._summarize_content_parts(contents)
            self.trace["json_schema_input"] = json_schema
            self.trace["json_schema_sanitized"] = None
            self.trace["raw_response_text"] = None
            self.trace["finish_reason"] = None
            self.trace["retry_count"] = 0
            self.trace["error_traceback"] = None

        # Retry loop for rate limiting
        for attempt in range(max_retries):
            start_time = time.time()
            try:
                logger.info(
                    f"Calling {self.provider.provider_name} "
                    f"{self.model} for {operation.value}..."
                )
                response = self.provider.generate(
                    contents=contents,
                    json_schema=json_schema,
                )

                latency_ms = int((time.time() - start_time) * 1000)

                # Store token counts for observability
                self._last_prompt_tokens = response.prompt_tokens
                self._last_completion_tokens = response.completion_tokens

                # Populate trace with post-call data
                if self.trace is not None:
                    self.trace["raw_response_text"] = response.text
                    self.trace["finish_reason"] = response.finish_reason
                    self.trace["retry_count"] = attempt
                    self.trace["json_schema_sanitized"] = getattr(
                        self.provider, "_last_sanitized_schema", None
                    )

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

                # Populate trace with error data
                if self.trace is not None:
                    self.trace["retry_count"] = attempt
                    self.trace["error_traceback"] = traceback.format_exc()
                    self.trace["json_schema_sanitized"] = getattr(
                        self.provider, "_last_sanitized_schema", None
                    )

                # Check for rate limiting
                if self._is_retryable_error(error_str):
                    if attempt < max_retries - 1:
                        wait_time = (2**attempt) + 1  # 1, 3, 5 seconds
                        logger.warning(
                            f"Rate limited by {self.provider.provider_name} API, "
                            f"waiting {wait_time}s "
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
                    raise LLMAPIError(
                        f"{self.provider.provider_name} API error: {e}"
                    ) from e

        # Should not reach here, but just in case
        raise LLMRateLimitError(f"Failed after {max_retries} retries")

    def _summarize_content_parts(self, contents: list[ContentPart]) -> list[dict[str, Any]]:
        """Build a summary of content parts for tracing (no raw image data)."""
        summary = []
        for item in contents:
            if isinstance(item, str):
                summary.append({"type": "text", "length": len(item), "text": item})
            elif isinstance(item, ImageContent):
                summary.append({
                    "type": "image",
                    "mime_type": item.mime_type,
                    "size_bytes": len(item.data),
                })
        return summary

    def _build_prompt_for_logging(self, contents: list[ContentPart]) -> str:
        """Build a string representation of the prompt for logging.

        Args:
            contents: List of content parts.

        Returns:
            String suitable for logging.
        """
        parts = []
        attachment_count = 0
        for item in contents:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, ImageContent):
                attachment_count += 1
            else:
                parts.append(str(item))

        result = "".join(parts)
        if attachment_count > 0:
            result += f"\n[{attachment_count} attachment(s) included]"
        return result

    def _is_retryable_error(self, error_str: str) -> bool:
        """Check if error is retryable (rate limit or transient server error).

        Args:
            error_str: Lowercase error string.

        Returns:
            True if the error should be retried with backoff.
        """
        return (
            "429" in error_str
            or "rate limit" in error_str
            or "quota" in error_str
            or "503" in error_str
            or "unavailable" in error_str
            or "overloaded" in error_str
            or "high demand" in error_str
        )

    def _classify_error(self, error_str: str) -> LLMErrorType:
        """Classify an error into a type.

        Args:
            error_str: Lowercase error string.

        Returns:
            Error type classification.
        """
        if self._is_retryable_error(error_str):
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
        response: LLMResponse,
        latency_ms: int,
    ) -> None:
        """Log a successful LLM call.

        Args:
            operation: Type of operation.
            prompt_text: The prompt sent.
            response: The LLMResponse received.
            latency_ms: Call duration in milliseconds.
        """
        if not self.logging_service or not self.user_id:
            return

        self.logging_service.log_success(
            user_id=self.user_id,
            operation_type=operation,
            model=self.model,
            prompt_text=prompt_text,
            response_text=response.text,
            latency_ms=latency_ms,
            email_id=self.email_id,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            provider=self.provider.provider_name,
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
            provider=self.provider.provider_name,
        )
