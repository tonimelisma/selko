"""Tests for integration service."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from selko.services.integrations import (
    IntegrationError,
    OAuthProviderNotAllowed,
    OAuthStateError,
    _validate_and_consume_oauth_state,
    _save_oauth_state,
    claim_integration_recovery,
    complete_integration_reauthorization,
    complete_oauth_flow,
    get_oauth_credentials,
    initiate_oauth_flow,
    save_oauth_credentials,
    save_provider_tokens,
    unlock_expired_integration_recoveries,
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

        # Credentials must go through the atomic reauthorization RPC, not a
        # direct table upsert, so recovery scheduling can never be skipped.
        mock_supabase_client.rpc.assert_called_once_with(
            "complete_integration_reauthorization",
            {
                "p_user_id": "test-user-id",
                "p_provider": "gmail",
                "p_access_token": "access-token",
                "p_refresh_token": "refresh-token",
                "p_token_expiry": "2026-01-22T12:00:00+00:00",
                "p_scopes": ["gmail.readonly"],
                "p_provider_email": "test@gmail.com",
            },
        )

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

        rpc_call = mock_supabase_client.rpc.call_args
        params = rpc_call[0][1]

        assert params["p_token_expiry"] is None

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

        rpc_call = mock_supabase_client.rpc.call_args
        params = rpc_call[0][1]

        assert params["p_scopes"] == []


class TestSaveProviderTokens:
    """Non-Google (Outlook) token storage also goes through the atomic RPC."""

    def test_saves_via_reauthorization_rpc(self, mock_supabase_client):
        save_provider_tokens(
            mock_supabase_client,
            "test-user-id",
            provider="outlook",
            token_result={
                "access_token": "outlook-access",
                "refresh_token": "outlook-refresh",
                "expires_in": 3600,
                "scope": "Mail.Read offline_access",
            },
            provider_email="test@outlook.com",
        )

        rpc_call = mock_supabase_client.rpc.call_args
        assert rpc_call[0][0] == "complete_integration_reauthorization"
        params = rpc_call[0][1]
        assert params["p_provider"] == "outlook"
        assert params["p_access_token"] == "outlook-access"
        assert params["p_refresh_token"] == "outlook-refresh"
        assert params["p_scopes"] == ["Mail.Read", "offline_access"]
        assert params["p_provider_email"] == "test@outlook.com"

    def test_requires_access_token(self, mock_supabase_client):
        with pytest.raises(IntegrationError):
            save_provider_tokens(
                mock_supabase_client,
                "test-user-id",
                provider="outlook",
                token_result={},
            )


class TestCompleteIntegrationReauthorization:
    """Direct coverage of the RPC wrapper itself."""

    def test_returns_integration_id_from_rpc(self, mock_supabase_client):
        mock_supabase_client.rpc.return_value.execute.return_value = MagicMock(
            data="integration-123"
        )

        result = complete_integration_reauthorization(
            mock_supabase_client,
            user_id="test-user-id",
            provider="google_calendar",
            access_token="access-token",
            refresh_token="refresh-token",
            token_expiry=None,
            scopes=["calendar"],
            provider_email=None,
        )

        assert result == "integration-123"
        mock_supabase_client.rpc.assert_called_once_with(
            "complete_integration_reauthorization",
            {
                "p_user_id": "test-user-id",
                "p_provider": "google_calendar",
                "p_access_token": "access-token",
                "p_refresh_token": "refresh-token",
                "p_token_expiry": None,
                "p_scopes": ["calendar"],
                "p_provider_email": None,
            },
        )

    def test_wraps_rpc_failure(self, mock_supabase_client):
        from postgrest.exceptions import APIError

        mock_supabase_client.rpc.return_value.execute.side_effect = APIError(
            {"message": "boom"}
        )

        with pytest.raises(IntegrationError):
            complete_integration_reauthorization(
                mock_supabase_client,
                user_id="test-user-id",
                provider="gmail",
                access_token="access-token",
                refresh_token=None,
                token_expiry=None,
                scopes=[],
                provider_email=None,
            )


class TestIntegrationRecoveryClaiming:
    """RPC wrappers for the recovery worker stage (claim/unlock)."""

    def test_claim_returns_first_row(self, mock_supabase_client):
        mock_supabase_client.rpc.return_value.execute.return_value = MagicMock(
            data=[{"id": "recovery-1", "status": "processing"}]
        )

        claimed = claim_integration_recovery(mock_supabase_client, "worker-1")

        assert claimed == {"id": "recovery-1", "status": "processing"}
        mock_supabase_client.rpc.assert_called_once_with(
            "claim_integration_recovery",
            {"p_worker_id": "worker-1", "p_lock_seconds": 300},
        )

    def test_claim_returns_none_when_nothing_pending(self, mock_supabase_client):
        mock_supabase_client.rpc.return_value.execute.return_value = MagicMock(data=[])

        assert claim_integration_recovery(mock_supabase_client, "worker-1") is None

    def test_unlock_returns_count(self, mock_supabase_client):
        mock_supabase_client.rpc.return_value.execute.return_value = MagicMock(data=3)

        assert unlock_expired_integration_recoveries(mock_supabase_client) == 3


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
            code_verifier="pkce-verifier-abc",
        )

        # Verify insert was called
        mock_client.table.assert_called_with("oauth_states")
        insert_call = mock_client.table().insert.call_args
        data = insert_call[0][0]

        assert data["state"] == "test-state-token"
        assert data["user_id"] == "user-123"
        assert data["provider"] == "gmail"
        assert data["redirect_uri"] == "http://localhost:8000/integrations/google/callback"
        assert data["code_verifier"] == "pkce-verifier-abc"

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
                "code_verifier": "pkce-verifier-xyz",
                "expires_at": future_expiry,
            }
        )

        result = _validate_and_consume_oauth_state("valid-state")

        assert result["user_id"] == "user-123"
        assert result["provider"] == "gmail"
        assert result["redirect_uri"] == "http://localhost:8000/integrations/google/callback"
        assert result["code_verifier"] == "pkce-verifier-xyz"

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
        mock_flow.code_verifier = "generated-pkce-verifier"
        mock_flow_class.from_client_config.return_value = mock_flow

        result = initiate_oauth_flow(
            config=mock_config,
            provider="gmail",
            user_id="user-123",
            redirect_uri="http://localhost:8000/integrations/google/callback",
        )

        assert "auth_url" in result
        assert "state" in result

        # Verify state was saved to DB with PKCE verifier
        mock_save_state.assert_called_once()
        call_args = mock_save_state.call_args
        # _save_oauth_state(state, user_id, provider, redirect_uri, code_verifier=...)
        assert call_args[0][1] == "user-123"
        assert call_args[0][2] == "gmail"
        assert call_args.kwargs.get("code_verifier") == "generated-pkce-verifier"
        mock_flow_class.from_client_config.assert_called_once()
        assert mock_flow_class.from_client_config.call_args.kwargs.get(
            "autogenerate_code_verifier"
        ) is True

    @patch("selko.services.integrations._clean_expired_oauth_states")
    @patch("selko.services.integrations._save_oauth_state")
    @patch("selko.services.integrations.Flow")
    def test_initiate_requires_code_verifier(self, mock_flow_class, mock_save_state, mock_cleanup, mock_config):
        """Initiate must fail closed if PKCE verifier was not generated."""
        mock_flow = MagicMock()
        mock_flow.authorization_url.return_value = ("https://accounts.google.com/oauth?...", "state")
        mock_flow.code_verifier = None
        mock_flow_class.from_client_config.return_value = mock_flow

        with pytest.raises(IntegrationError, match="code_verifier"):
            initiate_oauth_flow(
                config=mock_config,
                provider="gmail",
                user_id="user-123",
                redirect_uri="http://localhost:8000/integrations/google/callback",
            )

        mock_save_state.assert_not_called()

    @patch("selko.services.integrations._clean_expired_oauth_states")
    @patch("selko.services.integrations._save_oauth_state")
    @patch("selko.services.integrations.Flow")
    def test_initiate_cleans_expired_states(self, mock_flow_class, mock_save_state, mock_cleanup, mock_config):
        """Test that initiation triggers expired state cleanup."""
        mock_flow = MagicMock()
        mock_flow.authorization_url.return_value = ("https://accounts.google.com/oauth?...", "state")
        mock_flow.code_verifier = "generated-pkce-verifier"
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
            "code_verifier": "persisted-pkce-verifier",
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
        mock_flow_class.from_client_config.assert_called_once()
        flow_kwargs = mock_flow_class.from_client_config.call_args.kwargs
        assert flow_kwargs.get("code_verifier") == "persisted-pkce-verifier"
        assert flow_kwargs.get("autogenerate_code_verifier") is False
        mock_flow.fetch_token.assert_called_once_with(code="auth-code-123")

    @patch("selko.services.integrations._validate_and_consume_oauth_state")
    def test_complete_requires_persisted_code_verifier(self, mock_validate, mock_config):
        """Regression: missing PKCE verifier must fail before token exchange."""
        mock_validate.return_value = {
            "user_id": "user-123",
            "provider": "gmail",
            "redirect_uri": "http://localhost:8000/integrations/google/callback",
            "code_verifier": None,
        }

        with pytest.raises(IntegrationError, match="code_verifier"):
            complete_oauth_flow(
                config=mock_config,
                code="auth-code-123",
                state="test-state",
            )

    @patch("selko.services.integrations._validate_and_consume_oauth_state")
    @patch("selko.services.integrations.Flow")
    def test_rejected_provider_does_not_exchange_code(
        self, mock_flow_class, mock_validate, mock_config
    ):
        """Regression: callback provider rejection must precede token exchange."""
        mock_validate.return_value = {
            "user_id": "user-123",
            "provider": "google_photos",
            "redirect_uri": "http://localhost:8000/integrations/google/callback",
            "code_verifier": "persisted-pkce-verifier",
        }

        with pytest.raises(OAuthProviderNotAllowed, match="google_photos"):
            complete_oauth_flow(
                config=mock_config,
                code="auth-code-123",
                state="test-state",
                allowed_providers={"gmail", "google_calendar"},
            )

        mock_flow_class.from_client_config.assert_not_called()

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
