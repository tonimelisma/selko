"""Tests for LLM-based calendar event extraction."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from datetime import datetime, timezone

from selko.api.schemas.calendar import CalendarEvent, CalendarEventExtraction, EventExtractionResponse
from selko.config import Config
from selko.services.event_processing import (
    _build_prompt,
    compare_events,
    extract_calendar_events,
    generate_source_attribution,
    looks_like_json_schema,
    merge_event_data,
)
from selko.services.llm_gateway import LLMGatewayError
from selko.services.llm_gateway import LLMGateway, LLMGatewayError, LLMRateLimitError
from selko.services.llm_provider import LLMProvider, LLMResponse


@pytest.fixture
def mock_config():
    """Create a mock Config with Gemini API key."""
    return Config(
        environment="development",
        supabase_url="http://localhost:54321",
        supabase_key="test-key",
        gemini_api_key="test-gemini-key",
    )


@pytest.fixture
def fixtures_dir():
    """Get the path to test fixtures directory."""
    return Path(__file__).parent / "fixtures" / "emails"


def load_fixture(fixtures_dir: Path, fixture_name: str) -> dict:
    """Load a test fixture JSON file."""
    if not fixture_name.endswith(".json"):
        fixture_name += ".json"

    fixture_path = fixtures_dir / fixture_name
    with open(fixture_path) as f:
        return json.load(f)


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
def mock_gateway(mock_provider):
    """Create a mock LLMGateway with mock provider."""
    gateway = LLMGateway(mock_provider)
    return gateway


class TestT24DatetimeSanitization:
    """Regression tests for T24:XX:XX datetime handling (Qwen LLM output)."""

    def test_t24_converts_to_next_day_midnight(self):
        """T24:00:00Z should become next day T00:00:00Z."""
        event = CalendarEvent(
            title="Test",
            start_datetime="2025-06-15T24:00:00Z",
            description="test",
        )
        assert event.start_datetime == datetime(2025, 6, 16, 0, 0, 0, tzinfo=timezone.utc)

    def test_t24_end_datetime(self):
        """T24:00:00 on end_datetime should also be sanitized."""
        event = CalendarEvent(
            title="Test",
            end_datetime="2025-12-31T24:00:00Z",
            description="test",
        )
        assert event.end_datetime == datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)

    def test_normal_datetime_unchanged(self):
        """Normal datetimes should pass through unmodified."""
        event = CalendarEvent(
            title="Test",
            start_datetime="2025-06-15T09:30:00Z",
            description="test",
        )
        assert event.start_datetime == datetime(2025, 6, 15, 9, 30, 0, tzinfo=timezone.utc)

    def test_none_datetime_unchanged(self):
        """None datetimes should remain None."""
        event = CalendarEvent(title="Test", description="test")
        assert event.start_datetime is None
        assert event.end_datetime is None


class TestExtractCalendarEvents:
    """Test calendar event extraction from emails."""

    def test_prompt_excludes_calendar_derived_digests(self):
        """Calendar recaps of existing entries are not new event sources."""
        prompt = _build_prompt(
            {
                "subject": "Daily Brief",
                "from_name": "Contact Assistant",
                "from_email": "notify@example.com",
                "date_sent": "2026-07-15T14:01:14Z",
            },
            "2026-07-15",
        )

        assert "calendar-derived briefs" in prompt
        assert "already on the recipient's calendar" in prompt
        assert "genuine organizer-issued change" in prompt
        assert "does NOT apply to organizer-sent meeting invitations" in prompt
        assert "attached agendas" in prompt
        assert "briefs, agendas" not in prompt

    @pytest.mark.parametrize(
        "fixture_name,expected_found,expected_count",
        [
            ("event_birthday_party", True, 1),
            ("event_doctor_appointment", True, 1),
            ("event_meeting_request", True, 1),
            ("event_multiple_events", True, 3),
            ("no_event_newsletter", False, 0),
            ("no_event_receipt", False, 0),
        ],
    )
    def test_extraction_from_fixtures(
        self, mock_config, fixtures_dir, fixture_name, expected_found, expected_count
    ):
        """Test event extraction using fixture files."""
        fixture = load_fixture(fixtures_dir, fixture_name)
        input_data = fixture["input"]
        expected_data = fixture["expected"]

        # Build mock Gemini response as JSON
        mock_gemini_response = EventExtractionResponse(
            events_found=expected_data["events_found"],
            events=expected_data["events"],
        )
        response_json = mock_gemini_response.model_dump_json()

        mock_provider = MagicMock(spec=LLMProvider)
        mock_provider.provider_name = "gemini"
        mock_provider.model = "gemini-3-flash-preview"
        mock_provider.generate.return_value = LLMResponse(
            text=response_json, prompt_tokens=100, completion_tokens=50
        )

        gateway = LLMGateway(mock_provider)

        # Extract email metadata
        email_metadata = {
            "provider_message_id": input_data["provider_message_id"],
            "subject": input_data["subject"],
            "from_name": input_data.get("from_name"),
            "from_email": input_data["from_email"],
            "date_sent": input_data["date_sent"],
        }

        # Call extraction
        result = extract_calendar_events(
            gateway=gateway,
            email_text=input_data["body_text"],
            email_metadata=email_metadata,
            attachments=input_data.get("attachments"),
        )

        # Verify results
        assert result.events_found == expected_found
        assert len(result.events) == expected_count
        assert result.sender_email == input_data["from_email"]

        # Verify provider was called
        mock_provider.generate.assert_called_once()

    def test_rate_limit_retry(self, mock_config):
        """Test retry logic on rate limit errors."""
        mock_provider = MagicMock(spec=LLMProvider)
        mock_provider.provider_name = "gemini"
        mock_provider.model = "gemini-3-flash-preview"

        response_json = EventExtractionResponse(
            events_found=False, events=[]
        ).model_dump_json()

        # First call raises rate limit, second succeeds
        mock_provider.generate.side_effect = [
            Exception("429 Rate limit exceeded"),
            LLMResponse(text=response_json, prompt_tokens=10, completion_tokens=5),
        ]

        gateway = LLMGateway(mock_provider)

        email_metadata = {
            "provider_message_id": "test-123",
            "subject": "Test",
            "from_email": "test@example.com",
            "date_sent": "2026-01-20T10:00:00Z",
        }

        # Should succeed after retry
        with patch("selko.services.llm_gateway.time.sleep"):
            result = extract_calendar_events(
                gateway=gateway,
                email_text="Test email",
                email_metadata=email_metadata,
                max_retries=3,
            )

        assert result.events_found is False
        assert mock_provider.generate.call_count == 2

    def test_rate_limit_exhausted(self, mock_config):
        """Test failure after exhausting retries."""
        mock_provider = MagicMock(spec=LLMProvider)
        mock_provider.provider_name = "gemini"
        mock_provider.model = "gemini-3-flash-preview"
        mock_provider.generate.side_effect = Exception("429 Rate limit exceeded")

        gateway = LLMGateway(mock_provider)

        email_metadata = {
            "provider_message_id": "test-123",
            "subject": "Test",
            "from_email": "test@example.com",
            "date_sent": "2026-01-20T10:00:00Z",
        }

        with patch("selko.services.llm_gateway.time.sleep"):
            with pytest.raises(LLMRateLimitError) as exc_info:
                extract_calendar_events(
                    gateway=gateway,
                    email_text="Test email",
                    email_metadata=email_metadata,
                    max_retries=2,
                )

        assert "rate limited" in str(exc_info.value).lower()

    def test_non_rate_limit_error(self, mock_config):
        """Test immediate failure on non-rate-limit errors."""
        mock_provider = MagicMock(spec=LLMProvider)
        mock_provider.provider_name = "gemini"
        mock_provider.model = "gemini-3-flash-preview"
        mock_provider.generate.side_effect = Exception("Invalid API key")

        gateway = LLMGateway(mock_provider)

        email_metadata = {
            "provider_message_id": "test-123",
            "subject": "Test",
            "from_email": "test@example.com",
            "date_sent": "2026-01-20T10:00:00Z",
        }

        with pytest.raises(LLMGatewayError) as exc_info:
            extract_calendar_events(
                gateway=gateway,
                email_text="Test email",
                email_metadata=email_metadata,
            )

        # Should fail immediately, not retry
        assert mock_provider.generate.call_count == 1
        assert "Invalid API key" in str(exc_info.value)

    def test_null_date_sent_allowed(self, mock_config):
        """Null date_sent must not crash — pass through as None, don't invent a date."""
        mock_provider = MagicMock(spec=LLMProvider)
        mock_provider.provider_name = "gemini"
        mock_provider.model = "gemini-3-flash-preview"
        response_json = EventExtractionResponse(
            events_found=False, events=[]
        ).model_dump_json()
        mock_provider.generate.return_value = LLMResponse(
            text=response_json, prompt_tokens=10, completion_tokens=5
        )
        gateway = LLMGateway(mock_provider)

        result = extract_calendar_events(
            gateway=gateway,
            email_text="Test email",
            email_metadata={
                "provider_message_id": "test-123",
                "subject": "Test",
                "from_email": "test@example.com",
                "date_sent": None,
            },
        )

        assert result.events_found is False
        assert result.email_date is None

    def test_schema_echo_raises_clear_error(self, mock_config):
        """Regression: LLM echoing JSON schema must not hit pydantic missing fields."""
        mock_provider = MagicMock(spec=LLMProvider)
        mock_provider.provider_name = "gemini"
        mock_provider.model = "gemini-3-flash-preview"
        schema_echo = EventExtractionResponse.model_json_schema()
        mock_provider.generate.return_value = LLMResponse(
            text=json.dumps(schema_echo), prompt_tokens=10, completion_tokens=5
        )
        gateway = LLMGateway(mock_provider)

        with pytest.raises(LLMGatewayError, match="JSON schema instead of extraction"):
            extract_calendar_events(
                gateway=gateway,
                email_text="Test email",
                email_metadata={
                    "provider_message_id": "test-123",
                    "subject": "Test",
                    "from_email": "test@example.com",
                    "date_sent": "2026-01-20T10:00:00Z",
                },
            )

    def test_attachment_handling(self, mock_config):
        """Test that attachments are properly added to request."""
        mock_provider = MagicMock(spec=LLMProvider)
        mock_provider.provider_name = "gemini"
        mock_provider.model = "gemini-3-flash-preview"

        response_json = EventExtractionResponse(
            events_found=True, events=[]
        ).model_dump_json()
        mock_provider.generate.return_value = LLMResponse(
            text=response_json, prompt_tokens=10, completion_tokens=5
        )

        gateway = LLMGateway(mock_provider)

        email_metadata = {
            "provider_message_id": "test-123",
            "subject": "Test with attachment",
            "from_email": "test@example.com",
            "date_sent": "2026-01-20T10:00:00Z",
        }

        attachments = [
            {
                "data": b"fake image data",
                "mime_type": "image/jpeg",
                "filename": "invite.jpg",
            }
        ]

        result = extract_calendar_events(
            gateway=gateway,
            email_text="See attached invitation",
            email_metadata=email_metadata,
            attachments=attachments,
        )

        assert result.events_found is True
        mock_provider.generate.assert_called_once()

        # Verify contents include attachment
        call_args = mock_provider.generate.call_args
        contents = call_args.kwargs["contents"]
        assert len(contents) > 2  # prompt + email body + attachment

    def test_oversized_attachment_skipped(self, mock_config):
        """Test that oversized attachments are skipped."""
        mock_provider = MagicMock(spec=LLMProvider)
        mock_provider.provider_name = "gemini"
        mock_provider.model = "gemini-3-flash-preview"

        response_json = EventExtractionResponse(
            events_found=False, events=[]
        ).model_dump_json()
        mock_provider.generate.return_value = LLMResponse(
            text=response_json, prompt_tokens=10, completion_tokens=5
        )

        gateway = LLMGateway(mock_provider)

        email_metadata = {
            "provider_message_id": "test-123",
            "subject": "Test with large attachment",
            "from_email": "test@example.com",
            "date_sent": "2026-01-20T10:00:00Z",
        }

        # 25MB attachment (over 20MB limit)
        large_data = b"x" * (25 * 1024 * 1024)
        attachments = [
            {
                "data": large_data,
                "mime_type": "application/pdf",
                "filename": "large.pdf",
            }
        ]

        result = extract_calendar_events(
            gateway=gateway,
            email_text="See attached document",
            email_metadata=email_metadata,
            attachments=attachments,
        )

        assert result.events_found is False

        # Verify contents don't include the oversized attachment
        call_args = mock_provider.generate.call_args
        contents = call_args.kwargs["contents"]
        assert len(contents) == 2  # Only prompt + email body


class TestLooksLikeJsonSchema:
    """Detect LLM schema-echo responses."""

    def test_detects_defs(self):
        assert looks_like_json_schema({"$defs": {"CalendarEvent": {}}, "type": "object"})

    def test_detects_properties_without_events(self):
        assert looks_like_json_schema(
            {"type": "object", "properties": {"events_found": {"type": "boolean"}}}
        )

    def test_accepts_real_extraction(self):
        assert not looks_like_json_schema({"events_found": False, "events": []})


class TestCompareEvents:
    """Test event comparison for deduplication."""

    def test_returns_none_when_no_candidates(self, mock_provider):
        """Test that empty candidate list returns None."""
        gateway = LLMGateway(mock_provider)

        new_event = {
            "title": "Birthday Party",
            "start_datetime": "2026-03-15T14:00:00Z",
            "location": "123 Main St",
        }

        result = compare_events(gateway, new_event, [])

        assert result is None
        mock_provider.generate.assert_not_called()

    def test_returns_matched_event_id(self, mock_provider):
        """Test that matching event ID is returned."""
        mock_provider.generate.return_value = LLMResponse(
            text=json.dumps({"matched_event_id": "event-123", "reasoning": "Same birthday party"}),
            prompt_tokens=10, completion_tokens=5
        )

        gateway = LLMGateway(mock_provider)

        new_event = {
            "title": "Jake's Birthday Party",
            "start_datetime": "2026-03-15T14:00:00Z",
            "end_datetime": "2026-03-15T16:00:00Z",
            "location": "123 Main St",
            "description": "Come celebrate!",
        }

        candidates = [{
            "id": "event-123",
            "title": "Birthday Party",
            "start_datetime": "2026-03-15T14:00:00Z",
            "end_datetime": "2026-03-15T16:00:00Z",
            "location": "123 Main St",
            "description": "Party time!",
        }]

        result = compare_events(gateway, new_event, candidates)

        assert result == "event-123"
        mock_provider.generate.assert_called_once()

    def test_returns_none_for_no_match(self, mock_provider):
        """Test that null matched_event_id returns None."""
        mock_provider.generate.return_value = LLMResponse(
            text=json.dumps({"matched_event_id": None, "reasoning": "Different events"}),
            prompt_tokens=10, completion_tokens=5
        )

        gateway = LLMGateway(mock_provider)

        new_event = {
            "title": "Doctor Appointment",
            "start_datetime": "2026-03-15T09:00:00Z",
        }

        candidates = [{
            "id": "event-456",
            "title": "Dentist Appointment",
            "start_datetime": "2026-03-15T14:00:00Z",
        }]

        result = compare_events(gateway, new_event, candidates)

        assert result is None

    def test_returns_none_for_unknown_event_id(self, mock_provider):
        """Test that unknown event ID from LLM returns None."""
        mock_provider.generate.return_value = LLMResponse(
            text=json.dumps({"matched_event_id": "unknown-event-999", "reasoning": "Seems similar"}),
            prompt_tokens=10, completion_tokens=5
        )

        gateway = LLMGateway(mock_provider)

        new_event = {
            "title": "Test Event",
            "start_datetime": "2026-03-15T14:00:00Z",
        }

        candidates = [{
            "id": "event-123",
            "title": "Test",
            "start_datetime": "2026-03-15T14:00:00Z",
        }]

        result = compare_events(gateway, new_event, candidates)

        assert result is None

    def test_raises_error_on_llm_failure(self, mock_provider):
        """Test that LLM failure raises LLMGatewayError."""
        mock_provider.generate.side_effect = Exception("API Error")

        gateway = LLMGateway(mock_provider)

        new_event = {"title": "Test", "start_datetime": "2026-03-15T14:00:00Z"}
        candidates = [{"id": "event-1", "title": "Test", "start_datetime": "2026-03-15T14:00:00Z"}]

        with pytest.raises(LLMGatewayError) as exc_info:
            compare_events(gateway, new_event, candidates)

        assert "api error" in str(exc_info.value).lower()


class TestMergeEventData:
    """Test event data merging."""

    def test_merges_event_data(self, mock_provider):
        """Test that event data is properly merged."""
        mock_provider.generate.return_value = LLMResponse(
            text=json.dumps({
                "title": "Updated Meeting",
                "start_datetime": "2026-03-15T15:00:00Z",
                "end_datetime": "2026-03-15T16:00:00Z",
                "all_day": False,
                "location": "Conference Room B",
                "description": "Original info. Updated: new agenda.",
            }),
            prompt_tokens=10,
            completion_tokens=20,
        )

        gateway = LLMGateway(mock_provider)

        existing_event = {
            "title": "Team Meeting",
            "start_datetime": "2026-03-15T14:00:00Z",
            "end_datetime": "2026-03-15T15:00:00Z",
            "all_day": False,
            "location": "Conference Room A",
            "description": "Original info.",
        }

        new_extraction = {
            "title": "Updated Meeting",
            "start_datetime": "2026-03-15T15:00:00Z",
            "end_datetime": "2026-03-15T16:00:00Z",
            "all_day": False,
            "location": "Conference Room B",
            "description": "new agenda",
        }

        result = merge_event_data(gateway, existing_event, new_extraction, "update")

        assert result["title"] == "Updated Meeting"
        assert result["start_datetime"] == "2026-03-15T15:00:00Z"
        assert result["location"] == "Conference Room B"
        mock_provider.generate.assert_called_once()

    def test_handles_cancellation_source_type(self, mock_provider):
        """Test that cancellation source type triggers CANCELLED prefix."""
        mock_provider.generate.return_value = LLMResponse(
            text=json.dumps({
                "title": "CANCELLED: Team Meeting",
                "start_datetime": "2026-03-15T14:00:00Z",
                "end_datetime": "2026-03-15T15:00:00Z",
                "all_day": False,
                "location": "Conference Room A",
                "description": "Event has been cancelled.",
            }),
            prompt_tokens=10,
            completion_tokens=20,
        )

        gateway = LLMGateway(mock_provider)

        existing_event = {
            "title": "Team Meeting",
            "start_datetime": "2026-03-15T14:00:00Z",
            "end_datetime": "2026-03-15T15:00:00Z",
            "all_day": False,
            "location": "Conference Room A",
            "description": "Weekly sync.",
        }

        new_extraction = {
            "title": "Meeting Cancelled",
            "start_datetime": "2026-03-15T14:00:00Z",
        }

        result = merge_event_data(gateway, existing_event, new_extraction, "cancellation")

        assert "CANCELLED" in result["title"]

    def test_raises_error_on_llm_failure(self, mock_provider):
        """Test that LLM failure raises LLMGatewayError."""
        mock_provider.generate.side_effect = Exception("API Error")

        gateway = LLMGateway(mock_provider)

        existing_event = {"title": "Test", "start_datetime": "2026-03-15T14:00:00Z"}
        new_extraction = {"title": "Test Updated", "start_datetime": "2026-03-15T15:00:00Z"}

        with pytest.raises(LLMGatewayError) as exc_info:
            merge_event_data(gateway, existing_event, new_extraction, "update")

        assert "api error" in str(exc_info.value).lower()

    def test_raises_error_on_invalid_json(self, mock_provider):
        """Test that invalid JSON response raises LLMGatewayError."""
        mock_provider.generate.return_value = LLMResponse(
            text="not valid json", prompt_tokens=10, completion_tokens=5
        )

        gateway = LLMGateway(mock_provider)

        existing_event = {"title": "Test", "start_datetime": "2026-03-15T14:00:00Z"}
        new_extraction = {"title": "Test Updated", "start_datetime": "2026-03-15T15:00:00Z"}

        with pytest.raises(LLMGatewayError):
            merge_event_data(gateway, existing_event, new_extraction, "update")


class TestGenerateSourceAttribution:
    """Test source attribution generation."""

    def test_empty_sources_returns_empty_string(self):
        """Test that empty sources list returns empty string."""
        result = generate_source_attribution([])

        assert result == ""

    def test_single_invitation_source(self):
        """Test attribution for single invitation source."""
        sources = [{
            "source_type": "new_invitation",
            "email_sender": "organizer@example.com",
            "email_sender_name": "Event Organizer",
            "email_date": "2026-01-25T13:30:00Z",
            "created_at": "2026-01-25T13:35:00Z",
            "is_undone": False,
        }]

        result = generate_source_attribution(sources)

        assert "Event Organizer" in result
        assert "January" in result or "Jan" in result
        assert "automatically created" in result

    def test_invitation_with_updates(self):
        """Test attribution for invitation with subsequent updates."""
        sources = [
            {
                "source_type": "new_invitation",
                "email_sender": "organizer@example.com",
                "email_sender_name": "Event Organizer",
                "email_date": "2026-01-25T13:30:00Z",
                "created_at": "2026-01-25T13:35:00Z",
                "is_undone": False,
            },
            {
                "source_type": "update",
                "email_sender": "organizer@example.com",
                "email_sender_name": "Event Organizer",
                "email_date": "2026-01-26T10:00:00Z",
                "created_at": "2026-01-26T10:05:00Z",
                "is_undone": False,
            },
        ]

        result = generate_source_attribution(sources)

        assert "automatically created" in result
        assert "updated" in result

    def test_skips_undone_sources(self):
        """Test that undone sources are excluded."""
        sources = [
            {
                "source_type": "new_invitation",
                "email_sender": "old@example.com",
                "email_sender_name": "Old Sender",
                "email_date": "2026-01-20T10:00:00Z",
                "created_at": "2026-01-20T10:05:00Z",
                "is_undone": True,
            },
            {
                "source_type": "new_invitation",
                "email_sender": "active@example.com",
                "email_sender_name": "Active Sender",
                "email_date": "2026-01-25T13:30:00Z",
                "created_at": "2026-01-25T13:35:00Z",
                "is_undone": False,
            },
        ]

        result = generate_source_attribution(sources)

        assert "Active Sender" in result
        assert "Old Sender" not in result

    def test_uses_email_address_when_no_name(self):
        """Test that email address is used when sender name is missing."""
        sources = [{
            "source_type": "new_invitation",
            "email_sender": "noreply@service.com",
            "email_sender_name": None,
            "email_date": "2026-01-25T13:30:00Z",
            "created_at": "2026-01-25T13:35:00Z",
            "is_undone": False,
        }]

        result = generate_source_attribution(sources)

        assert "noreply@service.com" in result

    def test_returns_empty_when_only_undone_sources(self):
        """Test that empty string is returned when all sources are undone."""
        sources = [{
            "source_type": "new_invitation",
            "email_sender": "test@example.com",
            "email_sender_name": "Test",
            "email_date": "2026-01-25T13:30:00Z",
            "created_at": "2026-01-25T13:35:00Z",
            "is_undone": True,
        }]

        result = generate_source_attribution(sources)

        assert result == ""


class TestBuildContentPartsPerTypeLimits:
    """Test per-type attachment size limits in _build_content_parts."""

    def test_pdf_uses_page_limit_not_byte_limit(self):
        """PDFs use page-based limits, so large PDFs pass byte-size check."""
        from selko.services.event_processing import _build_content_parts

        config = Config(
            environment="development",
            supabase_url="http://localhost:54321",
            supabase_key="test-key",
        )

        attachments = [{
            "data": b"x" * (6 * 1024 * 1024),
            "mime_type": "application/pdf",
            "filename": "large.pdf",
        }]

        # PDF is included because byte-size limit is effectively unlimited;
        # page-based limits are applied later in format_conversion
        parts = _build_content_parts("prompt", "email body", attachments, config=config)

        assert len(parts) == 3

    def test_image_limit_skips_oversized(self):
        """Test that an 11MB image is skipped with 10MB limit."""
        from selko.services.event_processing import _build_content_parts

        config = Config(
            environment="development",
            supabase_url="http://localhost:54321",
            supabase_key="test-key",
            max_image_size_for_llm=10 * 1024 * 1024,
        )

        attachments = [{
            "data": b"x" * (11 * 1024 * 1024),
            "mime_type": "image/jpeg",
            "filename": "large.jpg",
        }]

        parts = _build_content_parts("prompt", "email body", attachments, config=config)

        assert len(parts) == 2

    def test_no_config_fallback_20mb(self):
        """Test that without config, 20MB default is used."""
        from selko.services.event_processing import _build_content_parts

        attachments = [{
            "data": b"x" * (15 * 1024 * 1024),
            "mime_type": "application/pdf",
            "filename": "medium.pdf",
        }]

        parts = _build_content_parts("prompt", "email body", attachments, config=None)

        assert len(parts) == 3

    def test_small_attachment_within_limit(self):
        """Test that small attachments within limit are included."""
        from selko.services.event_processing import _build_content_parts

        config = Config(
            environment="development",
            supabase_url="http://localhost:54321",
            supabase_key="test-key",
        )

        attachments = [{
            "data": b"x" * (1 * 1024 * 1024),
            "mime_type": "application/pdf",
            "filename": "small.pdf",
        }]

        parts = _build_content_parts("prompt", "email body", attachments, config=config)

        assert len(parts) == 3
