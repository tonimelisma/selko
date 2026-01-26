"""Tests for Gemini calendar event extraction."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from selko.api.schemas.calendar import CalendarEventExtraction
from selko.config import Config
from selko.services.gemini import (
    GeminiError,
    extract_calendar_events,
    get_gemini_client,
)


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
    """Load a test fixture JSON file.

    Args:
        fixtures_dir: Path to fixtures directory.
        fixture_name: Name of fixture file (with or without .json extension).

    Returns:
        Parsed fixture data.
    """
    if not fixture_name.endswith(".json"):
        fixture_name += ".json"

    fixture_path = fixtures_dir / fixture_name
    with open(fixture_path) as f:
        return json.load(f)


class TestGetGeminiClient:
    """Test Gemini client initialization."""

    def test_success(self, mock_config):
        """Test successful client initialization."""
        with patch("selko.services.gemini.genai.Client") as mock_client_class:
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

        with pytest.raises(GeminiError) as exc_info:
            get_gemini_client(config)

        assert "GEMINI_API_KEY not configured" in str(exc_info.value)

    def test_client_initialization_failure(self, mock_config):
        """Test error handling when client initialization fails."""
        with patch("selko.services.gemini.genai.Client") as mock_client_class:
            mock_client_class.side_effect = Exception("API connection failed")

            with pytest.raises(GeminiError) as exc_info:
                get_gemini_client(mock_config)

            assert "Failed to initialize Gemini client" in str(exc_info.value)


class TestExtractCalendarEvents:
    """Test calendar event extraction from emails."""

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
        self, fixtures_dir, fixture_name, expected_found, expected_count
    ):
        """Test event extraction using fixture files.

        This test uses mocked Gemini responses based on fixture expected values.
        """
        fixture = load_fixture(fixtures_dir, fixture_name)
        input_data = fixture["input"]
        expected_data = fixture["expected"]

        # Mock Gemini client and response
        mock_client = MagicMock()
        mock_response = MagicMock()

        # Build mock extraction result from expected data
        mock_extraction = CalendarEventExtraction(
            email_message_id=input_data["gmail_id"],
            email_date=input_data["date_sent"],
            sender_name=input_data.get("from_name"),
            sender_email=input_data["from_email"],
            events_found=expected_data["events_found"],
            events=expected_data["events"],
        )
        mock_response.parsed = mock_extraction

        mock_client.models.generate_content.return_value = mock_response

        # Extract email metadata
        email_metadata = {
            "gmail_id": input_data["gmail_id"],
            "subject": input_data["subject"],
            "from_name": input_data.get("from_name"),
            "from_email": input_data["from_email"],
            "date_sent": input_data["date_sent"],
        }

        # Call extraction
        result = extract_calendar_events(
            client=mock_client,
            email_text=input_data["body_text"],
            email_metadata=email_metadata,
            attachments=input_data.get("attachments"),
        )

        # Verify results
        assert result.events_found == expected_found
        assert len(result.events) == expected_count
        assert result.sender_email == input_data["from_email"]

        # Verify Gemini was called
        mock_client.models.generate_content.assert_called_once()

    def test_rate_limit_retry(self):
        """Test retry logic on rate limit errors."""
        mock_client = MagicMock()

        # First call raises rate limit error, second succeeds
        mock_response = MagicMock()
        mock_extraction = CalendarEventExtraction(
            email_message_id="test-123",
            email_date="2026-01-20T10:00:00Z",
            sender_email="test@example.com",
            events_found=False,
            events=[],
        )
        mock_response.parsed = mock_extraction

        mock_client.models.generate_content.side_effect = [
            Exception("429 Rate limit exceeded"),
            mock_response,
        ]

        email_metadata = {
            "gmail_id": "test-123",
            "subject": "Test",
            "from_email": "test@example.com",
            "date_sent": "2026-01-20T10:00:00Z",
        }

        # Should succeed after retry
        with patch("selko.services.gemini.time.sleep"):  # Skip actual sleep
            result = extract_calendar_events(
                client=mock_client,
                email_text="Test email",
                email_metadata=email_metadata,
                max_retries=3,
            )

        assert result.events_found is False
        assert mock_client.models.generate_content.call_count == 2

    def test_rate_limit_exhausted(self):
        """Test failure after exhausting retries."""
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception(
            "429 Rate limit exceeded"
        )

        email_metadata = {
            "gmail_id": "test-123",
            "subject": "Test",
            "from_email": "test@example.com",
            "date_sent": "2026-01-20T10:00:00Z",
        }

        with patch("selko.services.gemini.time.sleep"):  # Skip actual sleep
            with pytest.raises(GeminiError) as exc_info:
                extract_calendar_events(
                    client=mock_client,
                    email_text="Test email",
                    email_metadata=email_metadata,
                    max_retries=2,
                )

        assert "rate limited" in str(exc_info.value).lower()

    def test_non_rate_limit_error(self):
        """Test immediate failure on non-rate-limit errors."""
        mock_client = MagicMock()
        mock_client.models.generate_content.side_effect = Exception("Invalid API key")

        email_metadata = {
            "gmail_id": "test-123",
            "subject": "Test",
            "from_email": "test@example.com",
            "date_sent": "2026-01-20T10:00:00Z",
        }

        with pytest.raises(GeminiError) as exc_info:
            extract_calendar_events(
                client=mock_client,
                email_text="Test email",
                email_metadata=email_metadata,
            )

        # Should fail immediately, not retry
        assert mock_client.models.generate_content.call_count == 1
        assert "Invalid API key" in str(exc_info.value)

    def test_attachment_handling(self):
        """Test that attachments are properly added to request."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_extraction = CalendarEventExtraction(
            email_message_id="test-123",
            email_date="2026-01-20T10:00:00Z",
            sender_email="test@example.com",
            events_found=True,
            events=[],
        )
        mock_response.parsed = mock_extraction
        mock_client.models.generate_content.return_value = mock_response

        email_metadata = {
            "gmail_id": "test-123",
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
            client=mock_client,
            email_text="See attached invitation",
            email_metadata=email_metadata,
            attachments=attachments,
        )

        assert result.events_found is True
        mock_client.models.generate_content.assert_called_once()

        # Verify attachments were included in call
        call_args = mock_client.models.generate_content.call_args
        contents = call_args.kwargs["contents"]
        assert len(contents) > 2  # Should have text parts + attachment

    def test_oversized_attachment_skipped(self):
        """Test that oversized attachments are skipped."""
        mock_client = MagicMock()
        mock_response = MagicMock()
        mock_extraction = CalendarEventExtraction(
            email_message_id="test-123",
            email_date="2026-01-20T10:00:00Z",
            sender_email="test@example.com",
            events_found=False,
            events=[],
        )
        mock_response.parsed = mock_extraction
        mock_client.models.generate_content.return_value = mock_response

        email_metadata = {
            "gmail_id": "test-123",
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
            client=mock_client,
            email_text="See attached document",
            email_metadata=email_metadata,
            attachments=attachments,
        )

        assert result.events_found is False

        # Verify call was made (but without the oversized attachment)
        call_args = mock_client.models.generate_content.call_args
        contents = call_args.kwargs["contents"]
        # Should only have text parts, no attachment part
        assert len(contents) == 2
