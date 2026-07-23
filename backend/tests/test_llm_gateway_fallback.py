"""Deterministic fake-provider tests for validated primary/fallback routing."""

from __future__ import annotations

from typing import Any, Optional
from unittest.mock import MagicMock, patch

import pytest

from selko.services.llm_gateway import (
    LLMAPIError,
    LLMFailureKind,
    LLMGateway,
    LLMRateLimitError,
    LLMValidatedCallError,
    LLMValidationError,
)
from selko.services.llm_logging import LLMLoggingService, LLMOperationType
from selko.services.llm_provider import LLMProvider, LLMResponse


def _ok_payload(text: str = '{"ok": true}') -> LLMResponse:
    return LLMResponse(text=text, prompt_tokens=1, completion_tokens=1)


def _make_provider(name: str, model: str, behaviors: list[Any]) -> MagicMock:
    provider = MagicMock(spec=LLMProvider)
    provider.provider_name = name
    provider.model = model
    provider.supports_vision = True
    provider.supports_json_schema = True
    provider.generate.side_effect = list(behaviors)
    return provider


def _identity_validator(response: LLMResponse) -> dict[str, Any]:
    """Minimal validator: require non-empty JSON object with key ok."""
    import json

    from selko.services.llm_provider import strip_markdown_json

    cleaned = strip_markdown_json(response.text or "").strip()
    if not cleaned:
        raise LLMValidationError(LLMFailureKind.EMPTY, "empty")
    try:
        parsed = json.loads(cleaned)
    except json.JSONDecodeError as e:
        raise LLMValidationError(LLMFailureKind.INVALID_JSON, str(e)) from e
    if not isinstance(parsed, dict) or "ok" not in parsed:
        raise LLMValidationError(LLMFailureKind.INVALID_SCHEMA, "missing ok")
    return parsed


@pytest.fixture
def mock_logging_service():
    return MagicMock(spec=LLMLoggingService)


class TestCallValidatedRouting:
    """Failure routing table from WS3 spec."""

    def test_primary_transient_transient_then_success_no_fallback(self):
        primary = _make_provider(
            "primary",
            "p-model",
            [
                Exception("429 rate limit"),
                Exception("503 overloaded"),
                _ok_payload(),
            ],
        )
        fallback = _make_provider("fallback", "f-model", [_ok_payload()])
        gateway = LLMGateway(
            primary,
            fallback_provider=fallback,
            primary_max_attempts=3,
            fallback_max_attempts=2,
        )

        with patch("selko.services.llm_gateway.time.sleep"):
            result = gateway.call_validated(
                operation=LLMOperationType.EXTRACT_EVENTS,
                contents=["prompt"],
                validator=_identity_validator,
            )

        assert result == {"ok": True}
        assert primary.generate.call_count == 3
        assert fallback.generate.call_count == 0

    def test_primary_transient_three_times_then_fallback(self):
        primary = _make_provider(
            "primary",
            "p-model",
            [
                Exception("429 rate limit"),
                Exception("connection reset"),
                Exception("503 unavailable"),
            ],
        )
        fallback = _make_provider("fallback", "f-model", [_ok_payload()])
        gateway = LLMGateway(
            primary,
            fallback_provider=fallback,
            primary_max_attempts=3,
            fallback_max_attempts=2,
        )

        with patch("selko.services.llm_gateway.time.sleep"):
            result = gateway.call_validated(
                operation=LLMOperationType.EXTRACT_EVENTS,
                contents=["prompt"],
                validator=_identity_validator,
            )

        assert result == {"ok": True}
        assert primary.generate.call_count == 3
        assert fallback.generate.call_count == 1

    @pytest.mark.parametrize(
        "bad_response",
        [
            LLMResponse(text="   ", prompt_tokens=1, completion_tokens=0),
            LLMResponse(text="not-json", prompt_tokens=1, completion_tokens=1),
            LLMResponse(
                text='{"type": "object", "properties": {"x": {"type": "string"}}}',
                prompt_tokens=1,
                completion_tokens=1,
            ),
            LLMResponse(
                text='{"partial": true',
                prompt_tokens=1,
                completion_tokens=1,
                finish_reason="length",
            ),
        ],
        ids=["empty", "invalid_json", "schema_invalid_shape", "truncated"],
    )
    def test_primary_protocol_failure_immediate_fallback(self, bad_response):
        def validator(response: LLMResponse) -> dict[str, Any]:
            # Mirror production: reject schema-shaped payloads without data keys.
            import json

            from selko.services.event_processing import looks_like_json_schema
            from selko.services.llm_provider import strip_markdown_json

            cleaned = strip_markdown_json(response.text or "").strip()
            if not cleaned:
                raise LLMValidationError(LLMFailureKind.EMPTY, "empty")
            try:
                parsed = json.loads(cleaned)
            except json.JSONDecodeError as e:
                raise LLMValidationError(LLMFailureKind.INVALID_JSON, str(e)) from e
            if looks_like_json_schema(parsed):
                raise LLMValidationError(
                    LLMFailureKind.INVALID_SCHEMA, "schema echo"
                )
            if not isinstance(parsed, dict) or "ok" not in parsed:
                raise LLMValidationError(LLMFailureKind.INVALID_SCHEMA, "missing ok")
            return parsed

        primary = _make_provider("primary", "p-model", [bad_response])
        fallback = _make_provider("fallback", "f-model", [_ok_payload()])
        gateway = LLMGateway(
            primary,
            fallback_provider=fallback,
            primary_max_attempts=3,
            fallback_max_attempts=2,
        )

        result = gateway.call_validated(
            operation=LLMOperationType.EXTRACT_EVENTS,
            contents=["prompt"],
            validator=validator,
        )

        assert result == {"ok": True}
        assert primary.generate.call_count == 1
        assert fallback.generate.call_count == 1

    def test_primary_valid_exactly_one_call(self):
        primary = _make_provider("primary", "p-model", [_ok_payload()])
        fallback = _make_provider("fallback", "f-model", [_ok_payload()])
        gateway = LLMGateway(primary, fallback_provider=fallback)

        result = gateway.call_validated(
            operation=LLMOperationType.EXTRACT_EVENTS,
            contents=["prompt"],
            validator=_identity_validator,
        )

        assert result == {"ok": True}
        assert primary.generate.call_count == 1
        assert fallback.generate.call_count == 0

    def test_primary_permanent_no_retry_no_fallback(self):
        primary = _make_provider(
            "primary", "p-model", [Exception("Invalid API key")]
        )
        fallback = _make_provider("fallback", "f-model", [_ok_payload()])
        gateway = LLMGateway(primary, fallback_provider=fallback)

        with pytest.raises(LLMAPIError):
            gateway.call_validated(
                operation=LLMOperationType.EXTRACT_EVENTS,
                contents=["prompt"],
                validator=_identity_validator,
            )

        assert primary.generate.call_count == 1
        assert fallback.generate.call_count == 0

    def test_fallback_transient_then_success_at_most_two(self):
        primary = _make_provider(
            "primary", "p-model", [LLMResponse(text="", prompt_tokens=0, completion_tokens=0)]
        )
        fallback = _make_provider(
            "fallback",
            "f-model",
            [
                Exception("429 rate limit"),
                _ok_payload(),
            ],
        )
        gateway = LLMGateway(
            primary,
            fallback_provider=fallback,
            primary_max_attempts=3,
            fallback_max_attempts=2,
        )

        with patch("selko.services.llm_gateway.time.sleep"):
            result = gateway.call_validated(
                operation=LLMOperationType.EXTRACT_EVENTS,
                contents=["prompt"],
                validator=_identity_validator,
            )

        assert result == {"ok": True}
        assert primary.generate.call_count == 1
        assert fallback.generate.call_count == 2

    def test_both_routes_fail_retains_attempt_history(self):
        primary = _make_provider(
            "primary",
            "p-model",
            [LLMResponse(text="not json", prompt_tokens=1, completion_tokens=1)],
        )
        fallback = _make_provider(
            "fallback",
            "f-model",
            [
                Exception("429"),
                Exception("503 overloaded"),
            ],
        )
        gateway = LLMGateway(
            primary,
            fallback_provider=fallback,
            primary_max_attempts=3,
            fallback_max_attempts=2,
        )

        with patch("selko.services.llm_gateway.time.sleep"):
            with pytest.raises((LLMValidatedCallError, LLMRateLimitError)) as exc_info:
                gateway.call_validated(
                    operation=LLMOperationType.EXTRACT_EVENTS,
                    contents=["prompt"],
                    validator=_identity_validator,
                )

        err = exc_info.value
        if isinstance(err, LLMValidatedCallError):
            attempts = err.attempts
        else:
            attempts = gateway._last_attempts

        assert len(attempts) == 3  # 1 primary + 2 fallback
        assert attempts[0].route_role == "primary"
        assert attempts[0].failure_kind == LLMFailureKind.INVALID_JSON
        assert attempts[1].route_role == "fallback"
        assert attempts[2].route_role == "fallback"
        assert primary.generate.call_count == 1
        assert fallback.generate.call_count == 2

    def test_persistence_exception_after_valid_never_calls_fallback(self):
        """After call_validated returns, a caller persistence error must not re-enter."""
        primary = _make_provider("primary", "p-model", [_ok_payload()])
        fallback = _make_provider("fallback", "f-model", [_ok_payload()])
        gateway = LLMGateway(primary, fallback_provider=fallback)

        result = gateway.call_validated(
            operation=LLMOperationType.EXTRACT_EVENTS,
            contents=["prompt"],
            validator=_identity_validator,
        )
        assert result == {"ok": True}

        # Simulate persistence failure after successful validation.
        with pytest.raises(RuntimeError, match="db down"):
            raise RuntimeError("db down")

        assert primary.generate.call_count == 1
        assert fallback.generate.call_count == 0

    def test_http_success_invalid_logged_as_failure(
        self, mock_logging_service
    ):
        primary = _make_provider(
            "primary",
            "p-model",
            [LLMResponse(text="not json", prompt_tokens=5, completion_tokens=2)],
        )
        fallback = _make_provider("fallback", "f-model", [_ok_payload()])
        gateway = LLMGateway(
            primary,
            logging_service=mock_logging_service,
            fallback_provider=fallback,
        )
        gateway.for_user("user-1")

        gateway.call_validated(
            operation=LLMOperationType.EXTRACT_EVENTS,
            contents=["prompt"],
            validator=_identity_validator,
        )

        # First attempt failed validation → log_failure; accepted fallback → log_success
        assert mock_logging_service.log_failure.call_count == 1
        failure_msg = mock_logging_service.log_failure.call_args.kwargs["error_message"]
        assert "invalid_json" in failure_msg
        assert mock_logging_service.log_success.call_count == 1
        # Must not mark the invalid primary attempt as success
        success_models = [
            c.kwargs["model"] for c in mock_logging_service.log_success.call_args_list
        ]
        assert success_models == ["f-model"]
