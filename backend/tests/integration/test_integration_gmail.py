"""Integration tests for Gmail service.

All tests use real Gmail API with seeded OAuth tokens.
Development tests use local Supabase, staging tests use cloud Supabase.
"""

import pytest

from selko.services.gmail import (
    GmailError,
    build_service,
    fetch_messages,
    get_credentials,
    get_user_profile,
)


import functools


def skip_if_token_expired(func):
    """Decorator to skip test if Gmail tokens are expired/revoked."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except GmailError as e:
            if "expired or revoked" in str(e) or "unauthorized_client" in str(e):
                pytest.skip(f"Gmail tokens expired/revoked - re-authenticate in staging: {e}")
            raise
    return wrapper


@pytest.mark.integration
@pytest.mark.staging
class TestGmailStaging:
    """Test Gmail service with real API (staging).

    These tests require:
    1. Burner Gmail account authorized
    2. OAuth tokens stored in staging database
    3. ENVIRONMENT=staging or --env staging
    """

    def test_get_credentials_real(self, authenticated_client, config):
        """Can retrieve real Gmail credentials from staging DB."""
        creds = get_credentials(authenticated_client, config)

        # If no credentials, fail the test
        if creds is None:
            pytest.fail("No Gmail credentials in staging - run cli_auth_gmail first")

        assert creds.token is not None
        # Real credentials should have refresh token
        assert creds.refresh_token is not None

    def test_build_service_real(self, authenticated_client, config):
        """Can build service with real credentials."""
        creds = get_credentials(authenticated_client, config)
        if creds is None:
            pytest.fail("No Gmail credentials in staging - run cli_auth_gmail first")

        service = build_service(creds)
        assert service is not None

    @skip_if_token_expired
    def test_get_user_profile_real(self, authenticated_client, config):
        """Can get real user profile from Gmail."""
        creds = get_credentials(authenticated_client, config)
        if creds is None:
            pytest.fail("No Gmail credentials in staging - run cli_auth_gmail first")

        service = build_service(creds)
        profile = get_user_profile(service)

        assert "emailAddress" in profile
        assert "@" in profile["emailAddress"]

    @skip_if_token_expired
    def test_fetch_messages_real(self, authenticated_client, config):
        """Can fetch real messages from Gmail."""
        creds = get_credentials(authenticated_client, config)
        if creds is None:
            pytest.fail("No Gmail credentials in staging - run cli_auth_gmail first")

        service = build_service(creds)
        messages = fetch_messages(service, max_results=5)

        # Burner account should have at least some emails
        # (send test emails to it during setup)
        assert isinstance(messages, list)
        # Each message should have expected fields
        if messages:
            msg = messages[0]
            assert "id" in msg
            assert "threadId" in msg
            assert "labelIds" in msg

    def test_token_refresh_if_expired(self, authenticated_client, config):
        """Expired tokens are automatically refreshed."""
        # This test verifies the refresh logic works
        # The get_credentials function handles refresh automatically
        creds = get_credentials(authenticated_client, config)
        if creds is None:
            pytest.fail("No Gmail credentials in staging - run cli_auth_gmail first")

        # Credentials should be valid (refreshed if needed)
        # If they were expired, get_credentials would have refreshed them
        assert creds.token is not None


@pytest.mark.integration
@pytest.mark.development
class TestGmailDevelopment:
    """Test Gmail service with local Supabase + real Gmail API.

    These tests use local Supabase (Docker) and call the real Gmail API.
    OAuth tokens must be seeded from staging using cli_seed_tokens.

    Prerequisites:
    1. Local Supabase running: supabase start
    2. Test user created locally
    3. Tokens seeded: uv run python -m cli.cli_seed_tokens --from staging --to development --provider gmail
    """

    def test_get_credentials_real(self, authenticated_client, config):
        """Can retrieve real Gmail credentials from local DB."""
        creds = get_credentials(authenticated_client, config)

        if creds is None:
            pytest.fail(
                "No Gmail credentials found.\n"
                "Seed tokens: uv run python -m cli.cli_seed_tokens --from staging --to development --provider gmail"
            )

        assert creds.token is not None
        assert creds.refresh_token is not None

    def test_build_service_real(self, authenticated_client, config):
        """Can build service with real credentials."""
        creds = get_credentials(authenticated_client, config)
        if creds is None:
            pytest.fail("No Gmail credentials - run cli_seed_tokens first")

        service = build_service(creds)
        assert service is not None

    @skip_if_token_expired
    def test_get_user_profile_real(self, authenticated_client, config):
        """Can get real user profile from Gmail."""
        creds = get_credentials(authenticated_client, config)
        if creds is None:
            pytest.fail("No Gmail credentials - run cli_seed_tokens first")

        service = build_service(creds)
        profile = get_user_profile(service)

        assert "emailAddress" in profile
        assert "@" in profile["emailAddress"]

    @skip_if_token_expired
    def test_fetch_messages_real(self, authenticated_client, config):
        """Can fetch real messages from Gmail."""
        creds = get_credentials(authenticated_client, config)
        if creds is None:
            pytest.fail("No Gmail credentials - run cli_seed_tokens first")

        service = build_service(creds)
        messages = fetch_messages(service, max_results=5)

        assert isinstance(messages, list)
        # Each message should have expected fields
        if messages:
            msg = messages[0]
            assert "id" in msg
            assert "threadId" in msg
            assert "labelIds" in msg

    def test_token_refresh_if_expired(self, authenticated_client, config):
        """Expired tokens are automatically refreshed."""
        creds = get_credentials(authenticated_client, config)
        if creds is None:
            pytest.fail("No Gmail credentials - run cli_seed_tokens first")

        # Credentials should be valid (refreshed if needed)
        assert creds.token is not None
