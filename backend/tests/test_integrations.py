"""Tests for the integration service, over a real SQLite database.

The database is never stubbed (docs/specs/sqlite-single-process/05-verification.md
§A.1 row 39): credentials, OAuth states and recoveries are written and read
back through ``selko.db``. Only Google's OAuth library is mocked.
"""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from selko.db import runtime
from selko.services.integrations import (
    IntegrationError,
    OAuthProviderNotAllowed,
    OAuthStateError,
    _clean_expired_oauth_states,
    _validate_and_consume_oauth_state,
    _save_oauth_state,
    claim_integration_recovery,
    complete_integration_reauthorization,
    complete_oauth_flow,
    delete_integration,
    get_oauth_credentials,
    get_provider_integration,
    initiate_oauth_flow,
    save_oauth_credentials,
    save_provider_tokens,
    unlock_expired_integration_recoveries,
    update_integration_status,
    update_oauth_credentials,
    update_provider_tokens,
)


@pytest.fixture
def process_db(db):
    """Install the test database as the process database (OAuth state helpers use it)."""
    runtime.use_database(db)
    yield db
    runtime.use_database(None)


def _creds(token="access-token", refresh="refresh-token", expiry=None, scopes=("gmail.readonly",)):
    creds = MagicMock()
    creds.token = token
    creds.refresh_token = refresh
    creds.expiry = expiry
    creds.scopes = list(scopes) if scopes is not None else None
    return creds


def _recoveries(db, user):
    return [dict(r) for r in db.query(
        "SELECT * FROM integration_recoveries WHERE user_id = ? ORDER BY requested_at", (user,)
    )]


class TestSaveOAuthCredentials:
    """Credentials go through complete_integration_reauthorization, never a bare upsert."""

    def test_saves_all_fields(self, db, factory):
        user = factory.user()
        creds = _creds(expiry=datetime(2026, 1, 22, 12, 0, 0, tzinfo=timezone.utc))

        save_oauth_credentials(db, user, provider="gmail", credentials=creds,
                               provider_email="test@gmail.com")

        row = get_provider_integration(db, "gmail", user_id=user)
        assert row["status"] == "active"
        assert row["access_token"] == "access-token"
        assert row["refresh_token"] == "refresh-token"
        assert row["token_expiry"] == "2026-01-22T12:00:00.000000Z"
        assert row["scopes"] == ["gmail.readonly"]
        assert row["provider_email"] == "test@gmail.com"

    def test_naive_expiry_is_read_as_utc(self, db, factory):
        """google-auth hands back naive UTC expiries."""
        user = factory.user()
        save_oauth_credentials(db, user, "gmail", _creds(expiry=datetime(2026, 1, 22, 12, 0, 0)))
        assert get_provider_integration(db, "gmail", user_id=user)["token_expiry"] == "2026-01-22T12:00:00.000000Z"

    def test_handles_none_expiry(self, db, factory):
        user = factory.user()
        save_oauth_credentials(db, user, provider="gmail", credentials=_creds(scopes=()))
        assert get_provider_integration(db, "gmail", user_id=user)["token_expiry"] is None

    def test_handles_none_scopes(self, db, factory):
        user = factory.user()
        save_oauth_credentials(db, user, "gmail", _creds(refresh=None, scopes=None))
        assert get_provider_integration(db, "gmail", user_id=user)["scopes"] == []

    # Validates: SEL-456
    def test_reconnect_keeps_the_stored_refresh_token(self, db, factory):
        user = factory.user()
        save_oauth_credentials(db, user, "gmail", _creds(refresh="first"))
        save_oauth_credentials(db, user, "gmail", _creds(token="new-access", refresh=None))
        row = get_provider_integration(db, "gmail", user_id=user)
        assert row["access_token"] == "new-access"
        assert row["refresh_token"] == "first"

    def test_calendar_grant_schedules_a_recovery(self, db, factory):
        user = factory.user()
        save_oauth_credentials(db, user, "google_calendar", _creds(scopes=("calendar",)))
        assert [r["status"] for r in _recoveries(db, user)] == ["pending"]

    def test_gmail_grant_schedules_no_recovery(self, db, factory):
        user = factory.user()
        save_oauth_credentials(db, user, "gmail", _creds())
        assert _recoveries(db, user) == []

    def test_activating_gmail_creates_its_sync_state(self, db, factory):
        user = factory.user()
        integration_id = complete_integration_reauthorization(
            db, user, "gmail", "a", None, None, [], None
        )
        state = db.query_one("SELECT * FROM email_sync_state WHERE integration_id = ?", (integration_id,))
        assert state is not None and state["provider"] == "gmail"


class TestSaveProviderTokens:
    """Non-Google (Outlook) token storage also goes through reauthorization."""

    def test_saves_via_reauthorization(self, db, factory):
        user = factory.user()
        before = datetime.now(timezone.utc)
        save_provider_tokens(
            db, user, provider="outlook",
            token_result={
                "access_token": "outlook-access",
                "refresh_token": "outlook-refresh",
                "expires_in": 3600,
                "scope": "Mail.Read offline_access",
            },
            provider_email="test@outlook.com",
        )
        row = get_provider_integration(db, "outlook", user_id=user)
        assert row["access_token"] == "outlook-access"
        assert row["refresh_token"] == "outlook-refresh"
        assert row["scopes"] == ["Mail.Read", "offline_access"]
        assert row["provider_email"] == "test@outlook.com"
        expiry = datetime.fromisoformat(row["token_expiry"].replace("Z", "+00:00"))
        assert before + timedelta(seconds=3590) < expiry < before + timedelta(seconds=3700)
        assert _recoveries(db, user) == [], "a mail-only grant is not a calendar"

    def test_outlook_calendar_grant_schedules_a_recovery(self, db, factory):
        user = factory.user()
        save_provider_tokens(db, user, "outlook", {
            "access_token": "a", "scope": "Mail.Read https://graph.microsoft.com/Calendars.ReadWrite",
        })
        assert [r["provider"] for r in _recoveries(db, user)] == ["outlook"]

    def test_requires_access_token(self, db, factory):
        with pytest.raises(IntegrationError):
            save_provider_tokens(db, factory.user(), provider="outlook", token_result={})


class TestCompleteIntegrationReauthorization:
    def test_returns_the_integration_id(self, db, factory):
        user = factory.user()
        result = complete_integration_reauthorization(
            db, user_id=user, provider="google_calendar", access_token="access-token",
            refresh_token="refresh-token", token_expiry=None, scopes=["calendar"],
            provider_email=None,
        )
        assert result == get_provider_integration(db, "google_calendar", user_id=user)["id"]

    def test_repeat_supersedes_the_previous_recovery(self, db, factory):
        user = factory.user()
        for _ in range(2):
            complete_integration_reauthorization(db, user, "google_calendar", "a", None, None, [], None)
        assert [r["status"] for r in _recoveries(db, user)] == ["superseded", "pending"]

    def test_wraps_database_failure(self, db):
        """An unknown user violates the foreign key: wrapped, nothing saved."""
        with pytest.raises(IntegrationError):
            complete_integration_reauthorization(
                db, user_id="00000000-0000-0000-0000-000000000000", provider="gmail",
                access_token="access-token", refresh_token=None, token_expiry=None,
                scopes=[], provider_email=None,
            )

    def test_unknown_provider_is_refused(self, db, factory):
        with pytest.raises(IntegrationError):
            complete_integration_reauthorization(db, factory.user(), "dropbox", "a", None, None, [], None)


class TestIntegrationRecoveryClaiming:
    """The recovery worker stage's claim/unlock, run through db.run."""

    def test_claim_leases_the_pending_recovery(self, db, factory):
        user = factory.user()
        complete_integration_reauthorization(db, user, "google_calendar", "a", None, None, [], None)

        claimed = asyncio.run(claim_integration_recovery(db, "worker-1"))

        assert claimed["status"] == "processing"
        assert claimed["locked_by"] == "worker-1"
        assert claimed["attempts"] == 1
        assert asyncio.run(claim_integration_recovery(db, "worker-2")) is None, "held by worker-1"

    def test_claim_returns_none_when_nothing_pending(self, db):
        assert asyncio.run(claim_integration_recovery(db, "worker-1")) is None

    def test_unlock_returns_expired_claims_to_pending(self, db, factory):
        user = factory.user()
        complete_integration_reauthorization(db, user, "google_calendar", "a", None, None, [], None)
        asyncio.run(claim_integration_recovery(db, "worker-1", lock_seconds=1))
        assert asyncio.run(unlock_expired_integration_recoveries(db)) == 0, "lease still live"
        with db.write() as tx:
            tx.execute("UPDATE integration_recoveries SET locked_until = ?", (tx.ts(-60),))

        assert asyncio.run(unlock_expired_integration_recoveries(db)) == 1
        assert _recoveries(db, user)[0]["status"] == "pending"

    def test_claim_failure_is_wrapped(self):
        class Broken:
            async def run(self, *args, **kwargs):
                raise RuntimeError("disk gone")

        with pytest.raises(IntegrationError):
            asyncio.run(claim_integration_recovery(Broken(), "worker-1"))


class TestGetOAuthCredentials:
    """Credential retrieval reads the user's own row only."""

    def test_returns_none_when_not_found(self, db, factory, mock_config):
        assert get_oauth_credentials(db, mock_config, "gmail", user_id=factory.user()) is None

    @pytest.mark.parametrize("status", ["revoked", "error", "expired"])
    def test_returns_none_when_not_active(self, db, factory, mock_config, status):
        user = factory.user()
        factory.integration(user, "gmail", status=status)
        assert get_oauth_credentials(db, mock_config, "gmail", user_id=user) is None

    def test_rebuilds_refreshable_credentials(self, db, factory, mock_config):
        user = factory.user()
        factory.integration(user, "gmail", refresh_token="r1", scopes=["s1"],
                            token_expiry="2026-01-22T12:00:00.000000Z")
        creds = get_oauth_credentials(db, mock_config, "gmail", user_id=user)
        assert creds.token == "test-access-token"
        assert creds.refresh_token == "r1"
        assert creds.client_id == mock_config.google_client_id
        assert list(creds.scopes) == ["s1"]
        assert creds.expiry == datetime(2026, 1, 22, 12, 0, 0), "naive UTC for google-auth"

    def test_never_reads_another_users_row(self, db, factory, mock_config):
        alice, bob = factory.user(), factory.user()
        factory.integration(alice, "gmail")
        assert get_oauth_credentials(db, mock_config, "gmail", user_id=bob) is None

    def test_requires_a_user(self, db, mock_config):
        with pytest.raises(IntegrationError, match="user_id"):
            get_oauth_credentials(db, mock_config, "gmail")


class TestIntegrationWrites:
    def test_status_update_is_scoped_to_the_user(self, db, factory):
        alice, bob = factory.user(), factory.user()
        factory.integration(alice, "gmail")
        factory.integration(bob, "gmail")
        update_integration_status(db, "gmail", "expired", user_id=alice)
        assert get_provider_integration(db, "gmail", user_id=alice)["status"] == "expired"
        assert get_provider_integration(db, "gmail", user_id=bob)["status"] == "active"

    def test_refreshed_google_tokens_keep_the_refresh_token(self, db, factory):
        user = factory.user()
        factory.integration(user, "gmail", status="expired", refresh_token="keep")
        update_oauth_credentials(
            db, "gmail", _creds(token="fresh", expiry=datetime(2030, 1, 1, 0, 0, 0)), user_id=user
        )
        row = get_provider_integration(db, "gmail", user_id=user)
        assert (row["access_token"], row["refresh_token"], row["status"]) == ("fresh", "keep", "active")
        assert row["token_expiry"] == "2030-01-01T00:00:00.000000Z"

    def test_provider_tokens_replace_the_refresh_token(self, db, factory):
        user = factory.user()
        factory.integration(user, "outlook", refresh_token="old")
        update_provider_tokens(
            db, "outlook", access_token="a2", refresh_token="new",
            token_expiry=datetime(2030, 1, 1, tzinfo=timezone.utc), user_id=user,
        )
        row = get_provider_integration(db, "outlook", user_id=user)
        assert (row["access_token"], row["refresh_token"]) == ("a2", "new")

    def test_delete_disconnects_only_the_users_row(self, db, factory):
        alice, bob = factory.user(), factory.user()
        factory.integration(alice, "gmail")
        factory.integration(bob, "gmail")
        delete_integration(db, "gmail", user_id=alice)
        assert get_provider_integration(db, "gmail", user_id=alice) is None
        assert get_provider_integration(db, "gmail", user_id=bob) is not None

    def test_writes_require_a_user(self, db):
        with pytest.raises(IntegrationError):
            update_integration_status(db, "gmail", "expired")
        with pytest.raises(IntegrationError):
            delete_integration(db, "gmail")


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
    """DB-backed OAuth state management, on the process database."""

    def _save(self, user, state="test-state-token", **kw):
        _save_oauth_state(
            state=state, user_id=user, provider="gmail",
            redirect_uri="http://localhost:8000/integrations/google/callback",
            code_verifier=kw.get("code_verifier", "pkce-verifier-abc"),
        )

    # Validates: SEL-450
    def test_save_oauth_state(self, process_db, factory):
        user = factory.user()
        self._save(user)
        row = process_db.query_one("SELECT * FROM oauth_states WHERE state = 'test-state-token'")
        assert row["user_id"] == user
        assert row["provider"] == "gmail"
        assert row["redirect_uri"] == "http://localhost:8000/integrations/google/callback"
        assert row["code_verifier"] == "pkce-verifier-abc"
        created = datetime.fromisoformat(row["created_at"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(row["expires_at"].replace("Z", "+00:00"))
        assert expires - created == timedelta(minutes=10)

    def test_validate_and_consume_valid_state(self, process_db, factory):
        user = factory.user()
        self._save(user, state="valid-state", code_verifier="pkce-verifier-xyz")

        result = _validate_and_consume_oauth_state("valid-state")

        assert result == {
            "user_id": user,
            "provider": "gmail",
            "redirect_uri": "http://localhost:8000/integrations/google/callback",
            "code_verifier": "pkce-verifier-xyz",
        }

    # Validates: SEL-451
    def test_validate_expired_state_raises_and_deletes_it(self, process_db, factory):
        self._save(factory.user(), state="expired-state")
        with process_db.write() as tx:
            tx.execute("UPDATE oauth_states SET expires_at = ?", (tx.ts(-300),))

        with pytest.raises(OAuthStateError, match="expired"):
            _validate_and_consume_oauth_state("expired-state")
        assert process_db.query_one("SELECT 1 FROM oauth_states") is None

    def test_validate_missing_state_raises(self, process_db):
        with pytest.raises(OAuthStateError, match="Invalid or expired"):
            _validate_and_consume_oauth_state("nonexistent-state")

    def test_state_is_consumed_after_use(self, process_db, factory):
        self._save(factory.user(), state="one-time-state")
        _validate_and_consume_oauth_state("one-time-state")
        with pytest.raises(OAuthStateError):
            _validate_and_consume_oauth_state("one-time-state")

    # Validates: SEL-450
    def test_cleanup_removes_only_expired_states(self, process_db, factory):
        user = factory.user()
        self._save(user, state="old")
        self._save(user, state="fresh")
        with process_db.write() as tx:
            tx.execute("UPDATE oauth_states SET expires_at = ? WHERE state = 'old'", (tx.ts(-1),))
        _clean_expired_oauth_states()
        assert [r["state"] for r in process_db.query("SELECT state FROM oauth_states")] == ["fresh"]


class TestInitiateOAuthFlow:
    """Test OAuth flow initiation with DB-backed state."""

    # Validates: SEL-450
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


class TestCombinedGoogleConsent:
    """One consent for Gmail and Calendar, tolerant of a partial grant."""

    # Validates: SEL-453
    @patch("selko.services.integrations._validate_and_consume_oauth_state")
    @patch("selko.services.integrations.Flow")
    def test_partial_grant_is_accepted_only_during_the_exchange(
        self, mock_flow_class, mock_validate, mock_config, monkeypatch
    ):
        import os

        from selko.services.integrations import GOOGLE_SCOPES

        monkeypatch.delenv("OAUTHLIB_RELAX_TOKEN_SCOPE", raising=False)
        mock_validate.return_value = {
            "user_id": "user-123",
            "provider": "google",
            "redirect_uri": "http://localhost:8000/integrations/google/callback",
            "code_verifier": "persisted-pkce-verifier",
        }
        seen = []
        mock_flow = MagicMock()
        mock_flow.fetch_token.side_effect = lambda **_: seen.append(
            os.environ.get("OAUTHLIB_RELAX_TOKEN_SCOPE")
        )
        mock_flow_class.from_client_config.return_value = mock_flow

        _, _, provider = complete_oauth_flow(
            config=mock_config, code="auth-code-123", state="test-state"
        )

        assert provider == "google"
        assert mock_flow_class.from_client_config.call_args.kwargs["scopes"] == GOOGLE_SCOPES
        # Relaxed while the token is parsed, restored the moment it returns.
        assert seen == ["1"]
        assert "OAUTHLIB_RELAX_TOKEN_SCOPE" not in os.environ

    @patch("selko.services.integrations._validate_and_consume_oauth_state")
    @patch("selko.services.integrations.Flow")
    def test_a_single_product_flow_stays_strict(
        self, mock_flow_class, mock_validate, mock_config, monkeypatch
    ):
        import os

        monkeypatch.delenv("OAUTHLIB_RELAX_TOKEN_SCOPE", raising=False)
        mock_validate.return_value = {
            "user_id": "user-123",
            "provider": "gmail",
            "redirect_uri": "http://localhost:8000/integrations/google/callback",
            "code_verifier": "persisted-pkce-verifier",
        }
        seen = []
        mock_flow = MagicMock()
        mock_flow.fetch_token.side_effect = lambda **_: seen.append(
            os.environ.get("OAUTHLIB_RELAX_TOKEN_SCOPE")
        )
        mock_flow_class.from_client_config.return_value = mock_flow

        complete_oauth_flow(config=mock_config, code="c", state="s")

        assert seen == [None]

    @pytest.mark.parametrize(
        ("granted", "expected"),
        [
            ("both", ["gmail", "google_calendar"]),
            ("gmail", ["gmail"]),
            ("calendar", ["google_calendar"]),
            ("none", []),
        ],
    )
    def test_grants_map_to_integrations(self, granted, expected):
        from selko.services.integrations import (
            CALENDAR_SCOPES,
            GMAIL_SCOPES,
            granted_google_providers,
        )

        scopes = {
            "both": GMAIL_SCOPES + CALENDAR_SCOPES,
            "gmail": GMAIL_SCOPES,
            "calendar": CALENDAR_SCOPES,
            "none": ["openid"],
        }[granted]
        creds = MagicMock()
        creds.granted_scopes = scopes

        assert granted_google_providers(creds) == expected

    def test_real_oauthlib_rejects_a_partial_grant_unless_relaxed(self, monkeypatch):
        """The mocks above cannot fail on this; the real token parser can.

        A partial grant is what Google returns when the user unticks Calendar.
        Unrelaxed, oauthlib raises and the user would connect nothing.
        """
        import json

        from oauthlib.oauth2 import WebApplicationClient

        from selko.services.integrations import (
            GMAIL_SCOPES,
            GOOGLE_SCOPES,
            _partial_scope_grant_allowed,
        )

        monkeypatch.delenv("OAUTHLIB_RELAX_TOKEN_SCOPE", raising=False)
        body = json.dumps({
            "access_token": "a", "token_type": "Bearer", "expires_in": 3600,
            "scope": " ".join(GMAIL_SCOPES),
        })

        with pytest.raises(Warning):
            WebApplicationClient("id").parse_request_body_response(body, scope=GOOGLE_SCOPES)

        with _partial_scope_grant_allowed():
            token = WebApplicationClient("id").parse_request_body_response(
                body, scope=GOOGLE_SCOPES
            )
        assert token["scope"] == GMAIL_SCOPES

    # Validates: SEL-454
    def test_half_of_the_calendar_scopes_is_not_calendar(self):
        """Calendar needs both of its scopes; one alone would fail on write."""
        from selko.services.integrations import CALENDAR_SCOPES, granted_google_providers

        creds = MagicMock()
        creds.granted_scopes = CALENDAR_SCOPES[:1]

        assert granted_google_providers(creds) == []


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

    # Validates: SEL-452
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

    # Validates: SEL-452
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
    def test_passes_user_id(self, mock_load_config, mock_get_oauth, db):
        from selko.services.integrations import get_credentials

        mock_load_config.return_value = MagicMock()
        mock_creds = MagicMock()
        mock_creds.expired = False
        mock_get_oauth.return_value = mock_creds

        result = get_credentials(db, "user-abc", "google_calendar")

        assert result is mock_creds
        mock_get_oauth.assert_called_once_with(
            db, mock_load_config.return_value, "google_calendar", user_id="user-abc"
        )

    # Validates: SEL-458
    def test_failed_refresh_marks_the_integration_expired(self, db, factory, monkeypatch):
        """A refresh Google refuses expires the row (read back from the database)."""
        from google.auth.exceptions import RefreshError

        from selko.services import integrations as svc

        user = factory.user()
        factory.integration(user, "google_calendar", refresh_token="r",
                            token_expiry="2000-01-01T00:00:00.000000Z")
        monkeypatch.setattr(
            "google.oauth2.credentials.Credentials.refresh",
            lambda self, request: (_ for _ in ()).throw(RefreshError("invalid_grant")),
        )
        assert svc.get_credentials(db, user, "google_calendar") is None
        assert get_provider_integration(db, "google_calendar", user_id=user)["status"] == "expired"
