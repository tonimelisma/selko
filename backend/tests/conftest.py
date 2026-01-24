"""Pytest fixtures for Selko tests."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from selko.config import Config


@pytest.fixture
def mock_config():
    """Create a mock Config object for testing."""
    return Config(
        environment="development",
        supabase_url="http://localhost:54321",
        supabase_key="test-anon-key",
        supabase_service_role_key="test-service-key",
        google_client_id="test-client-id",
        google_client_secret="test-client-secret",
        test_user_email="test@example.com",
        test_user_password="testpass",
        credentials_file=Path("/tmp/credentials.json"),
    )


@pytest.fixture
def mock_supabase_client():
    """Create a mock Supabase client."""
    client = MagicMock()
    client.auth.get_session.return_value = MagicMock(
        user=MagicMock(id="test-user-id")
    )
    return client


@pytest.fixture
def sample_gmail_message():
    """Create a sample Gmail API message for testing."""
    return {
        "id": "msg-123",
        "threadId": "thread-123",
        "snippet": "This is a test email snippet",
        "labelIds": ["INBOX", "UNREAD"],
        "payload": {
            "headers": [
                {"name": "From", "value": "John Doe <john@example.com>"},
                {"name": "To", "value": "Jane Smith <jane@example.com>"},
                {"name": "Subject", "value": "Test Subject"},
                {"name": "Date", "value": "Mon, 20 Jan 2026 10:30:00 +0000"},
            ],
            "parts": [],
        },
    }
