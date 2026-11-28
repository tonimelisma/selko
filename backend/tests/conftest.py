"""Pytest fixtures for Selko tests."""

import os

import pytest

from selko.config import Config

# `db` and `factory`: a fresh SQLite database per test (selko.db).
pytest_plugins = ["tests.sqlite_fixtures"]


def pytest_addoption(parser):
    """Add custom command line options."""
    parser.addoption(
        "--run-llm",
        action="store_true",
        default=False,
        help="Run tests that make real LLM API calls (costs money)",
    )


def pytest_configure(config):
    """Register custom markers; keep Key Vault out of runs that need no keys."""
    # load_config() reads missing API keys from Azure Key Vault (selko.keyvault).
    # Only --run-llm needs real keys; every other test must see exactly the
    # environment it sets up, on the Mac (az login) as in CI.
    if not config.getoption("--run-llm"):
        os.environ.setdefault("SELKO_KEYVAULT_AUTH", "off")
    config.addinivalue_line(
        "markers", "llm: marks tests as requiring real LLM API calls (deselect with '-m \"not llm\"')"
    )


def pytest_collection_modifyitems(config, items):
    """Auto-skip LLM tests unless --run-llm flag is provided."""
    if config.getoption("--run-llm"):
        # Run all tests including LLM
        return
    
    skip_llm = pytest.mark.skip(reason="LLM test requires --run-llm flag to avoid API costs")
    for item in items:
        if "llm" in item.keywords:
            item.add_marker(skip_llm)


@pytest.fixture
def mock_config():
    """Create a mock Config object for testing."""
    return Config(
        environment="development",
        google_client_id="test-client-id",
        google_client_secret="test-client-secret",
    )


@pytest.fixture
def fake_pg_pool():
    """Minimal asyncpg pool double: records SQL and returns queued rows.

    C2: every worker database operation runs over the pool, so tests assert
    on the recorded calls instead of mocking PostgREST ``client.rpc``.
    """

    class FakePool:
        def __init__(self):
            self.calls = []
            self.rows = []

        async def fetchrow(self, sql, *args):
            self.calls.append((sql, args))
            return self.rows.pop(0) if self.rows else None

        async def fetchval(self, sql, *args):
            self.calls.append((sql, args))
            return self.rows.pop(0) if self.rows else None

        async def fetch(self, sql, *args):
            self.calls.append((sql, args))
            row = self.rows.pop(0) if self.rows else None
            return [row] if row is not None else []

        async def execute(self, sql, *args):
            self.calls.append((sql, args))

    return FakePool()


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
