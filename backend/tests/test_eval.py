"""Unit tests for eval helper functions."""

import json
import tempfile
from pathlib import Path

import pytest


class TestFixtureHash:
    """Test fixture hashing for idempotent caching."""

    def test_hash_deterministic(self, tmp_path):
        """Same content should produce the same hash."""
        from tests.eval.run_eval import get_fixture_hash

        fixture = tmp_path / "test.json"
        fixture.write_text('{"key": "value"}')
        h1 = get_fixture_hash(fixture)
        h2 = get_fixture_hash(fixture)
        assert h1 == h2

    def test_different_content_different_hash(self, tmp_path):
        """Different content should produce different hashes."""
        from tests.eval.run_eval import get_fixture_hash

        f1 = tmp_path / "test1.json"
        f2 = tmp_path / "test2.json"
        f1.write_text('{"key": "value1"}')
        f2.write_text('{"key": "value2"}')
        assert get_fixture_hash(f1) != get_fixture_hash(f2)


class TestCodeHash:
    """Test code hashing for detecting production code changes."""

    def test_code_hash_returns_string(self):
        from tests.eval.run_eval import get_code_hash

        h = get_code_hash()
        assert isinstance(h, str)
        assert len(h) == 12 or h == "unknown"


class TestCostEstimation:
    """Test cost estimation from MODEL_REGISTRY pricing."""

    def test_gemini_cost(self):
        from tests.eval.run_eval import estimate_cost

        # gemini-3-flash-preview: input=$0.15/1M, output=$0.60/1M
        cost = estimate_cost("gemini-3-flash-preview", 1000, 500)
        expected = (1000 * 0.15 + 500 * 0.60) / 1_000_000
        assert abs(cost - expected) < 1e-10

    def test_deepseek_cost(self):
        from tests.eval.run_eval import estimate_cost

        # deepseek-chat: input=$0.27/1M, output=$1.10/1M
        cost = estimate_cost("deepseek-chat", 2000, 1000)
        expected = (2000 * 0.27 + 1000 * 1.10) / 1_000_000
        assert abs(cost - expected) < 1e-10

    def test_free_model_returns_zero(self):
        from tests.eval.run_eval import estimate_cost

        # glm-4.6v-flash: $0.00/$0.00
        cost = estimate_cost("glm-4.6v-flash", 5000, 2000)
        assert cost == 0.0

    def test_unknown_model_returns_zero(self):
        from tests.eval.run_eval import estimate_cost

        cost = estimate_cost("nonexistent-model", 1000, 500)
        assert cost == 0.0

    def test_none_tokens_returns_zero(self):
        from tests.eval.run_eval import estimate_cost

        cost = estimate_cost("gemini-3-flash-preview", None, None)
        assert cost == 0.0

    def test_partial_none_tokens_returns_zero(self):
        from tests.eval.run_eval import estimate_cost

        cost = estimate_cost("gemini-3-flash-preview", 1000, None)
        assert cost == 0.0


class TestCompareScoring:
    """Test compare (dedup) scoring."""

    def test_correct_match_is_pass(self):
        from tests.eval.run_eval import score_compare_result

        expected = {"matched_event_id": "event-001"}
        score = score_compare_result(expected, "event-001")
        assert score["correct"] is True

    def test_wrong_match_is_fail(self):
        from tests.eval.run_eval import score_compare_result

        expected = {"matched_event_id": "event-001"}
        score = score_compare_result(expected, "event-002")
        assert score["correct"] is False

    def test_correct_no_match_is_pass(self):
        from tests.eval.run_eval import score_compare_result

        expected = {"matched_event_id": None}
        score = score_compare_result(expected, None)
        assert score["correct"] is True

    def test_false_positive_is_fail(self):
        from tests.eval.run_eval import score_compare_result

        expected = {"matched_event_id": None}
        score = score_compare_result(expected, "event-001")
        assert score["correct"] is False

    def test_missed_match_is_fail(self):
        from tests.eval.run_eval import score_compare_result

        expected = {"matched_event_id": "event-001"}
        score = score_compare_result(expected, None)
        assert score["correct"] is False


class TestMergeScoring:
    """Test merge scoring logic."""

    def test_perfect_merge_score_5(self):
        from tests.eval.run_eval import score_merge_result

        expected = {
            "title": "Project Kickoff Meeting",
            "start_datetime": "2026-03-20T14:00:00",
            "end_datetime": "2026-03-20T15:30:00",
            "all_day": False,
            "location": "Conference Room B, 2nd Floor",
            "description_contains": ["planning", "laptops"],
        }
        actual = {
            "title": "Project Kickoff Meeting",
            "start_datetime": "2026-03-20T14:00:00",
            "end_datetime": "2026-03-20T15:30:00",
            "all_day": False,
            "location": "Conference Room B, 2nd Floor",
            "description": "Rescheduled planning meeting. Please bring laptops.",
        }
        score = score_merge_result(expected, actual)
        assert score["auto_rating"] == 5
        assert score["fields_matched"] == score["total_fields"]

    def test_partial_merge_scored_correctly(self):
        from tests.eval.run_eval import score_merge_result

        expected = {
            "title": "Team Meeting",
            "start_datetime": "2026-03-20T14:00:00",
            "end_datetime": "2026-03-20T15:00:00",
            "location": "Room A",
        }
        actual = {
            "title": "Team Meeting",
            "start_datetime": "2026-03-20T14:00:00",
            "end_datetime": "2026-03-20T16:00:00",  # Wrong end time
            "location": "Completely Different Place",  # Wrong location
        }
        score = score_merge_result(expected, actual)
        # Title matches, start matches, end wrong, location wrong
        assert score["auto_rating"] < 5
        assert score["title"]["match"] is True
        assert score["start_datetime"]["match"] is True
        assert score["end_datetime"]["match"] is False
        assert score["location"]["match"] is False

    def test_description_contains_check(self):
        from tests.eval.run_eval import score_merge_result

        expected = {
            "title": "Meeting",
            "start_datetime": "2026-03-20T14:00:00",
            "end_datetime": "2026-03-20T15:00:00",
            "description_contains": ["agenda", "parking"],
        }
        actual = {
            "title": "Meeting",
            "start_datetime": "2026-03-20T14:00:00",
            "end_datetime": "2026-03-20T15:00:00",
            "description": "Meeting with updated agenda. Free parking available.",
        }
        score = score_merge_result(expected, actual)
        assert score["description_contains"]["match"] is True
        assert score["description_contains"]["missing"] == []

    def test_description_contains_partial_failure(self):
        from tests.eval.run_eval import score_merge_result

        expected = {
            "title": "Meeting",
            "start_datetime": "2026-03-20T14:00:00",
            "end_datetime": "2026-03-20T15:00:00",
            "description_contains": ["agenda", "parking", "dress code"],
        }
        actual = {
            "title": "Meeting",
            "start_datetime": "2026-03-20T14:00:00",
            "end_datetime": "2026-03-20T15:00:00",
            "description": "Updated agenda for the meeting.",
        }
        score = score_merge_result(expected, actual)
        assert score["description_contains"]["match"] is False
        assert "parking" in score["description_contains"]["missing"]
        assert "dress code" in score["description_contains"]["missing"]

    def test_cancellation_prefix_check(self):
        from tests.eval.run_eval import score_merge_result

        expected = {
            "title": "CANCELLED: Team Meeting",
            "start_datetime": "2026-03-20T14:00:00",
            "end_datetime": "2026-03-20T15:00:00",
        }
        actual = {
            "title": "CANCELLED: Team Meeting",
            "start_datetime": "2026-03-20T14:00:00",
            "end_datetime": "2026-03-20T15:00:00",
        }
        score = score_merge_result(expected, actual)
        assert score["cancellation_prefix"] is True

    def test_missing_cancellation_prefix(self):
        from tests.eval.run_eval import score_merge_result

        expected = {
            "title": "CANCELLED: Team Meeting",
            "start_datetime": "2026-03-20T14:00:00",
            "end_datetime": "2026-03-20T15:00:00",
        }
        actual = {
            "title": "Team Meeting",  # Missing CANCELLED prefix
            "start_datetime": "2026-03-20T14:00:00",
            "end_datetime": "2026-03-20T15:00:00",
        }
        score = score_merge_result(expected, actual)
        assert score["cancellation_prefix"] is False


class TestStringHelpers:
    """Test string similarity and time difference helpers."""

    def test_string_similarity_identical(self):
        from tests.eval.run_eval import string_similarity

        assert string_similarity("hello world", "hello world") == 1.0

    def test_string_similarity_case_insensitive(self):
        from tests.eval.run_eval import string_similarity

        assert string_similarity("Hello World", "hello world") == 1.0

    def test_string_similarity_both_none(self):
        from tests.eval.run_eval import string_similarity

        assert string_similarity(None, None) == 1.0

    def test_string_similarity_one_none(self):
        from tests.eval.run_eval import string_similarity

        assert string_similarity("hello", None) == 0.0

    def test_time_difference_exact(self):
        from tests.eval.run_eval import time_difference_minutes

        diff = time_difference_minutes("2026-03-20T14:00:00", "2026-03-20T14:00:00")
        assert diff == 0.0

    def test_time_difference_30min(self):
        from tests.eval.run_eval import time_difference_minutes

        diff = time_difference_minutes("2026-03-20T14:00:00", "2026-03-20T14:30:00")
        assert diff == 30.0

    def test_time_difference_none_input(self):
        from tests.eval.run_eval import time_difference_minutes

        assert time_difference_minutes(None, "2026-03-20T14:00:00") is None


class TestResultPath:
    """Test result path generation."""

    def test_result_path_format(self):
        from tests.eval.run_eval import get_result_path

        path = get_result_path("extract", "gemini", "gemini-3-flash-preview", "invitations/birthday_01", "abc123")
        assert "extract" in str(path)
        assert "gemini_gemini-3-flash-preview" in str(path)
        assert "invitations_birthday_01" in str(path)
        assert "result_abc123.json" in str(path)

    def test_result_path_safe_name(self):
        from tests.eval.run_eval import get_result_path

        path = get_result_path("compare", "zai", "glm-4.6v-flash", "some/nested/name", "def456")
        # Slashes in fixture_name should become underscores
        assert "some_nested_name" in str(path)


class TestFixtureHasImages:
    """Test vision requirement detection."""

    def test_fixture_with_images(self):
        from tests.eval.run_eval import fixture_has_images

        fixture = {"input": {"attachments": ["image1.png", "doc.txt"]}}
        assert fixture_has_images(fixture) is True

    def test_fixture_without_images(self):
        from tests.eval.run_eval import fixture_has_images

        fixture = {"input": {"attachments": ["doc.txt", "data.csv"]}}
        assert fixture_has_images(fixture) is False

    def test_fixture_no_attachments(self):
        from tests.eval.run_eval import fixture_has_images

        fixture = {"input": {"body_text": "hello"}}
        assert fixture_has_images(fixture) is False

    def test_fixture_jpg_attachment(self):
        from tests.eval.run_eval import fixture_has_images

        fixture = {"input": {"attachments": ["photo.jpg"]}}
        assert fixture_has_images(fixture) is True
