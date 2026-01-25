"""Integration tests for OAuth integration storage.

Tests storing and retrieving OAuth credentials from the database.
"""

import pytest

from selko.services.integrations import (
    IntegrationError,
    get_oauth_credentials,
    save_oauth_credentials,
    update_integration_status,
    update_oauth_credentials,
)


@pytest.mark.integration
@pytest.mark.development
class TestOAuthIntegrations:
    """Test OAuth credential storage with real Supabase.
    
    These tests create temporary test data and should clean up after themselves.
    They use temp_user to avoid interfering with seeded Gmail credentials.
    """

    def test_save_oauth_credentials(
        self,
        config,
        sample_oauth_credentials,
        temp_user_client,
    ):
        """Can save OAuth credentials to database."""
        save_oauth_credentials(
            temp_user_client,
            "gmail",
            sample_oauth_credentials,
            provider_email="test@gmail.com",
        )

        # Verify saved by retrieving
        creds = get_oauth_credentials(temp_user_client, config, "gmail")
        assert creds is not None
        assert creds.token == sample_oauth_credentials.token
        assert creds.refresh_token == sample_oauth_credentials.refresh_token

    def test_get_oauth_credentials_not_found(self, config, temp_user_client):
        """Returns None when no credentials exist."""
        # Use a provider that shouldn't exist
        creds = get_oauth_credentials(
            temp_user_client, config, "nonexistent_provider"
        )
        assert creds is None

    def test_save_credentials_upsert(
        self,
        config,
        sample_oauth_credentials,
        temp_user_client,
    ):
        """Saving credentials again updates existing record."""
        # First save
        save_oauth_credentials(temp_user_client, "gmail", sample_oauth_credentials)

        # Second save with different token
        from google.oauth2.credentials import Credentials

        updated_creds = Credentials(
            token="updated_token_xyz",
            refresh_token=sample_oauth_credentials.refresh_token,
            token_uri=sample_oauth_credentials.token_uri,
            client_id=sample_oauth_credentials.client_id,
            client_secret=sample_oauth_credentials.client_secret,
            scopes=sample_oauth_credentials.scopes,
        )
        save_oauth_credentials(temp_user_client, "gmail", updated_creds)

        # Verify update
        creds = get_oauth_credentials(temp_user_client, config, "gmail")
        assert creds.token == "updated_token_xyz"

    def test_update_integration_status(
        self,
        config,
        sample_oauth_credentials,
        temp_user_client,
    ):
        """Can update integration status."""
        save_oauth_credentials(temp_user_client, "gmail", sample_oauth_credentials)

        # Update status to expired
        update_integration_status(temp_user_client, "gmail", "expired")

        # Credentials should return None for expired status
        creds = get_oauth_credentials(temp_user_client, config, "gmail")
        assert creds is None

    def test_update_oauth_credentials(
        self,
        config,
        sample_oauth_credentials,
        temp_user_client,
    ):
        """Can update OAuth tokens after refresh."""
        save_oauth_credentials(temp_user_client, "gmail", sample_oauth_credentials)

        # Simulate token refresh
        from datetime import datetime, timedelta, timezone

        from google.oauth2.credentials import Credentials

        refreshed_creds = Credentials(
            token="refreshed_token_abc",
            refresh_token=sample_oauth_credentials.refresh_token,
            token_uri=sample_oauth_credentials.token_uri,
            client_id=sample_oauth_credentials.client_id,
            client_secret=sample_oauth_credentials.client_secret,
            scopes=sample_oauth_credentials.scopes,
        )
        # Note: expiry is normally set by Google auth library
        # We can't easily set it on Credentials, but the update should work

        update_oauth_credentials(temp_user_client, "gmail", refreshed_creds)

        # Verify update
        creds = get_oauth_credentials(temp_user_client, config, "gmail")
        assert creds.token == "refreshed_token_abc"

    def test_scopes_stored_as_array(
        self,
        config,
        sample_oauth_credentials,
        temp_user_client,
    ):
        """Scopes are stored and retrieved as array."""
        save_oauth_credentials(temp_user_client, "gmail", sample_oauth_credentials)

        creds = get_oauth_credentials(temp_user_client, config, "gmail")
        assert creds.scopes == list(sample_oauth_credentials.scopes)

    def test_provider_email_stored(
        self,
        config,
        sample_oauth_credentials,
        temp_user,
        temp_user_client,
    ):
        """Provider email is stored with credentials."""
        user_id, email, password = temp_user
        
        save_oauth_credentials(
            temp_user_client,
            "gmail",
            sample_oauth_credentials,
            provider_email="myemail@gmail.com",
        )

        # Verify by direct query (provider_email not in Credentials object)
        result = (
            temp_user_client.table("integrations")
            .select("provider_email")
            .eq("user_id", user_id)
            .eq("provider", "gmail")
            .single()
            .execute()
        )
        assert result.data["provider_email"] == "myemail@gmail.com"

    def test_multiple_providers(
        self,
        config,
        sample_oauth_credentials,
        temp_user_client,
    ):
        """Can store credentials for multiple providers."""
        # Save Gmail
        save_oauth_credentials(temp_user_client, "gmail", sample_oauth_credentials)

        # Save Calendar with different token
        from google.oauth2.credentials import Credentials

        calendar_creds = Credentials(
            token="calendar_token",
            refresh_token="calendar_refresh",
            token_uri="https://oauth2.googleapis.com/token",
            client_id="test_client",
            client_secret="test_secret",
            scopes=["https://www.googleapis.com/auth/calendar"],
        )
        save_oauth_credentials(
            temp_user_client, "google_calendar", calendar_creds
        )

        # Verify both exist
        gmail = get_oauth_credentials(temp_user_client, config, "gmail")
        calendar = get_oauth_credentials(temp_user_client, config, "google_calendar")

        assert gmail is not None
        assert calendar is not None
        assert gmail.token != calendar.token


@pytest.mark.integration
@pytest.mark.staging
class TestOAuthIntegrationsStaging:
    """Test OAuth storage in staging environment."""

    def test_read_existing_credentials_staging(
        self,
        authenticated_client,
        config,
    ):
        """Can retrieve existing credentials from staging DB."""
        # Do NOT use cleanup_integrations - we're reading, not creating
        # This test expects real Gmail OAuth tokens from cli_auth_gmail
        creds = get_oauth_credentials(authenticated_client, config, "gmail")
        
        if creds is None:
            pytest.fail("No Gmail credentials in staging - run cli_auth_gmail first")
        
        assert creds.token is not None
        assert creds.refresh_token is not None
