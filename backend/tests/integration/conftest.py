"""Pytest fixtures for integration tests.

These fixtures connect to real Supabase instances and require proper configuration.
Development tests use local Supabase (Docker), staging tests use cloud Supabase.
"""

import os
from uuid import uuid4

import pytest
from supabase import create_client

from selko.config import Config, load_config
from selko.services.auth import get_authenticated_client, get_current_user_id
from selko.services.users import create_user, delete_user, get_admin_client


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
    return {
        "gmail_id": f"test_msg_{uuid4().hex[:8]}",
        "thread_id": f"test_thread_{uuid4().hex[:8]}",
        "subject": "Test Email Subject",
        "from_email": "sender@example.com",
        "from_name": "Test Sender",
        "to_emails": ["recipient@example.com"],
        "date_sent": "2026-01-22T10:00:00+00:00",
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
