"""Tests for integration service."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from selko.services.integrations import (
    IntegrationError,
    OAuthStateError,
    _validate_and_consume_oauth_state,
    _save_oauth_state,
    complete_oauth_flow,
    get_oauth_credentials,
    initiate_oauth_flow,
    save_oauth_credentials,
)


class TestSaveOAuthCredentials:
    """Test OAuth credential storage."""

    def test_saves_all_fields(self, mock_supabase_client):
        """Verify all credential fields are saved."""
        creds = MagicMock()
        creds.token = "access-token"
        creds.refresh_token = "refresh-token"
        creds.expiry = datetime(2026, 1, 22, 12, 0, 0, tzinfo=timezone.utc)
        creds.scopes = ["gmail.readonly"]

        save_oauth_credentials(
            mock_supabase_client,
            "test-user-id",
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
        creds = MagicMock()
        creds.token = "access-token"
        creds.refresh_token = "refresh-token"
        creds.expiry = None
        creds.scopes = []

        save_oauth_credentials(
            mock_supabase_client,
            "test-user-id",
            provider="gmail",
            credentials=creds,
        )

        upsert_call = mock_supabase_client.table().upsert.call_args
        data = upsert_call[0][0]

        assert data["token_expiry"] is None

    def test_handles_none_scopes(self, mock_supabase_client):
        """Handle credentials with no scopes."""
        creds = MagicMock()
        creds.token = "access-token"
        creds.refresh_token = None
        creds.expiry = None
        creds.scopes = None

        save_oauth_credentials(
            mock_supabase_client,
            "test-user-id",
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


class TestOAuthStateError:
    """Test OAuthStateError exception class."""

    def test_is_integration_error_subclass(self):
        """OAuthStateError should be a subclass of IntegrationError."""
        error = OAuthStateError("test")
        assert isinstance(error, IntegrationError)
        assert isinstance(error, OAuthStateError)

    def test_message(self):
        """OAuthStateError stores the message."""
        error = OAuthStateError("Invalid state")
        assert str(error) == "Invalid state"


class TestOAuthStateDB:
    """Test DB-backed OAuth state management."""

    @patch("selko.services.integrations._get_service_client_for_oauth")
    def test_save_oauth_state(self, mock_get_client):
        """Test saving OAuth state to database."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        _save_oauth_state(
            state="test-state-token",
            user_id="user-123",
            provider="gmail",
            redirect_uri="http://localhost:8000/integrations/google/callback",
        )

        # Verify insert was called
        mock_client.table.assert_called_with("oauth_states")
        insert_call = mock_client.table().insert.call_args
        data = insert_call[0][0]

        assert data["state"] == "test-state-token"
        assert data["user_id"] == "user-123"
        assert data["provider"] == "gmail"
        assert data["redirect_uri"] == "http://localhost:8000/integrations/google/callback"

    @patch("selko.services.integrations._get_service_client_for_oauth")
    def test_validate_and_consume_valid_state(self, mock_get_client):
        """Test validating a valid, non-expired state."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # State data with future expiry
        future_expiry = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        mock_client.table().select().eq().maybe_single().execute.return_value = MagicMock(
            data={
                "state": "valid-state",
                "user_id": "user-123",
                "provider": "gmail",
                "redirect_uri": "http://localhost:8000/integrations/google/callback",
                "expires_at": future_expiry,
            }
        )

        result = _validate_and_consume_oauth_state("valid-state")

        assert result["user_id"] == "user-123"
        assert result["provider"] == "gmail"
        assert result["redirect_uri"] == "http://localhost:8000/integrations/google/callback"

        # Verify state was deleted (consumed)
        mock_client.table().delete().eq.assert_called_with("state", "valid-state")

    @patch("selko.services.integrations._get_service_client_for_oauth")
    def test_validate_expired_state_raises(self, mock_get_client):
        """Test that expired state raises OAuthStateError."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        # State data with past expiry
        past_expiry = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
        mock_client.table().select().eq().maybe_single().execute.return_value = MagicMock(
            data={
                "state": "expired-state",
                "user_id": "user-123",
                "provider": "gmail",
                "redirect_uri": "http://localhost:8000/callback",
                "expires_at": past_expiry,
            }
        )

        with pytest.raises(OAuthStateError, match="expired"):
            _validate_and_consume_oauth_state("expired-state")

    @patch("selko.services.integrations._get_service_client_for_oauth")
    def test_validate_missing_state_raises(self, mock_get_client):
        """Test that missing state raises OAuthStateError."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        mock_client.table().select().eq().maybe_single().execute.return_value = MagicMock(
            data=None
        )

        with pytest.raises(OAuthStateError, match="Invalid or expired"):
            _validate_and_consume_oauth_state("nonexistent-state")

    @patch("selko.services.integrations._get_service_client_for_oauth")
    def test_state_is_consumed_after_use(self, mock_get_client):
        """State should be deleted from DB after successful validation."""
        mock_client = MagicMock()
        mock_get_client.return_value = mock_client

        future_expiry = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
        mock_client.table().select().eq().maybe_single().execute.return_value = MagicMock(
            data={
                "state": "one-time-state",
                "user_id": "user-123",
                "provider": "gmail",
                "redirect_uri": "http://localhost:8000/callback",
                "expires_at": future_expiry,
            }
        )

        _validate_and_consume_oauth_state("one-time-state")

        # Verify delete was called to consume the state
        delete_chain = mock_client.table().delete()
        delete_chain.eq.assert_called_with("state", "one-time-state")


class TestInitiateOAuthFlow:
    """Test OAuth flow initiation with DB-backed state."""

    @patch("selko.services.integrations._clean_expired_oauth_states")
    @patch("selko.services.integrations._save_oauth_state")
    @patch("selko.services.integrations.Flow")
    def test_initiate_stores_state_in_db(self, mock_flow_class, mock_save_state, mock_cleanup, mock_config):
        """Test that initiate_oauth_flow saves state to DB."""
        # Set up Flow mock
        mock_flow = MagicMock()
        mock_flow.authorization_url.return_value = ("https://accounts.google.com/oauth?...", "state")
        mock_flow_class.from_client_config.return_value = mock_flow

        result = initiate_oauth_flow(
            config=mock_config,
            provider="gmail",
            user_id="user-123",
            redirect_uri="http://localhost:8000/integrations/google/callback",
        )

        assert "auth_url" in result
        assert "state" in result

        # Verify state was saved to DB
        mock_save_state.assert_called_once()
        call_args = mock_save_state.call_args
        # _save_oauth_state(state, user_id, provider, redirect_uri) — positional
        assert call_args[0][1] == "user-123"
        assert call_args[0][2] == "gmail"

    @patch("selko.services.integrations._clean_expired_oauth_states")
    @patch("selko.services.integrations._save_oauth_state")
    @patch("selko.services.integrations.Flow")
    def test_initiate_cleans_expired_states(self, mock_flow_class, mock_save_state, mock_cleanup, mock_config):
        """Test that initiation triggers expired state cleanup."""
        mock_flow = MagicMock()
        mock_flow.authorization_url.return_value = ("https://accounts.google.com/oauth?...", "state")
        mock_flow_class.from_client_config.return_value = mock_flow

        initiate_oauth_flow(
            config=mock_config,
            provider="gmail",
            user_id="user-123",
            redirect_uri="http://localhost:8000/integrations/google/callback",
        )

        mock_cleanup.assert_called_once()

    def test_initiate_rejects_unsupported_provider(self, mock_config):
        """Test that unsupported provider raises IntegrationError."""
        with pytest.raises(IntegrationError, match="Unsupported provider"):
            initiate_oauth_flow(
                config=mock_config,
                provider="invalid_provider",
                user_id="user-123",
                redirect_uri="http://localhost:8000/callback",
            )


class TestCompleteOAuthFlow:
    """Test OAuth flow completion with DB-backed state."""

    @patch("selko.services.integrations._validate_and_consume_oauth_state")
    @patch("selko.services.integrations.Flow")
    def test_complete_validates_state_from_db(self, mock_flow_class, mock_validate, mock_config):
        """Test that complete_oauth_flow validates state from DB."""
        mock_validate.return_value = {
            "user_id": "user-123",
            "provider": "gmail",
            "redirect_uri": "http://localhost:8000/integrations/google/callback",
        }

        mock_flow = MagicMock()
        mock_creds = MagicMock()
        mock_flow.credentials = mock_creds
        mock_flow_class.from_client_config.return_value = mock_flow

        credentials, user_id, provider = complete_oauth_flow(
            config=mock_config,
            code="auth-code-123",
            state="test-state",
        )

        assert user_id == "user-123"
        assert provider == "gmail"
        assert credentials == mock_creds
        mock_validate.assert_called_once_with("test-state")

    @patch("selko.services.integrations._validate_and_consume_oauth_state")
    def test_complete_raises_on_invalid_state(self, mock_validate, mock_config):
        """Test that invalid state raises OAuthStateError."""
        mock_validate.side_effect = OAuthStateError("Invalid or expired state parameter")

        with pytest.raises(OAuthStateError, match="Invalid or expired"):
            complete_oauth_flow(
                config=mock_config,
                code="auth-code-123",
                state="bad-state",
            )


class TestGetCredentialsPassesUserId:
    """integrations.get_credentials must pass user_id for service-role workers."""

    @patch("selko.services.integrations.get_oauth_credentials")
    @patch("selko.config.load_config")
    def test_passes_user_id(self, mock_load_config, mock_get_oauth):
        from selko.services.integrations import get_credentials

        mock_load_config.return_value = MagicMock()
        mock_creds = MagicMock()
        mock_creds.expired = False
        mock_get_oauth.return_value = mock_creds

        client = MagicMock()
        result = get_credentials(client, "user-abc", "google_calendar")

        assert result is mock_creds
        mock_get_oauth.assert_called_once_with(
            client, mock_load_config.return_value, "google_calendar", user_id="user-abc"
        )
