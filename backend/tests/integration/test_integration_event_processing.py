"""Integration tests for LLM calendar event extraction.

These tests make real calls to the LLM API and require:
- The active provider API key in environment (see LLM_PROVIDER)
- a real SQLite database (the `db` fixture) for the database tests
"""

import json
from pathlib import Path

import pytest

from selko.api.schemas.calendar import CalendarEventExtraction
from selko.config import load_config
from selko.services.event_processing import (
    extract_calendar_events,
    fetch_email_with_attachments,
)
from selko.services.llm_gateway import LLMGatewayError
from selko.services.llm_gateway import LLMGateway
from selko.services.llm_provider import LLMProviderError, create_provider


@pytest.fixture
def config():
    """Load application config."""
    return load_config()


@pytest.fixture
def fixtures_dir():
    """Get path to test fixtures directory."""
    return Path(__file__).parent.parent / "fixtures" / "emails"


def load_fixture(fixtures_dir: Path, fixture_name: str) -> dict:
    """Load a test fixture JSON file."""
    if not fixture_name.endswith(".json"):
        fixture_name += ".json"

    fixture_path = fixtures_dir / fixture_name
    with open(fixture_path) as f:
        return json.load(f)


@pytest.mark.integration
@pytest.mark.llm
class TestLlmRealAPI:
    """Test calendar extraction with real LLM API calls.

    These tests require --run-llm flag to run (costs money).
    """

    def test_birthday_party_extraction(self, llm_gateway, fixtures_dir):
        """Test extraction from birthday party invitation."""
        fixture = load_fixture(fixtures_dir, "event_birthday_party")
        input_data = fixture["input"]

        email_metadata = {
            "provider_message_id": input_data["provider_message_id"],
            "subject": input_data["subject"],
            "from_name": input_data.get("from_name"),
            "from_email": input_data["from_email"],
            "date_sent": input_data["date_sent"],
        }

        result = extract_calendar_events(
            gateway=llm_gateway,
            email_text=input_data["body_text"],
            email_metadata=email_metadata,
        )

        # Verify structure
        assert isinstance(result, CalendarEventExtraction)
        assert result.events_found is True
        assert len(result.events) >= 1

        # Verify at least one event has expected fields
        event = result.events[0]
        assert event.title
        assert event.start_datetime is not None
        assert "birthday" in event.title.lower() or "jake" in event.title.lower()

    def test_doctor_appointment_extraction(self, llm_gateway, fixtures_dir):
        """Test extraction from doctor appointment confirmation."""
        fixture = load_fixture(fixtures_dir, "event_doctor_appointment")
        input_data = fixture["input"]

        email_metadata = {
            "provider_message_id": input_data["provider_message_id"],
            "subject": input_data["subject"],
            "from_name": input_data.get("from_name"),
            "from_email": input_data["from_email"],
            "date_sent": input_data["date_sent"],
        }

        result = extract_calendar_events(
            gateway=llm_gateway,
            email_text=input_data["body_text"],
            email_metadata=email_metadata,
        )

        assert result.events_found is True
        assert len(result.events) >= 1

        event = result.events[0]
        assert event.start_datetime is not None
        assert event.location is not None

    def test_newsletter_no_events(self, llm_gateway, fixtures_dir):
        """Test that newsletter correctly returns no events."""
        fixture = load_fixture(fixtures_dir, "no_event_newsletter")
        input_data = fixture["input"]

        email_metadata = {
            "provider_message_id": input_data["provider_message_id"],
            "subject": input_data["subject"],
            "from_name": input_data.get("from_name"),
            "from_email": input_data["from_email"],
            "date_sent": input_data["date_sent"],
        }

        result = extract_calendar_events(
            gateway=llm_gateway,
            email_text=input_data["body_text"],
            email_metadata=email_metadata,
        )

        # Newsletter should have no events
        assert result.events_found is False
        assert len(result.events) == 0

    def test_receipt_no_events(self, llm_gateway, fixtures_dir):
        """Test that receipt correctly returns no events."""
        fixture = load_fixture(fixtures_dir, "no_event_receipt")
        input_data = fixture["input"]

        email_metadata = {
            "provider_message_id": input_data["provider_message_id"],
            "subject": input_data["subject"],
            "from_name": input_data.get("from_name"),
            "from_email": input_data["from_email"],
            "date_sent": input_data["date_sent"],
        }

        result = extract_calendar_events(
            gateway=llm_gateway,
            email_text=input_data["body_text"],
            email_metadata=email_metadata,
        )

        # Receipt should have no events
        assert result.events_found is False
        assert len(result.events) == 0

    def test_multiple_events_extraction(self, llm_gateway, fixtures_dir):
        """Test extraction of multiple events from conference schedule."""
        fixture = load_fixture(fixtures_dir, "event_multiple_events")
        input_data = fixture["input"]

        email_metadata = {
            "provider_message_id": input_data["provider_message_id"],
            "subject": input_data["subject"],
            "from_name": input_data.get("from_name"),
            "from_email": input_data["from_email"],
            "date_sent": input_data["date_sent"],
        }

        result = extract_calendar_events(
            gateway=llm_gateway,
            email_text=input_data["body_text"],
            email_metadata=email_metadata,
        )

        assert result.events_found is True
        # Should extract multiple events from the conference schedule
        assert len(result.events) >= 2

        # Verify all events have required fields
        for event in result.events:
            assert event.title
            assert event.start_datetime is not None

    def test_thinking_level_low(self, llm_gateway, fixtures_dir):
        """Test that thinking_level='low' is being used correctly."""
        fixture = load_fixture(fixtures_dir, "event_birthday_party")
        input_data = fixture["input"]

        email_metadata = {
            "provider_message_id": input_data["provider_message_id"],
            "subject": input_data["subject"],
            "from_name": input_data.get("from_name"),
            "from_email": input_data["from_email"],
            "date_sent": input_data["date_sent"],
        }

        # Should complete successfully with low thinking level
        result = extract_calendar_events(
            gateway=llm_gateway,
            email_text=input_data["body_text"],
            email_metadata=email_metadata,
        )

        assert isinstance(result, CalendarEventExtraction)
        assert result.events_found is True


@pytest.mark.integration
@pytest.mark.llm
class TestLlmWithDatabase:
    """Test LLM extraction with real database emails.

    The email is seeded into a real SQLite database (`db`/`factory`).

    These tests require --run-llm flag to run (costs money).
    """

    def test_fetch_and_extract_from_database(self, llm_gateway, db, factory):
        """Fetch an email from the database and extract events from it."""
        user = factory.user()
        email_id = factory.email(
            user, provider_message_id="llm-db-probe", subject="Birthday Party Invitation",
            from_email="friend@example.com", from_name="Best Friend",
            date_sent="2026-02-15T12:00:00.000000Z",
            body_text="You're invited to Sarah's birthday party on Feb 20th at 2pm!",
        )

        email_metadata, email_text, attachments = fetch_email_with_attachments(db, email_id)

        assert email_metadata["provider_message_id"] == "llm-db-probe"
        assert email_metadata["subject"] == "Birthday Party Invitation"

        extraction_result = extract_calendar_events(
            gateway=llm_gateway,
            email_text=email_text,
            email_metadata=email_metadata,
            attachments=attachments,
        )

        assert isinstance(extraction_result, CalendarEventExtraction)
        # email_message_id should match the provider_message_id from the email
        assert extraction_result.email_message_id == email_metadata["provider_message_id"]
        assert extraction_result.sender_email == email_metadata["from_email"]

    def test_fetch_nonexistent_email(self, db):
        """Test error handling for nonexistent email."""
        fake_uuid = "00000000-0000-0000-0000-000000000000"

        with pytest.raises(LLMGatewayError) as exc_info:
            fetch_email_with_attachments(db, fake_uuid)

        assert "Email not found" in str(exc_info.value)


@pytest.mark.integration
@pytest.mark.llm
class TestLLMGatewayErrorHandling:
    """Test LLM provider/gateway error handling.

    These tests require --run-llm flag to run (costs money).
    """

    def test_invalid_api_key(self, config):
        """Test error handling with invalid API key."""
        from selko.config import Config

        bad_config = Config(
            environment=config.environment,
            llm_provider="gemini",
            llm_model="gemini-3.5-flash-lite",
            gemini_api_key="invalid-key-12345",
        )

        provider = create_provider(bad_config)
        gateway = LLMGateway(provider)

        email_metadata = {
            "provider_message_id": "test-123",
            "subject": "Test",
            "from_email": "test@example.com",
            "date_sent": "2026-01-20T10:00:00Z",
        }

        # Should fail with invalid key
        with pytest.raises(LLMGatewayError):
            extract_calendar_events(
                gateway=gateway,
                email_text="Test email",
                email_metadata=email_metadata,
            )

    def test_missing_api_key(self):
        """Test error when API key is not configured."""
        from selko.config import Config

        config_no_key = Config(
            environment="development",
            llm_provider="gemini",
            llm_model="gemini-3.5-flash-lite",
            gemini_api_key=None,
        )

        with pytest.raises(LLMProviderError, match="API key not configured"):
            create_provider(config_no_key)


@pytest.mark.integration
def test_fetching_a_missing_email_is_email_not_found(db):
    """No LLM needed: the database read answers None and the service says so."""
    with pytest.raises(LLMGatewayError, match="Email not found"):
        fetch_email_with_attachments(db, "00000000-0000-0000-0000-000000000000")
