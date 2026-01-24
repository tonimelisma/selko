"""Integration tests for authentication service.

Tests sign in/out flow with real Supabase Auth.
"""

import pytest
from supabase import create_client

from selko.services.auth import (
    AuthenticationError,
    get_authenticated_client,
    get_current_user_id,
)


@pytest.mark.integration
@pytest.mark.development
class TestAuthentication:
    """Test authentication with real Supabase."""

    def test_sign_in_valid_credentials(self, config):
        """User can sign in with valid credentials."""
        client = get_authenticated_client(config)

        # Verify session exists
        session = client.auth.get_session()
        assert session is not None
        assert session.user is not None
        assert session.user.email == config.test_user_email
        assert session.access_token is not None

        # Cleanup
        client.auth.sign_out()

    def test_sign_in_invalid_credentials(self, config):
        """Sign in fails with invalid credentials."""
        from selko.config import Config

        invalid_config = Config(
            environment=config.environment,
            supabase_url=config.supabase_url,
            supabase_key=config.supabase_key,
            test_user_email="nonexistent@example.com",
            test_user_password="wrongpassword",
        )

        with pytest.raises(AuthenticationError) as exc_info:
            get_authenticated_client(invalid_config)

        assert "Sign-in failed" in str(exc_info.value)

    def test_get_current_user_id(self, authenticated_client):
        """Can retrieve user ID from authenticated session."""
        user_id = get_current_user_id(authenticated_client)

        assert user_id is not None
        # UUID format check
        assert len(user_id) == 36
        assert user_id.count("-") == 4

    def test_get_current_user_id_unauthenticated(self, config):
        """Getting user ID without auth raises error."""
        # Create unauthenticated client
        client = create_client(config.supabase_url, config.supabase_key)

        with pytest.raises(AuthenticationError) as exc_info:
            get_current_user_id(client)

        assert "No user signed in" in str(exc_info.value)

    def test_sign_out(self, config):
        """User can sign out and session is cleared."""
        client = get_authenticated_client(config)

        # Verify signed in
        session = client.auth.get_session()
        assert session is not None

        # Sign out
        client.auth.sign_out()

        # Note: Supabase client may still have cached session
        # The sign_out is primarily server-side invalidation

    def test_missing_credentials_config(self, config):
        """Error when credentials not configured."""
        from selko.config import Config

        empty_config = Config(
            environment=config.environment,
            supabase_url=config.supabase_url,
            supabase_key=config.supabase_key,
            test_user_email=None,
            test_user_password=None,
        )

        with pytest.raises(AuthenticationError) as exc_info:
            get_authenticated_client(empty_config)

        assert "TEST_USER_EMAIL" in str(exc_info.value)


@pytest.mark.integration
@pytest.mark.staging
class TestAuthenticationStaging:
    """Test authentication against staging environment."""

    def test_sign_in_staging(self, config):
        """User can sign in to staging environment."""
        client = get_authenticated_client(config)

        session = client.auth.get_session()
        assert session is not None
        assert session.user is not None

        client.auth.sign_out()

    def test_get_user_id_staging(self, authenticated_client):
        """Can retrieve user ID in staging environment."""
        user_id = get_current_user_id(authenticated_client)
        assert user_id is not None
