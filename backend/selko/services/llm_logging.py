"""LLM call logging service.

Logs all LLM API calls to the database with prompts, responses, metrics,
and cost tracking for auditing and analysis.
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional, TypeVar

from supabase import Client

logger = logging.getLogger(__name__)

# Type variable for generic return types
T = TypeVar("T")


class LLMOperationType(str, Enum):
    """Types of LLM operations."""

    EXTRACT_EVENTS = "extract_events"
    CLASSIFY_EMAIL_FOLDER = "classify_email_folder"
    COMPARE_EVENTS = "compare_events"
    MERGE_EVENTS = "merge_events"
    PROPOSE_EVENT_UPDATE = "propose_event_update"


class LLMErrorType(str, Enum):
    """Classification of LLM errors."""

    RATE_LIMIT = "rate_limit"
    API_ERROR = "api_error"
    TIMEOUT = "timeout"
    INVALID_RESPONSE = "invalid_response"
    UNKNOWN = "unknown"


# Default fallback pricing per 1M tokens in USD
_DEFAULT_PRICING = {"input": 0.15, "output": 0.60}


@dataclass
class LLMCallMetrics:
    """Metrics collected from an LLM call."""

    prompt_tokens: Optional[int] = None
    completion_tokens: Optional[int] = None
    total_tokens: Optional[int] = None
    latency_ms: Optional[int] = None


@dataclass
class LLMCallRecord:
    """Complete record of an LLM API call."""

    user_id: str
    operation_type: LLMOperationType
    model: str
    prompt_text: str
    response_text: Optional[str] = None
    email_id: Optional[str] = None
    provider: Optional[str] = None
    metrics: LLMCallMetrics = field(default_factory=LLMCallMetrics)
    success: bool = True
    error_message: Optional[str] = None
    error_type: Optional[LLMErrorType] = None
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None


def estimate_cost(
    model: str,
    prompt_tokens: Optional[int],
    completion_tokens: Optional[int],
) -> Optional[float]:
    """Estimate cost of an LLM call based on token usage.

    Args:
        model: Model name (e.g., 'gemini-3-flash-preview').
        prompt_tokens: Number of input tokens.
        completion_tokens: Number of output tokens.

    Returns:
        Estimated cost in USD, or None if tokens not available.
    """
    if prompt_tokens is None or completion_tokens is None:
        return None

    # Look up pricing from MODEL_REGISTRY, fall back to default
    from selko.services.llm_provider import MODEL_REGISTRY

    registry_entry = MODEL_REGISTRY.get(model)
    pricing = registry_entry["pricing"] if registry_entry else _DEFAULT_PRICING

    input_cost = (prompt_tokens / 1_000_000) * pricing["input"]
    output_cost = (completion_tokens / 1_000_000) * pricing["output"]

    return round(input_cost + output_cost, 6)


class LLMLoggingService:
    """Service for logging LLM API calls to the database.

    Logs all details of LLM calls including prompts, responses, timing,
    and cost estimates for auditing and analysis.
    """

    def __init__(self, client: Client):
        """Initialize LLMLoggingService.

        Args:
            client: Supabase client (service role required for writes).
        """
        self.client = client

    def log_call(self, record: LLMCallRecord) -> Optional[str]:
        """Log an LLM call to the database.

        Args:
            record: Complete record of the LLM call.

        Returns:
            UUID of the created log entry, or None on error.
        """
        try:
            # Calculate cost estimate
            estimated_cost = estimate_cost(
                record.model,
                record.metrics.prompt_tokens,
                record.metrics.completion_tokens,
            )

            # Build insert data
            data = {
                "user_id": record.user_id,
                "operation_type": record.operation_type.value,
                "model": record.model,
                "prompt_text": record.prompt_text,
                "response_text": record.response_text,
                "email_id": record.email_id,
                "prompt_tokens": record.metrics.prompt_tokens,
                "completion_tokens": record.metrics.completion_tokens,
                "total_tokens": record.metrics.total_tokens,
                "started_at": record.started_at.isoformat(),
                "completed_at": (
                    record.completed_at.isoformat() if record.completed_at else None
                ),
                "latency_ms": record.metrics.latency_ms,
                "success": record.success,
                "error_message": record.error_message,
                "error_type": record.error_type.value if record.error_type else None,
                "estimated_cost_usd": estimated_cost,
            }

            if record.provider:
                data["provider"] = record.provider

            result = self.client.table("llm_call_log").insert(data).execute()

            if result.data:
                log_id = result.data[0]["id"]
                logger.debug(
                    f"Logged LLM call: {record.operation_type.value} "
                    f"(latency={record.metrics.latency_ms}ms, "
                    f"tokens={record.metrics.total_tokens})"
                )
                return log_id

            return None

        except Exception as e:
            # Log to console but don't fail the main operation
            logger.error(f"Failed to log LLM call: {e}")
            return None

    def log_success(
        self,
        user_id: str,
        operation_type: LLMOperationType,
        model: str,
        prompt_text: str,
        response_text: str,
        latency_ms: int,
        email_id: Optional[str] = None,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        provider: Optional[str] = None,
    ) -> Optional[str]:
        """Convenience method to log a successful LLM call.

        Args:
            user_id: User UUID.
            operation_type: Type of LLM operation.
            model: Model name.
            prompt_text: Full prompt sent.
            response_text: Full response received.
            latency_ms: Call duration in milliseconds.
            email_id: Optional linked email UUID.
            prompt_tokens: Optional input token count.
            completion_tokens: Optional output token count.
            provider: Optional provider name (e.g., "gemini", "moonshot").

        Returns:
            UUID of the created log entry, or None on error.
        """
        total_tokens = None
        if prompt_tokens is not None and completion_tokens is not None:
            total_tokens = prompt_tokens + completion_tokens

        record = LLMCallRecord(
            user_id=user_id,
            operation_type=operation_type,
            model=model,
            prompt_text=prompt_text,
            response_text=response_text,
            email_id=email_id,
            provider=provider,
            metrics=LLMCallMetrics(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                latency_ms=latency_ms,
            ),
            success=True,
            completed_at=datetime.now(timezone.utc),
        )

        return self.log_call(record)

    def log_failure(
        self,
        user_id: str,
        operation_type: LLMOperationType,
        model: str,
        prompt_text: str,
        error_message: str,
        latency_ms: int,
        error_type: LLMErrorType = LLMErrorType.UNKNOWN,
        email_id: Optional[str] = None,
        provider: Optional[str] = None,
    ) -> Optional[str]:
        """Log a failed LLM call.

        Args:
            user_id: User UUID.
            operation_type: Type of LLM operation.
            model: Model name.
            prompt_text: Full prompt that was sent.
            error_message: Error description.
            latency_ms: Call duration until failure.
            error_type: Classification of the error.
            email_id: Optional linked email UUID.
            provider: Optional provider name (e.g., "gemini", "moonshot").

        Returns:
            UUID of the created log entry, or None on error.
        """
        record = LLMCallRecord(
            user_id=user_id,
            operation_type=operation_type,
            model=model,
            prompt_text=prompt_text,
            email_id=email_id,
            provider=provider,
            metrics=LLMCallMetrics(latency_ms=latency_ms),
            success=False,
            error_message=error_message,
            error_type=error_type,
            completed_at=datetime.now(timezone.utc),
        )

        return self.log_call(record)

    def get_user_usage_summary(
        self,
        user_id: str,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> dict[str, Any]:
        """Get LLM usage summary for a user.

        Args:
            user_id: User UUID.
            start_date: Start date (YYYY-MM-DD), defaults to today.
            end_date: End date (YYYY-MM-DD), defaults to today.

        Returns:
            Dict with usage statistics.
        """
        try:
            params: dict[str, Any] = {"p_user_id": user_id}
            if start_date:
                params["p_start_date"] = start_date
            if end_date:
                params["p_end_date"] = end_date

            result = self.client.rpc("get_llm_usage_summary", params).execute()

            if result.data and len(result.data) > 0:
                return result.data[0]

            return {
                "total_calls": 0,
                "successful_calls": 0,
                "failed_calls": 0,
                "total_tokens": 0,
                "total_prompt_tokens": 0,
                "total_completion_tokens": 0,
                "total_latency_ms": 0,
                "avg_latency_ms": 0,
                "estimated_cost_usd": 0,
                "calls_by_operation": {},
            }

        except Exception as e:
            logger.error(f"Failed to get LLM usage summary: {e}")
            return {}


def get_llm_logging_service(client: Client) -> LLMLoggingService:
    """Factory function to create LLMLoggingService.

    Args:
        client: Supabase client.

    Returns:
        Configured LLMLoggingService instance.
    """
    return LLMLoggingService(client)


class LLMCallContext:
    """Context manager for tracking LLM call timing and logging.

    Automatically tracks timing and logs the result (success or failure)
    when the context exits.

    Usage:
        with LLMCallContext(logging_service, user_id, operation, model, prompt) as ctx:
            response = gateway.generate(...)
            ctx.set_response(response.text, tokens=...)

        # Automatically logged on exit
    """

    def __init__(
        self,
        logging_service: LLMLoggingService,
        user_id: str,
        operation_type: LLMOperationType,
        model: str,
        prompt_text: str,
        email_id: Optional[str] = None,
    ):
        self.logging_service = logging_service
        self.user_id = user_id
        self.operation_type = operation_type
        self.model = model
        self.prompt_text = prompt_text
        self.email_id = email_id

        self._start_time: float = 0
        self._response_text: Optional[str] = None
        self._prompt_tokens: Optional[int] = None
        self._completion_tokens: Optional[int] = None
        self._error: Optional[Exception] = None

    def __enter__(self) -> "LLMCallContext":
        self._start_time = time.time()
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> bool:
        latency_ms = int((time.time() - self._start_time) * 1000)

        if exc_val is not None:
            # Call failed with exception
            error_type = self._classify_error(exc_val)
            self.logging_service.log_failure(
                user_id=self.user_id,
                operation_type=self.operation_type,
                model=self.model,
                prompt_text=self.prompt_text,
                error_message=str(exc_val),
                latency_ms=latency_ms,
                error_type=error_type,
                email_id=self.email_id,
            )
        elif self._error is not None:
            # Explicitly set error
            error_type = self._classify_error(self._error)
            self.logging_service.log_failure(
                user_id=self.user_id,
                operation_type=self.operation_type,
                model=self.model,
                prompt_text=self.prompt_text,
                error_message=str(self._error),
                latency_ms=latency_ms,
                error_type=error_type,
                email_id=self.email_id,
            )
        else:
            # Call succeeded
            self.logging_service.log_success(
                user_id=self.user_id,
                operation_type=self.operation_type,
                model=self.model,
                prompt_text=self.prompt_text,
                response_text=self._response_text or "",
                latency_ms=latency_ms,
                email_id=self.email_id,
                prompt_tokens=self._prompt_tokens,
                completion_tokens=self._completion_tokens,
            )

        # Don't suppress exceptions
        return False

    def set_response(
        self,
        response_text: str,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
    ) -> None:
        """Set the successful response data.

        Args:
            response_text: Full response from LLM.
            prompt_tokens: Input token count (if available).
            completion_tokens: Output token count (if available).
        """
        self._response_text = response_text
        self._prompt_tokens = prompt_tokens
        self._completion_tokens = completion_tokens

    def set_error(self, error: Exception) -> None:
        """Explicitly set an error (for non-exception failures).

        Args:
            error: The error that occurred.
        """
        self._error = error

    def _classify_error(self, error: Exception) -> LLMErrorType:
        """Classify an error into a type.

        Args:
            error: The exception to classify.

        Returns:
            Error type classification.
        """
        error_str = str(error).lower()

        if "429" in error_str or "rate limit" in error_str or "quota" in error_str:
            return LLMErrorType.RATE_LIMIT
        elif "timeout" in error_str:
            return LLMErrorType.TIMEOUT
        elif "invalid" in error_str or "parse" in error_str:
            return LLMErrorType.INVALID_RESPONSE
        elif "api" in error_str or "500" in error_str or "503" in error_str:
            return LLMErrorType.API_ERROR
        else:
            return LLMErrorType.UNKNOWN
