"""Unified LLM Gateway for all LLM operations.

Provides a single entry point for all LLM calls with:
- Rate limit checking (per-call quota enforcement)
- Automatic timing and logging
- Validated primary/fallback routing for structured ops
- Retry logic with exponential backoff
- Error classification and handling

Supports multiple LLM providers via the LLMProvider abstraction.
"""

from __future__ import annotations

import logging
import random
import re
import time
import traceback
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Callable, Literal, Optional, TypeVar

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

T = TypeVar("T")


class LLMGatewayError(Exception):
    """Base exception for LLM gateway errors."""

    pass


class LLMRateLimitError(LLMGatewayError):
    """Raised when rate limit is exceeded."""

    pass


class LLMAPIError(LLMGatewayError):
    """Raised when LLM API call fails."""

    pass


class LLMFailureKind(StrEnum):
    """Classification of structured-call failures for routing decisions."""

    TRANSIENT = "transient"
    EMPTY = "empty"
    INVALID_JSON = "invalid_json"
    INVALID_SCHEMA = "invalid_schema"
    TRUNCATED = "truncated"
    PERMANENT_PROVIDER = "permanent_provider"


@dataclass(frozen=True)
class LLMRoute:
    """A configured provider route (primary or fallback)."""

    role: Literal["primary", "fallback"]
    provider: LLMProvider
    max_attempts: int


@dataclass(frozen=True)
class LLMAttemptRecord:
    """One physical provider attempt within a logical operation."""

    route_role: Literal["primary", "fallback"]
    provider: str
    model: str
    attempt: int
    max_attempts: int
    failure_kind: Optional[LLMFailureKind] = None
    error_message: Optional[str] = None
    finish_reason: Optional[str] = None
    accepted: bool = False
    latency_ms: Optional[int] = None


class LLMValidationError(LLMGatewayError):
    """Raised by validators when an HTTP response fails structured validation."""

    def __init__(self, kind: LLMFailureKind, message: str):
        super().__init__(message)
        self.kind = kind


class LLMValidatedCallError(LLMGatewayError):
    """Raised when primary (and optional fallback) fail to produce valid output."""

    def __init__(
        self,
        message: str,
        *,
        kind: LLMFailureKind,
        attempts: list[LLMAttemptRecord],
        correlation_id: str,
    ):
        super().__init__(message)
        self.kind = kind
        self.attempts = attempts
        self.correlation_id = correlation_id


# Failure kinds that skip remaining primary retries and go straight to fallback.
_IMMEDIATE_FALLBACK_KINDS = frozenset(
    {
        LLMFailureKind.EMPTY,
        LLMFailureKind.INVALID_JSON,
        LLMFailureKind.INVALID_SCHEMA,
        LLMFailureKind.TRUNCATED,
    }
)

_TRUNCATED_FINISH_MARKERS = (
    "length",
    "max_token",
    "max_tokens",
    "truncated",
)

_RETRY_AFTER_RE = re.compile(r"retry[- ]after[:\s]+(\d+(?:\.\d+)?)", re.IGNORECASE)


class LLMGateway:
    """Unified gateway for all LLM operations.

    Handles all LLM execution concerns:
    - Rate limit checking (increments quota on each call)
    - Automatic timing
    - Validated primary/fallback routing via ``call_validated``
    - Retry logic with exponential backoff for ``call``
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
        fallback_provider: Optional[LLMProvider] = None,
        primary_max_attempts: int = 3,
        fallback_max_attempts: int = 2,
    ):
        """Initialize LLMGateway.

        Args:
            provider: Primary LLM provider instance.
            logging_service: Optional service for logging LLM calls.
            quota_service: Optional service for rate limiting.
            fallback_provider: Optional different-provider fallback.
            primary_max_attempts: Max primary attempts for transient failures.
            fallback_max_attempts: Max fallback attempts for transient failures.
        """
        self.provider = provider
        self.fallback_provider = fallback_provider
        self.model = provider.model
        self.primary_max_attempts = max(1, primary_max_attempts)
        self.fallback_max_attempts = max(1, fallback_max_attempts)
        self.logging_service = logging_service
        self.quota_service = quota_service
        self.user_id: Optional[str] = None
        self.email_id: Optional[str] = None
        # Last call token counts (for eval/observability)
        self._last_prompt_tokens: Optional[int] = None
        self._last_completion_tokens: Optional[int] = None
        # Optional tracing — set to {} to enable, None to disable
        self.trace: Optional[dict[str, Any]] = None
        self._last_attempts: list[LLMAttemptRecord] = []
        self._last_correlation_id: Optional[str] = None

    @property
    def routes(self) -> list[LLMRoute]:
        """Configured routes in evaluation order."""
        routes = [
            LLMRoute(
                role="primary",
                provider=self.provider,
                max_attempts=self.primary_max_attempts,
            )
        ]
        if self.fallback_provider is not None:
            routes.append(
                LLMRoute(
                    role="fallback",
                    provider=self.fallback_provider,
                    max_attempts=self.fallback_max_attempts,
                )
            )
        return routes

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
        """Execute unstructured LLM call with rate limiting, timing, retries, and logging.

        Prefer ``call_validated`` for calendar extraction/compare/merge. This
        method remains for genuinely unstructured operations (e.g. folder
        classification) where response text is not schema-validated here.

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
        self._check_quota()

        prompt_for_logging = self._build_prompt_for_logging(contents)
        self._init_trace(contents, json_schema)

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
                    provider=self.provider,
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
                        wait_time = self._backoff_seconds(attempt, e)
                        logger.warning(
                            f"Rate limited by {self.provider.provider_name} API, "
                            f"waiting {wait_time:.1f}s "
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
                            provider=self.provider,
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
                        provider=self.provider,
                    )
                    raise LLMAPIError(
                        f"{self.provider.provider_name} API error: {e}"
                    ) from e

        # Should not reach here, but just in case
        raise LLMRateLimitError(f"Failed after {max_retries} retries")

    def call_validated(
        self,
        operation: LLMOperationType,
        contents: list[ContentPart],
        validator: Callable[[LLMResponse], T],
        json_schema: Optional[dict] = None,
    ) -> T:
        """Execute a structured LLM call with validation-aware routing.

        Primary route: up to ``primary_max_attempts`` for transient failures.
        Empty/invalid JSON/schema/truncated skip remaining primary attempts and
        call the fallback immediately (when configured). Fallback gets up to
        ``fallback_max_attempts`` for transient failures only. Permanent/auth
        errors never fall back.

        An HTTP-success response that fails validation is logged as a failed
        attempt (not success).

        Args:
            operation: Type of LLM operation for logging/metrics.
            contents: Multimodal content parts.
            validator: Callable that parses/validates ``LLMResponse`` into ``T``.
                Must raise ``LLMValidationError`` (or let gateway wrap other
                exceptions) on protocol/schema failures.
            json_schema: Optional JSON schema passed to the provider.

        Returns:
            Validated result of type ``T``.

        Raises:
            QuotaExceededError: If user's daily quota is exceeded.
            LLMValidatedCallError: If all routes fail validation/transiently.
            LLMRateLimitError: If exhaustion is purely rate-limit/transient.
            LLMAPIError: If a permanent provider error occurs.
        """
        self._check_quota()

        correlation_id = uuid.uuid4().hex
        self._last_correlation_id = correlation_id
        attempts: list[LLMAttemptRecord] = []
        self._last_attempts = attempts

        prompt_for_logging = self._build_prompt_for_logging(contents)
        self._init_trace(contents, json_schema)
        if self.trace is not None:
            self.trace["correlation_id"] = correlation_id

        logger.info(
            "LLM validated call start operation=%s correlation_id=%s "
            "primary=%s/%s fallback=%s",
            operation.value,
            correlation_id,
            self.provider.provider_name,
            self.provider.model,
            (
                f"{self.fallback_provider.provider_name}/{self.fallback_provider.model}"
                if self.fallback_provider
                else "none"
            ),
        )

        last_failure_kind = LLMFailureKind.PERMANENT_PROVIDER
        last_error: Optional[BaseException] = None

        for route in self.routes:
            route_exhausted_transient = False
            for attempt_idx in range(route.max_attempts):
                start_time = time.time()
                response: Optional[LLMResponse] = None
                try:
                    logger.info(
                        "Calling %s %s for %s [%s attempt %s/%s] correlation_id=%s",
                        route.provider.provider_name,
                        route.provider.model,
                        operation.value,
                        route.role,
                        attempt_idx + 1,
                        route.max_attempts,
                        correlation_id,
                    )
                    response = route.provider.generate(
                        contents=contents,
                        json_schema=json_schema,
                    )
                    latency_ms = int((time.time() - start_time) * 1000)

                    self._last_prompt_tokens = response.prompt_tokens
                    self._last_completion_tokens = response.completion_tokens
                    if self.trace is not None:
                        self.trace["raw_response_text"] = response.text
                        self.trace["finish_reason"] = response.finish_reason
                        self.trace["retry_count"] = attempt_idx
                        self.trace["route_role"] = route.role
                        self.trace["json_schema_sanitized"] = getattr(
                            route.provider, "_last_sanitized_schema", None
                        )

                    # Protocol checks before caller validator.
                    if response.text is None or not str(response.text).strip():
                        raise LLMValidationError(
                            LLMFailureKind.EMPTY, "Empty LLM response"
                        )
                    if self._is_truncated_finish(response.finish_reason):
                        raise LLMValidationError(
                            LLMFailureKind.TRUNCATED,
                            f"Truncated LLM response (finish_reason={response.finish_reason})",
                        )

                    try:
                        result = validator(response)
                    except LLMValidationError:
                        raise
                    except Exception as exc:
                        # Unexpected validator errors still count as schema failure.
                        raise LLMValidationError(
                            LLMFailureKind.INVALID_SCHEMA, str(exc)
                        ) from exc

                    attempts.append(
                        LLMAttemptRecord(
                            route_role=route.role,
                            provider=route.provider.provider_name,
                            model=route.provider.model,
                            attempt=attempt_idx + 1,
                            max_attempts=route.max_attempts,
                            finish_reason=response.finish_reason,
                            accepted=True,
                            latency_ms=latency_ms,
                        )
                    )
                    self._log_success(
                        operation=operation,
                        prompt_text=prompt_for_logging,
                        response=response,
                        latency_ms=latency_ms,
                        provider=route.provider,
                    )
                    # Keep gateway.model aligned with the accepted route.
                    self.model = route.provider.model
                    return result

                except LLMValidationError as e:
                    latency_ms = int((time.time() - start_time) * 1000)
                    last_failure_kind = e.kind
                    last_error = e
                    attempts.append(
                        LLMAttemptRecord(
                            route_role=route.role,
                            provider=route.provider.provider_name,
                            model=route.provider.model,
                            attempt=attempt_idx + 1,
                            max_attempts=route.max_attempts,
                            failure_kind=e.kind,
                            error_message=str(e),
                            finish_reason=(
                                response.finish_reason if response is not None else None
                            ),
                            accepted=False,
                            latency_ms=latency_ms,
                        )
                    )
                    self._log_failure(
                        operation=operation,
                        prompt_text=prompt_for_logging,
                        error_message=f"[{e.kind.value}] {e}",
                        latency_ms=latency_ms,
                        error_type=self._failure_kind_to_error_type(e.kind),
                        provider=route.provider,
                    )
                    if self.trace is not None:
                        self.trace["error_traceback"] = traceback.format_exc()
                        self.trace["failure_kind"] = e.kind.value

                    # Malformed/empty/truncated → immediate fallback (or fail).
                    if e.kind in _IMMEDIATE_FALLBACK_KINDS:
                        break
                    # Other validation kinds should not happen; treat like immediate.
                    break

                except Exception as e:
                    latency_ms = int((time.time() - start_time) * 1000)
                    error_str = str(e).lower()
                    kind = self._classify_provider_failure(error_str)
                    last_failure_kind = kind
                    last_error = e
                    attempts.append(
                        LLMAttemptRecord(
                            route_role=route.role,
                            provider=route.provider.provider_name,
                            model=route.provider.model,
                            attempt=attempt_idx + 1,
                            max_attempts=route.max_attempts,
                            failure_kind=kind,
                            error_message=str(e),
                            accepted=False,
                            latency_ms=latency_ms,
                        )
                    )
                    self._log_failure(
                        operation=operation,
                        prompt_text=prompt_for_logging,
                        error_message=f"[{kind.value}] {e}",
                        latency_ms=latency_ms,
                        error_type=self._failure_kind_to_error_type(kind),
                        provider=route.provider,
                    )
                    if self.trace is not None:
                        self.trace["retry_count"] = attempt_idx
                        self.trace["error_traceback"] = traceback.format_exc()
                        self.trace["failure_kind"] = kind.value
                        self.trace["json_schema_sanitized"] = getattr(
                            route.provider, "_last_sanitized_schema", None
                        )

                    if kind == LLMFailureKind.PERMANENT_PROVIDER:
                        raise LLMAPIError(
                            f"{route.provider.provider_name} API error: {e}"
                        ) from e

                    # Transient: retry same route if attempts remain.
                    if attempt_idx < route.max_attempts - 1:
                        wait_time = self._backoff_seconds(attempt_idx, e)
                        logger.warning(
                            "Transient %s failure on %s, waiting %.1fs "
                            "(attempt %s/%s) correlation_id=%s",
                            route.role,
                            route.provider.provider_name,
                            wait_time,
                            attempt_idx + 1,
                            route.max_attempts,
                            correlation_id,
                        )
                        time.sleep(wait_time)
                        continue

                    route_exhausted_transient = True
                    break

            # After a route ends: continue to fallback only for transient
            # exhaustion or immediate-fallback protocol failures.
            if last_failure_kind == LLMFailureKind.PERMANENT_PROVIDER:
                break
            if (
                last_failure_kind in _IMMEDIATE_FALLBACK_KINDS
                or route_exhausted_transient
            ):
                continue
            break

        message = (
            f"Validated LLM call failed for {operation.value} "
            f"(correlation_id={correlation_id}, kind={last_failure_kind.value}, "
            f"attempts={len(attempts)})"
        )
        if last_error is not None:
            message = f"{message}: {last_error}"

        if last_failure_kind == LLMFailureKind.TRANSIENT:
            raise LLMRateLimitError(message) from last_error

        raise LLMValidatedCallError(
            message,
            kind=last_failure_kind,
            attempts=attempts,
            correlation_id=correlation_id,
        ) from last_error

    def _check_quota(self) -> None:
        """Raise QuotaExceededError if the user's daily LLM quota is exceeded."""
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

    def _init_trace(
        self, contents: list[ContentPart], json_schema: Optional[dict]
    ) -> None:
        if self.trace is not None:
            self.trace["content_parts"] = self._summarize_content_parts(contents)
            self.trace["json_schema_input"] = json_schema
            self.trace["json_schema_sanitized"] = None
            self.trace["raw_response_text"] = None
            self.trace["finish_reason"] = None
            self.trace["retry_count"] = 0
            self.trace["error_traceback"] = None

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
        return self._classify_provider_failure(error_str) == LLMFailureKind.TRANSIENT

    def _is_truncated_finish(self, finish_reason: Optional[str]) -> bool:
        if not finish_reason:
            return False
        fr = str(finish_reason).lower()
        return any(marker in fr for marker in _TRUNCATED_FINISH_MARKERS)

    def _classify_provider_failure(self, error_str: str) -> LLMFailureKind:
        """Classify a provider exception into transient vs permanent."""
        if any(
            marker in error_str
            for marker in (
                "401",
                "403",
                "authentication",
                "unauthorized",
                "invalid api key",
                "invalid_api_key",
                "permission",
                "forbidden",
                "invalid_request",
                "invalid request",
                "unsupported",
                "does not support",
                "model_not_found",
                "not found: model",
                "unknown model",
            )
        ):
            return LLMFailureKind.PERMANENT_PROVIDER

        if any(
            marker in error_str
            for marker in (
                "429",
                "408",
                "500",
                "502",
                "503",
                "504",
                "rate limit",
                "quota",
                "timeout",
                "timed out",
                "connection reset",
                "connection aborted",
                "connection refused",
                "temporarily unavailable",
                "unavailable",
                "overloaded",
                "high demand",
                "server error",
                "errno 11",
                "resource temporarily",
            )
        ):
            return LLMFailureKind.TRANSIENT

        return LLMFailureKind.PERMANENT_PROVIDER

    def _classify_error(self, error_str: str) -> LLMErrorType:
        """Classify an error into a logging type.

        Args:
            error_str: Lowercase error string.

        Returns:
            Error type classification.
        """
        kind = self._classify_provider_failure(error_str)
        return self._failure_kind_to_error_type(kind)

    def _failure_kind_to_error_type(self, kind: LLMFailureKind) -> LLMErrorType:
        if kind == LLMFailureKind.TRANSIENT:
            return LLMErrorType.RATE_LIMIT
        if kind == LLMFailureKind.EMPTY:
            return LLMErrorType.INVALID_RESPONSE
        if kind in (
            LLMFailureKind.INVALID_JSON,
            LLMFailureKind.INVALID_SCHEMA,
            LLMFailureKind.TRUNCATED,
        ):
            return LLMErrorType.INVALID_RESPONSE
        if kind == LLMFailureKind.PERMANENT_PROVIDER:
            return LLMErrorType.API_ERROR
        return LLMErrorType.UNKNOWN

    def _backoff_seconds(self, attempt: int, error: BaseException) -> float:
        """Exponential backoff with jitter; honor Retry-After when present."""
        match = _RETRY_AFTER_RE.search(str(error))
        if match:
            try:
                return max(0.0, float(match.group(1)))
            except ValueError:
                pass
        return (2**attempt) + random.uniform(0, 1)

    def _log_success(
        self,
        operation: LLMOperationType,
        prompt_text: str,
        response: LLMResponse,
        latency_ms: int,
        provider: Optional[LLMProvider] = None,
    ) -> None:
        """Log a successful LLM call.

        Args:
            operation: Type of operation.
            prompt_text: The prompt sent.
            response: The LLMResponse received.
            latency_ms: Call duration in milliseconds.
            provider: Provider that produced the response.
        """
        if not self.logging_service or not self.user_id:
            return

        active = provider or self.provider
        self.logging_service.log_success(
            user_id=self.user_id,
            operation_type=operation,
            model=active.model,
            prompt_text=prompt_text,
            response_text=response.text,
            latency_ms=latency_ms,
            email_id=self.email_id,
            prompt_tokens=response.prompt_tokens,
            completion_tokens=response.completion_tokens,
            provider=active.provider_name,
        )

    def _log_failure(
        self,
        operation: LLMOperationType,
        prompt_text: str,
        error_message: str,
        latency_ms: int,
        error_type: LLMErrorType,
        provider: Optional[LLMProvider] = None,
    ) -> None:
        """Log a failed LLM call.

        Args:
            operation: Type of operation.
            prompt_text: The prompt sent.
            error_message: Error description.
            latency_ms: Call duration until failure.
            error_type: Classification of the error.
            provider: Provider that failed.
        """
        if not self.logging_service or not self.user_id:
            return

        active = provider or self.provider
        self.logging_service.log_failure(
            user_id=self.user_id,
            operation_type=operation,
            model=active.model,
            prompt_text=prompt_text,
            error_message=error_message,
            latency_ms=latency_ms,
            error_type=error_type,
            email_id=self.email_id,
            provider=active.provider_name,
        )


def create_llm_gateway(
    config: Any,
    logging_service: Optional[LLMLoggingService] = None,
    quota_service: Optional[QuotaService] = None,
) -> LLMGateway:
    """Build a gateway with primary and optional fallback providers from config.

    Fallback is omitted (with a prior loud warning from ``load_config``) when
    the fallback provider/model/key is unavailable.
    """
    from selko.services.llm_provider import create_provider

    thinking = getattr(config, "llm_thinking", None) or "low"
    primary = create_provider(config, thinking=thinking)

    fallback_provider: Optional[LLMProvider] = None
    fallback_name = getattr(config, "llm_fallback_provider", None)
    fallback_model = getattr(config, "llm_fallback_model", None)
    fallback_thinking = getattr(config, "llm_fallback_thinking", None) or "low"
    if fallback_name and fallback_model and _fallback_api_key_present(config, fallback_name):
        try:
            fallback_provider = create_provider(
                config,
                thinking=fallback_thinking,
                provider_name=fallback_name,
                model_name=fallback_model,
            )
        except Exception as exc:
            logger.warning(
                "LLM fallback provider could not be created (%s/%s): %s",
                fallback_name,
                fallback_model,
                exc,
            )

    return LLMGateway(
        provider=primary,
        logging_service=logging_service,
        quota_service=quota_service,
        fallback_provider=fallback_provider,
        primary_max_attempts=int(getattr(config, "llm_primary_max_attempts", 3) or 3),
        fallback_max_attempts=int(getattr(config, "llm_fallback_max_attempts", 2) or 2),
    )


def _fallback_api_key_present(config: Any, provider_name: str) -> bool:
    from selko.services.llm_provider import PROVIDER_API_KEY_MAP

    attr = PROVIDER_API_KEY_MAP.get(provider_name)
    if not attr:
        return False
    return bool(getattr(config, attr, None))
