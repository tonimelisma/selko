"""Tests for integration service."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


class TestSaveOAuthCredentials:
    """Test OAuth credential storage."""

    def test_saves_all_fields(self, mock_supabase_client):
        """Verify all credential fields are saved."""
        from selko.services.integrations import save_oauth_credentials

        creds = MagicMock()
        creds.token = "access-token"
        creds.refresh_token = "refresh-token"
        creds.expiry = datetime(2026, 1, 22, 12, 0, 0, tzinfo=timezone.utc)
        creds.scopes = ["gmail.readonly"]

        with patch(
            "selko.services.integrations.get_current_user_id",
            return_value="test-user-id",
        ):
            save_oauth_credentials(
                mock_supabase_client,
                provider="gmail",
                credentials=creds,
                provider_email="test@gmail.com",
            )

        # Verify upsert was called
        mock_supabase_client.table.assert_called_with("integrations")
        upsert_call = mock_supabase_client.table().upsert.call_args
        data = upsert_call[0][0]

        assert data["access_token"] == "access-token"
        assert data["refresh_token"] == "refresh-token"
        assert data["provider"] == "gmail"
        assert data["provider_email"] == "test@gmail.com"
        assert data["user_id"] == "test-user-id"
        assert data["status"] == "active"
        assert "gmail.readonly" in data["scopes"]

    def test_handles_none_expiry(self, mock_supabase_client):
        """Handle credentials with no expiry set."""
        from selko.services.integrations import save_oauth_credentials

        creds = MagicMock()
        creds.token = "access-token"
        creds.refresh_token = "refresh-token"
        creds.expiry = None
        creds.scopes = []

        with patch(
            "selko.services.integrations.get_current_user_id",
            return_value="test-user-id",
        ):
            save_oauth_credentials(
                mock_supabase_client,
                provider="gmail",
                credentials=creds,
            )

        upsert_call = mock_supabase_client.table().upsert.call_args
        data = upsert_call[0][0]

        assert data["token_expiry"] is None

    def test_handles_none_scopes(self, mock_supabase_client):
        """Handle credentials with no scopes."""
        from selko.services.integrations import save_oauth_credentials

        creds = MagicMock()
        creds.token = "access-token"
        creds.refresh_token = None
        creds.expiry = None
        creds.scopes = None

        with patch(
            "selko.services.integrations.get_current_user_id",
            return_value="test-user-id",
        ):
            save_oauth_credentials(
                mock_supabase_client,
                provider="gmail",
                credentials=creds,
            )

        upsert_call = mock_supabase_client.table().upsert.call_args
        data = upsert_call[0][0]

        assert data["scopes"] == []


class TestGetOAuthCredentials:
    """Test OAuth credential retrieval."""

    def test_returns_none_when_not_found(self, mock_supabase_client, mock_config):
        """Return None when no integration exists."""
        from selko.services.integrations import get_oauth_credentials

        mock_supabase_client.table().select().eq().eq().maybe_single().execute.return_value = MagicMock(
            data=None
        )

        with patch(
            "selko.services.integrations.get_current_user_id",
            return_value="test-user-id",
        ):
            result = get_oauth_credentials(
                mock_supabase_client, mock_config, "gmail"
            )

        assert result is None

    def test_returns_none_when_revoked(self, mock_supabase_client, mock_config):
        """Return None when integration is revoked."""
        from selko.services.integrations import get_oauth_credentials

        mock_supabase_client.table().select().eq().eq().maybe_single().execute.return_value = MagicMock(
            data={"status": "revoked", "access_token": "token"}
        )

        with patch(
            "selko.services.integrations.get_current_user_id",
            return_value="test-user-id",
        ):
            result = get_oauth_credentials(
                mock_supabase_client, mock_config, "gmail"
            )

        assert result is None

    def test_returns_none_when_error_status(self, mock_supabase_client, mock_config):
        """Return None when integration has error status."""
        from selko.services.integrations import get_oauth_credentials

        mock_supabase_client.table().select().eq().eq().maybe_single().execute.return_value = MagicMock(
            data={"status": "error", "access_token": "token"}
        )

        with patch(
            "selko.services.integrations.get_current_user_id",
            return_value="test-user-id",
        ):
            result = get_oauth_credentials(
                mock_supabase_client, mock_config, "gmail"
            )

        assert result is None
