"""Integration tests for OAuth integration storage.

Token columns on `integrations` are service-role-only: migration
`20260714000004_restrict_integration_token_columns.sql` revoked INSERT/UPDATE
and table-wide SELECT from `authenticated`, leaving column-level SELECT on
metadata plus DELETE for disconnect. Production writes credentials through the
service-role client (`api/routes/integrations.py` builds one for the OAuth
callback), so these tests do the same, and separately assert that an
authenticated session cannot reach the token columns.
"""

import pytest
from postgrest.exceptions import APIError

from selko.services.integrations import (
    delete_integration,
    get_oauth_credentials,
    save_oauth_credentials,
    update_integration_status,
    update_oauth_credentials,
)


def _credentials(token: str, sample, **overrides):
    """Build a Credentials object that differs from `sample` only by token."""
    from google.oauth2.credentials import Credentials

    fields = {
        "token": token,
        "refresh_token": sample.refresh_token,
        "token_uri": sample.token_uri,
        "client_id": sample.client_id,
        "client_secret": sample.client_secret,
        "scopes": sample.scopes,
    }
    fields.update(overrides)
    return Credentials(**fields)


@pytest.mark.integration
@pytest.mark.development
class TestOAuthIntegrations:
    """Service-role credential storage against real Supabase.

    `temp_user` is deleted after each test, cascading its integrations, so no
    explicit integration cleanup is needed.
    """

    def test_save_oauth_credentials(
        self, config, sample_oauth_credentials, admin_client, temp_user
    ):
        """Can save OAuth credentials to database."""
        user_id, _, _ = temp_user
        save_oauth_credentials(
            admin_client,
            user_id,
            "gmail",
            sample_oauth_credentials,
            provider_email="test@gmail.com",
        )

        creds = get_oauth_credentials(admin_client, config, "gmail", user_id=user_id)
        assert creds is not None
        assert creds.token == sample_oauth_credentials.token
        assert creds.refresh_token == sample_oauth_credentials.refresh_token

    def test_get_oauth_credentials_not_found(self, config, admin_client, temp_user):
        """Returns None when the user has no integration for that provider."""
        user_id, _, _ = temp_user

        creds = get_oauth_credentials(
            admin_client, config, "google_calendar", user_id=user_id
        )

        assert creds is None

    def test_save_credentials_upsert(
        self, config, sample_oauth_credentials, admin_client, temp_user
    ):
        """Saving credentials again updates the existing record."""
        user_id, _, _ = temp_user
        save_oauth_credentials(admin_client, user_id, "gmail", sample_oauth_credentials)
        save_oauth_credentials(
            admin_client,
            user_id,
            "gmail",
            _credentials("updated_token_xyz", sample_oauth_credentials),
        )

        creds = get_oauth_credentials(admin_client, config, "gmail", user_id=user_id)
        assert creds.token == "updated_token_xyz"

        rows = (
            admin_client.table("integrations")
            .select("id")
            .eq("user_id", user_id)
            .eq("provider", "gmail")
            .execute()
        )
        assert len(rows.data) == 1, "upsert must not create a second row"

    def test_update_integration_status(
        self, config, sample_oauth_credentials, admin_client, temp_user
    ):
        """A non-active status hides credentials from callers."""
        user_id, _, _ = temp_user
        save_oauth_credentials(admin_client, user_id, "gmail", sample_oauth_credentials)

        update_integration_status(admin_client, "gmail", "expired", user_id=user_id)

        creds = get_oauth_credentials(admin_client, config, "gmail", user_id=user_id)
        assert creds is None

    def test_update_oauth_credentials(
        self, config, sample_oauth_credentials, admin_client, temp_user
    ):
        """Can update OAuth tokens after a refresh."""
        user_id, _, _ = temp_user
        save_oauth_credentials(admin_client, user_id, "gmail", sample_oauth_credentials)

        update_oauth_credentials(
            admin_client,
            "gmail",
            _credentials("refreshed_token_abc", sample_oauth_credentials),
            user_id=user_id,
        )

        creds = get_oauth_credentials(admin_client, config, "gmail", user_id=user_id)
        assert creds.token == "refreshed_token_abc"

    def test_scopes_stored_as_array(
        self, config, sample_oauth_credentials, admin_client, temp_user
    ):
        """Scopes round-trip as an array."""
        user_id, _, _ = temp_user
        save_oauth_credentials(admin_client, user_id, "gmail", sample_oauth_credentials)

        creds = get_oauth_credentials(admin_client, config, "gmail", user_id=user_id)
        assert creds.scopes == list(sample_oauth_credentials.scopes)

    def test_provider_email_stored(
        self, sample_oauth_credentials, admin_client, temp_user
    ):
        """Provider email is stored alongside credentials."""
        user_id, _, _ = temp_user
        save_oauth_credentials(
            admin_client,
            user_id,
            "gmail",
            sample_oauth_credentials,
            provider_email="myemail@gmail.com",
        )

        result = (
            admin_client.table("integrations")
            .select("provider_email")
            .eq("user_id", user_id)
            .eq("provider", "gmail")
            .single()
            .execute()
        )
        assert result.data["provider_email"] == "myemail@gmail.com"

    def test_multiple_providers(
        self, config, sample_oauth_credentials, admin_client, temp_user
    ):
        """Credentials for different providers stay independent."""
        user_id, _, _ = temp_user
        save_oauth_credentials(admin_client, user_id, "gmail", sample_oauth_credentials)
        save_oauth_credentials(
            admin_client,
            user_id,
            "google_calendar",
            _credentials(
                "calendar_token",
                sample_oauth_credentials,
                refresh_token="calendar_refresh",
                scopes=["https://www.googleapis.com/auth/calendar"],
            ),
        )

        gmail = get_oauth_credentials(admin_client, config, "gmail", user_id=user_id)
        calendar = get_oauth_credentials(
            admin_client, config, "google_calendar", user_id=user_id
        )

        assert gmail is not None
        assert calendar is not None
        assert gmail.token != calendar.token


@pytest.mark.integration
@pytest.mark.development
class TestOAuthTokensAreServiceRoleOnly:
    """The privilege boundary from 20260714000004 is the point of that migration.

    These replace the older tests that wrote tokens as `authenticated` — a path
    production never takes and the database no longer permits.
    """

    def test_authenticated_session_cannot_read_token_columns(
        self, sample_oauth_credentials, admin_client, temp_user, temp_user_client
    ):
        """Owning the row must not grant access to its OAuth tokens."""
        user_id, _, _ = temp_user
        save_oauth_credentials(admin_client, user_id, "gmail", sample_oauth_credentials)

        with pytest.raises(APIError) as exc_info:
            temp_user_client.table("integrations").select("access_token").eq(
                "user_id", user_id
            ).execute()

        assert exc_info.value.code == "42501"

    def test_authenticated_session_can_read_its_own_metadata(
        self, sample_oauth_credentials, admin_client, temp_user, temp_user_client
    ):
        """Frontends still list integrations; only token columns are withheld."""
        user_id, _, _ = temp_user
        save_oauth_credentials(
            admin_client,
            user_id,
            "gmail",
            sample_oauth_credentials,
            provider_email="visible@gmail.com",
        )

        result = (
            temp_user_client.table("integrations")
            .select("id,provider,status,provider_email")
            .eq("user_id", user_id)
            .single()
            .execute()
        )

        assert result.data["provider"] == "gmail"
        assert result.data["provider_email"] == "visible@gmail.com"

    def test_authenticated_session_cannot_write_tokens(
        self, sample_oauth_credentials, admin_client, temp_user, temp_user_client
    ):
        """INSERT/UPDATE on integrations is service-role-only."""
        user_id, _, _ = temp_user
        save_oauth_credentials(admin_client, user_id, "gmail", sample_oauth_credentials)

        with pytest.raises(APIError) as exc_info:
            temp_user_client.table("integrations").update(
                {"access_token": "stolen"}
            ).eq("user_id", user_id).execute()

        assert exc_info.value.code == "42501"

    def test_authenticated_session_can_still_disconnect(
        self, sample_oauth_credentials, admin_client, temp_user, temp_user_client
    ):
        """DELETE is deliberately retained so users can disconnect.

        Regression: postgrest-py requests `return=representation` by default,
        which needs SELECT on every column and is therefore denied under the
        column-level grant. Disconnect must not echo the deleted row.
        """
        user_id, _, _ = temp_user
        save_oauth_credentials(admin_client, user_id, "gmail", sample_oauth_credentials)

        delete_integration(temp_user_client, "gmail")

        remaining = (
            admin_client.table("integrations")
            .select("id")
            .eq("user_id", user_id)
            .execute()
        )
        assert remaining.data == []


@pytest.mark.integration
@pytest.mark.staging
class TestOAuthIntegrationsStaging:
    """Test OAuth storage in staging environment."""

    def test_read_existing_credentials_staging(self, admin_client, test_user_id, config):
        """Can retrieve existing credentials from staging DB."""
        creds = get_oauth_credentials(
            admin_client, config, "gmail", user_id=test_user_id
        )

        if creds is None:
            pytest.skip(
                "No Gmail credentials in staging; run "
                "'ENVIRONMENT=staging uv run python -m cli.cli_auth_gmail' to populate them"
            )

        assert creds.token is not None
        assert creds.refresh_token is not None
