"""Pytest fixtures for integration tests.

These fixtures connect to real Supabase instances and require proper configuration.
Development tests use local Supabase (Docker), staging tests use cloud Supabase.
"""

import logging
import os
from uuid import uuid4

import pytest
from supabase import create_client

from selko.config import Config, load_config
from selko.services.auth import get_authenticated_client, get_current_user_id
from selko.services.users import create_user, delete_user, get_admin_client

logger = logging.getLogger(__name__)


@pytest.fixture(autouse=True, scope="function")
def reset_fastapi_config_cache(request):
    """Clear FastAPI config cache and reset ENVIRONMENT before each test.

    This ensures that FastAPI's get_config() dependency uses the same
    configuration as the test fixtures, preventing JWT validation failures
    due to config mismatch between different Supabase instances.

    The problem:
    1. @lru_cache on get_config() persists across tests
    2. Test fixtures load different .env files which pollute os.environ
    3. .env.test sets ENVIRONMENT=staging, polluting os.environ["ENVIRONMENT"]
    4. get_config() then loads wrong config based on polluted ENVIRONMENT

    The fix:
    1. Clear the lru_cache
    2. Reset ENVIRONMENT to match the test's expected environment
    3. Reload the correct .env file
    """
    from selko.api.deps import get_config
    from selko.config import load_config, ENV_FILES, PROJECT_ROOT
    from dotenv import load_dotenv

    # Determine expected environment from test markers
    env = _get_env_for_markers(request)

    # Clear cache before test
    get_config.cache_clear()

    # Reset ENVIRONMENT variable and reload correct .env file
    os.environ["ENVIRONMENT"] = env
    env_file = ENV_FILES.get(env)
    env_path = PROJECT_ROOT / env_file
    if env_path.exists():
        load_dotenv(env_path, override=True)

    logger.debug(f"[CACHE] Reset config cache and ENVIRONMENT={env}")

    yield

    # Clear after test
    get_config.cache_clear()
    logger.debug("[CACHE] Cleared get_config cache after test")


def _get_env_for_markers(request) -> str:
    """Determine environment from test markers.

    The local_real marker uses development environment (local Supabase)
    but expects real Gmail tokens to be seeded via cli_seed_tokens.
    """
    if request.node.get_closest_marker("staging"):
        return "staging"
    if request.node.get_closest_marker("production"):
        return "production"
    # Both "development" and "local_real" use local Supabase
    # The difference is whether Gmail API is mocked or real
    return "development"


@pytest.fixture(scope="session")
def development_config():
    """Load development configuration (local Supabase)."""
    return load_config(env_override="development")


@pytest.fixture(scope="session")
def staging_config():
    """Load staging configuration (cloud Supabase).

    Always loads staging config - tests marked with @pytest.mark.staging
    will use this. If .env.test is missing, load_config will fail appropriately.
    """
    try:
        return load_config(env_override="staging")
    except SystemExit:
        # .env.test doesn't exist or is invalid
        return None


@pytest.fixture(scope="function")
def config(request, development_config, staging_config):
    """Get config based on test markers.

    Tests marked with @pytest.mark.staging get staging config,
    otherwise development config is used.
    """
    env = _get_env_for_markers(request)
    if env == "staging":
        if staging_config is None:
            pytest.skip("Staging config not available")
        return staging_config
    return development_config


@pytest.fixture(scope="function")
def authenticated_client(config):
    """Authenticated Supabase client for integration tests.

    Uses test user credentials from config.
    Signs out after test completes.
    """
    client = get_authenticated_client(config)
    yield client
    # Cleanup: sign out
    try:
        client.auth.sign_out()
    except Exception:
        pass  # Ignore sign out errors during cleanup


@pytest.fixture(scope="function")
def test_user_id(authenticated_client):
    """Get current user ID from authenticated session."""
    return get_current_user_id(authenticated_client)


@pytest.fixture(scope="function")
def admin_client(config):
    """Admin client using service role key (bypasses RLS).

    Use for setup/teardown of test data.
    """
    return get_admin_client(config)


@pytest.fixture(scope="function")
def temp_user(config):
    """Create a temporary user for testing, delete after test.

    Returns tuple of (user_id, email, password).
    """
    email = f"test-{uuid4()}@selko.local"
    password = "testpass123"

    user = create_user(config, email, password, auto_confirm=True)
    yield user["id"], email, password

    # Cleanup
    try:
        delete_user(config, user["id"])
    except Exception:
        pass  # Ignore cleanup errors


@pytest.fixture(scope="function")
def temp_user_client(config, temp_user):
    """Get authenticated client for temporary user.
    
    Returns authenticated Supabase client for the temp user.
    Temp user is automatically cleaned up after test.
    """
    user_id, email, password = temp_user
    client = create_client(config.supabase_url, config.supabase_key)
    client.auth.sign_in_with_password({"email": email, "password": password})
    yield client
    # Cleanup: sign out
    try:
        client.auth.sign_out()
    except Exception:
        pass


@pytest.fixture(scope="function")
def cleanup_emails(authenticated_client, test_user_id):
    """Delete test emails after test completes."""
    created_gmail_ids = []

    yield created_gmail_ids  # Test can append gmail_ids to this list

    # Cleanup
    if created_gmail_ids:
        try:
            for gmail_id in created_gmail_ids:
                authenticated_client.table("emails").delete().eq(
                    "user_id", test_user_id
                ).eq("gmail_id", gmail_id).execute()
        except Exception:
            pass


@pytest.fixture(scope="function")
def cleanup_integrations(authenticated_client, test_user_id):
    """Delete test integrations after test completes."""
    created_providers = []

    yield created_providers  # Test can append provider names to this list

    # Cleanup
    if created_providers:
        try:
            for provider in created_providers:
                authenticated_client.table("integrations").delete().eq(
                    "user_id", test_user_id
                ).eq("provider", provider).execute()
        except Exception:
            pass


# Sample test data fixtures


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
        "gmail_id": f"test_msg_{uuid4().hex[:8]}",
        "thread_id": f"test_thread_{uuid4().hex[:8]}",
        "subject": "Test Email Subject",
        "from_email": "sender@example.com",
        "from_name": "Test Sender",
        "to_emails": ["recipient@example.com"],
        "date_sent": current_time,
        "snippet": "This is a test email snippet",
        "gmail_label_ids": ["INBOX", "UNREAD"],
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


@pytest.fixture
def gemini_client(config):
    """Get LLM Gateway for real API calls.

    Requires GEMINI_API_KEY in environment.
    This fixture is for tests marked with @pytest.mark.llm.

    Note: This now returns an LLMGateway (not a raw client) since the
    codebase uses LLMGateway for all LLM operations.
    """
    from selko.services.llm_gateway import LLMGateway

    if not config.gemini_api_key:
        pytest.fail(
            "GEMINI_API_KEY not configured. "
            "Get your API key from https://aistudio.google.com/apikey"
        )
    return LLMGateway(config)


@pytest.fixture
def mock_gemini_client():
    """Get mocked LLM Gateway for integration tests without API costs.

    This fixture provides a mock gateway that returns realistic responses
    without making actual LLM API calls. Use for integration tests that
    test service orchestration without LLM costs.
    """
    from unittest.mock import MagicMock
    from selko.api.schemas.calendar import (
        CalendarEvent,
        GeminiEventsResponse,
    )
    from selko.services.llm_gateway import LLMGateway
    from selko.services.llm_provider import LLMProvider, LLMResponse
    from datetime import datetime

    mock_provider = MagicMock(spec=LLMProvider)
    mock_provider.provider_name = "gemini"
    mock_provider.model = "gemini-3-flash-preview"
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
                text='{"title": "Merged Event", "start_datetime": "2026-03-01T14:00:00Z", "end_datetime": "2026-03-01T15:00:00Z", "all_day": false, "location": "Merged Location", "description": "Merged description"}',
                prompt_tokens=200,
                completion_tokens=50,
            )

        # Event extraction (returns structured JSON response)
        mock_gemini_response = GeminiEventsResponse(
            events_found=True,
            events=[
                CalendarEvent(
                    title="Mock Event",
                    start_datetime=datetime.fromisoformat("2026-03-01T14:00:00+00:00"),
                    end_datetime=datetime.fromisoformat("2026-03-01T15:00:00+00:00"),
                    all_day=False,
                    location="Mock Location",
                    description="This is a mock event for testing",
                    confidence=0.9,
                )
            ],
        )
        return LLMResponse(
            text=mock_gemini_response.model_dump_json(),
            prompt_tokens=500,
            completion_tokens=100,
        )

    mock_provider.generate.side_effect = mock_generate

    gateway = LLMGateway(mock_provider)
    gateway._mock_provider = mock_provider
    return gateway


@pytest.fixture
def mock_gemini_no_events():
    """Mock LLM Gateway that returns no events found."""
    from unittest.mock import MagicMock
    from selko.api.schemas.calendar import GeminiEventsResponse
    from selko.services.llm_gateway import LLMGateway
    from selko.services.llm_provider import LLMProvider, LLMResponse

    mock_provider = MagicMock(spec=LLMProvider)
    mock_provider.provider_name = "gemini"
    mock_provider.model = "gemini-3-flash-preview"
    mock_provider.supports_vision = True
    mock_provider.supports_json_schema = True

    mock_gemini_response = GeminiEventsResponse(
        events_found=False,
        events=[],
    )
    mock_provider.generate.return_value = LLMResponse(
        text=mock_gemini_response.model_dump_json(),
        prompt_tokens=100,
        completion_tokens=20,
    )

    gateway = LLMGateway(mock_provider)
    gateway._mock_provider = mock_provider
    return gateway
