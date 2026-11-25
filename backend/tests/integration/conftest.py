"""Fixtures for the integration tests.

The database is the SQLite `db` / `factory` pair from tests/sqlite_fixtures.py
(a fresh migrated file per test); these add the development config and the
sample payloads and LLM doubles the integration tests share.
"""

from uuid import uuid4

import pytest

from selko.config import load_config


@pytest.fixture(autouse=True)
def reset_fastapi_config_cache():
    """FastAPI's get_config() is lru_cached; clear it around every test."""
    from selko.api.deps import get_config

    get_config.cache_clear()
    yield
    get_config.cache_clear()


@pytest.fixture(scope="session")
def development_config():
    return load_config(env_override="development")


@pytest.fixture
def config(development_config):
    return development_config



@pytest.fixture
def sample_oauth_credentials():
    """Sample OAuth credentials for testing."""
    from google.oauth2.credentials import Credentials

    return Credentials(
        token="test_access_token_12345",
        refresh_token="test_refresh_token_67890",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="test_client_id",
        client_secret="test_client_secret",
        scopes=["https://www.googleapis.com/auth/gmail.readonly"],
    )


@pytest.fixture
def sample_email_data():
    """Sample parsed email data for testing."""
    from datetime import datetime, timezone

    # Use current time to ensure test email appears first in results
    # (emails are sorted by date_sent DESC)
    current_time = datetime.now(timezone.utc).isoformat()

    return {
        "provider_message_id": f"test_msg_{uuid4().hex[:8]}",
        "thread_id": f"test_thread_{uuid4().hex[:8]}",
        "subject": "Test Email Subject",
        "from_email": "sender@example.com",
        "from_name": "Test Sender",
        "to_emails": ["recipient@example.com"],
        "date_sent": current_time,
        "snippet": "This is a test email snippet",
        "provider_labels": ["INBOX", "UNREAD"],
        "has_attachments": False,
    }


@pytest.fixture
def sample_gmail_api_message():
    """Sample Gmail API message response for testing."""
    return {
        "id": f"msg_{uuid4().hex[:12]}",
        "threadId": f"thread_{uuid4().hex[:12]}",
        "snippet": "This is a test email snippet from Gmail API",
        "labelIds": ["INBOX", "UNREAD", "IMPORTANT"],
        "payload": {
            "headers": [
                {"name": "From", "value": "John Doe <john@example.com>"},
                {"name": "To", "value": "Jane Smith <jane@example.com>"},
                {"name": "Subject", "value": "Test Subject from Gmail"},
                {"name": "Date", "value": "Wed, 22 Jan 2026 10:30:00 +0000"},
            ],
            "parts": [],
        },
    }


@pytest.fixture
def sample_gmail_api_message_with_attachment():
    """Sample Gmail API message with attachment for testing."""
    return {
        "id": f"msg_{uuid4().hex[:12]}",
        "threadId": f"thread_{uuid4().hex[:12]}",
        "snippet": "Email with attachment",
        "labelIds": ["INBOX"],
        "payload": {
            "headers": [
                {"name": "From", "value": "sender@example.com"},
                {"name": "Subject", "value": "Test with attachment"},
                {"name": "Date", "value": "Wed, 22 Jan 2026 10:30:00 +0000"},
            ],
            "mimeType": "multipart/mixed",
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": "VGVzdCBib2R5"},  # base64 "Test body"
                },
                {
                    "filename": "test_document.pdf",
                    "mimeType": "application/pdf",
                    "body": {
                        "attachmentId": f"att_{uuid4().hex[:12]}",
                        "size": 1024,
                    },
                },
            ],
        },
    }


@pytest.fixture
def sample_attachment_data():
    """Sample attachment bytes for testing."""
    return b"This is sample attachment content for testing purposes."


# Config attr → env var name for clear --run-llm failure messages
_API_KEY_ENV_NAMES = {
    "gemini_api_key": "GEMINI_API_KEY",
    "alibaba_api_key": "ALIBABA_API_KEY",
    "anthropic_api_key": "ANTHROPIC_API_KEY",
    "openai_api_key": "OPENAI_API_KEY",
    "moonshot_api_key": "MOONSHOT_API_KEY",
    "zai_api_key": "ZAI_API_KEY",
    "deepseek_api_key": "DEEPSEEK_API_KEY",
    "minimax_api_key": "MINIMAX_API_KEY",
    "xai_api_key": "XAI_API_KEY",
    "meta_api_key": "META_API_KEY",
    "tinker_api_key": "TINKER_API_KEY",
}


@pytest.fixture
def llm_gateway(config):
    """Real LLMGateway for tests marked @pytest.mark.llm (requires --run-llm).

    Uses config.llm_provider / llm_model and the matching provider API key.
    """
    from selko.services.llm_gateway import LLMGateway
    from selko.services.llm_provider import PROVIDER_API_KEY_MAP, create_provider

    provider_name = getattr(config, "llm_provider", None) or "gemini"
    api_key_attr = PROVIDER_API_KEY_MAP.get(provider_name)
    if not api_key_attr or not getattr(config, api_key_attr, None):
        env_name = _API_KEY_ENV_NAMES.get(api_key_attr or "", "LLM provider API key")
        pytest.fail(
            f"{env_name} not configured for provider '{provider_name}'. "
            "Set the matching key in your environment before using --run-llm."
        )
    provider = create_provider(config)
    return LLMGateway(provider)


@pytest.fixture
def mock_llm_gateway():
    """Mocked LLM Gateway for integration tests without API costs."""
    from unittest.mock import MagicMock
    from selko.api.schemas.calendar import (
        CalendarEvent,
        EventExtractionResponse,
    )
    from selko.services.llm_gateway import LLMGateway
    from selko.services.llm_provider import LLMProvider, LLMResponse
    from datetime import datetime

    mock_provider = MagicMock(spec=LLMProvider)
    mock_provider.provider_name = "mock"
    mock_provider.model = "mock-llm"
    mock_provider.supports_vision = True
    mock_provider.supports_json_schema = True

    def mock_generate(contents, json_schema=None):
        """Default mock: returns appropriate response based on prompt."""
        prompt_text = str(contents)

        # Event comparison (returns event ID or NO_MATCH)
        if "Is the new event the same" in prompt_text or "comparing calendar events" in prompt_text.lower():
            return LLMResponse(text="NO_MATCH", prompt_tokens=100, completion_tokens=10)

        # Event merge (returns merged JSON)
        if "merging calendar event data" in prompt_text.lower():
            return LLMResponse(
                text='{"title": "Merged Event", "start_datetime": "2026-03-01T14:00:00Z", "end_datetime": "2026-03-01T15:00:00Z", "all_day": false, "location": "Merged Location", "description": "Merged description", "importance": "action_required"}',
                prompt_tokens=200,
                completion_tokens=50,
            )

        # Event extraction (returns structured JSON response)
        mock_llm_response = EventExtractionResponse(
            events_found=True,
            events=[
                CalendarEvent(
                    title="Mock Event",
                    start_datetime=datetime.fromisoformat("2026-03-01T14:00:00+00:00"),
                    end_datetime=datetime.fromisoformat("2026-03-01T15:00:00+00:00"),
                    all_day=False,
                    location="Mock Location",
                    description="This is a mock event for testing",
                )
            ],
        )
        return LLMResponse(
            text=mock_llm_response.model_dump_json(),
            prompt_tokens=500,
            completion_tokens=100,
        )

    mock_provider.generate.side_effect = mock_generate

    gateway = LLMGateway(mock_provider)
    gateway._mock_provider = mock_provider
    return gateway


@pytest.fixture
def mock_llm_no_events():
    """Mock LLM Gateway that returns no events found."""
    from unittest.mock import MagicMock
    from selko.api.schemas.calendar import EventExtractionResponse
    from selko.services.llm_gateway import LLMGateway
    from selko.services.llm_provider import LLMProvider, LLMResponse

    mock_provider = MagicMock(spec=LLMProvider)
    mock_provider.provider_name = "mock"
    mock_provider.model = "mock-llm"
    mock_provider.supports_vision = True
    mock_provider.supports_json_schema = True

    mock_llm_response = EventExtractionResponse(
        events_found=False,
        events=[],
    )
    mock_provider.generate.return_value = LLMResponse(
        text=mock_llm_response.model_dump_json(),
        prompt_tokens=100,
        completion_tokens=20,
    )

    gateway = LLMGateway(mock_provider)
    gateway._mock_provider = mock_provider
    return gateway
