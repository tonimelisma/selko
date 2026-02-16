"""Tests for standardized API error response helpers."""

import pytest

from selko.api.schemas.common import ErrorCode, error_detail


class TestErrorDetail:
    """Tests for the error_detail() helper function."""

    def test_returns_dict_with_error_and_detail(self):
        """error_detail returns a dict with 'error' and 'detail' keys."""
        result = error_detail("SOME_CODE", "Something went wrong")
        assert result == {"error": "SOME_CODE", "detail": "Something went wrong"}

    def test_keys_are_error_and_detail(self):
        """Returned dict has exactly two keys: 'error' and 'detail'."""
        result = error_detail("CODE", "msg")
        assert set(result.keys()) == {"error", "detail"}

    def test_preserves_code_exactly(self):
        """The code value is stored unchanged."""
        result = error_detail(ErrorCode.EMAIL_NOT_FOUND, "not found")
        assert result["error"] == "EMAIL_NOT_FOUND"

    def test_preserves_message_exactly(self):
        """The message value is stored unchanged."""
        msg = "Email not found in database"
        result = error_detail(ErrorCode.EMAIL_NOT_FOUND, msg)
        assert result["detail"] == msg

    def test_with_empty_message(self):
        """Works with an empty message string."""
        result = error_detail(ErrorCode.NOT_FOUND, "")
        assert result == {"error": "NOT_FOUND", "detail": ""}


class TestErrorCodeConstants:
    """Tests for ErrorCode class constants."""

    def test_all_constants_are_strings(self):
        """Every public constant on ErrorCode is a string."""
        for attr_name in dir(ErrorCode):
            if attr_name.startswith("_"):
                continue
            value = getattr(ErrorCode, attr_name)
            assert isinstance(value, str), f"ErrorCode.{attr_name} is not a string: {type(value)}"

    def test_all_constants_are_uppercase(self):
        """Every constant value is UPPER_SNAKE_CASE."""
        for attr_name in dir(ErrorCode):
            if attr_name.startswith("_"):
                continue
            value = getattr(ErrorCode, attr_name)
            assert value == value.upper(), f"ErrorCode.{attr_name} = {value!r} is not uppercase"

    def test_expected_codes_exist(self):
        """All expected error codes are defined."""
        expected = [
            "UNAUTHORIZED",
            "FORBIDDEN",
            "NOT_FOUND",
            "EMAIL_NOT_FOUND",
            "EVENT_NOT_FOUND",
            "CALENDAR_NOT_FOUND",
            "CREDENTIALS_EXPIRED",
            "CREDENTIALS_NOT_FOUND",
            "QUOTA_EXCEEDED",
            "DATABASE_ERROR",
            "SYNC_FAILED",
            "GMAIL_API_ERROR",
            "INVALID_REQUEST",
            "PROCESSING_FAILED",
            "OAUTH_FAILED",
            "SERVER_ERROR",
        ]
        for code_name in expected:
            assert hasattr(ErrorCode, code_name), f"ErrorCode.{code_name} is missing"
            assert getattr(ErrorCode, code_name) == code_name

    def test_constant_name_matches_value(self):
        """Each constant's attribute name matches its string value."""
        for attr_name in dir(ErrorCode):
            if attr_name.startswith("_"):
                continue
            value = getattr(ErrorCode, attr_name)
            assert attr_name == value, (
                f"ErrorCode.{attr_name} = {value!r} — name and value should match"
            )


class TestErrorDetailIntegration:
    """Tests verifying error_detail works with ErrorCode constants."""

    @pytest.mark.parametrize(
        "code_attr",
        [
            "UNAUTHORIZED",
            "FORBIDDEN",
            "EMAIL_NOT_FOUND",
            "EVENT_NOT_FOUND",
            "QUOTA_EXCEEDED",
            "DATABASE_ERROR",
            "SYNC_FAILED",
            "PROCESSING_FAILED",
        ],
    )
    def test_error_detail_with_various_codes(self, code_attr: str):
        """error_detail works correctly with each ErrorCode constant."""
        code = getattr(ErrorCode, code_attr)
        result = error_detail(code, "test message")
        assert result["error"] == code_attr
        assert result["detail"] == "test message"
