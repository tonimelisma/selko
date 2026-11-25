"""Integrations service for Selko.

Handles OAuth token storage and retrieval from the integrations table.
Every function takes the process database (``client``) and the owning user's
id explicitly; nothing reads another user's row.
"""

import logging
import os
import re
import secrets
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from selko.config import Config
from selko.db import integrations as db_integrations
from selko.db import recovery as db_recovery
from selko.db.connection import Database
from selko.db.errors import DbError

Client = Database

logger = logging.getLogger(__name__)

# Gmail scopes
GMAIL_SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

# Google Calendar scopes
CALENDAR_SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.events",
]

# Google Photos scopes
PHOTOS_SCOPES = ["https://www.googleapis.com/auth/photoslibrary.readonly"]

# One Google consent covers both integrations. Connected separately, the two
# rows held two refresh tokens that expired independently, so a user could
# reconnect Calendar and still have mail silently stalled (or the reverse).
# The OAuth state uses the pseudo-provider "google"; storage stays one
# integrations row per provider, so polling, the mirror and reconnect
# recovery are unchanged.
GOOGLE_PROVIDER_SCOPES = {
    "gmail": GMAIL_SCOPES,
    "google_calendar": CALENDAR_SCOPES,
}
GOOGLE_SCOPES = [scope for scopes in GOOGLE_PROVIDER_SCOPES.values() for scope in scopes]


def granted_google_providers(credentials: Credentials) -> list[str]:
    """Integrations whose scopes this combined consent actually granted.

    Google's consent screen lets the user untick individual scopes, so a
    combined request can come back with only one product authorized. Saving
    a row without its scope would report a connection that fails on first
    use.
    """
    granted = set(credentials.granted_scopes or credentials.scopes or [])
    return [
        provider
        for provider, scopes in GOOGLE_PROVIDER_SCOPES.items()
        if set(scopes) <= granted
    ]


@contextmanager
def _partial_scope_grant_allowed():
    """Let oauthlib accept a token whose scope differs from the request.

    Without this, unticking one product on the consent screen raises during
    the token exchange and the user connects neither. The callback runs
    synchronously on the event-loop thread, and background refreshes go
    through google-auth rather than oauthlib, so nothing else observes the
    variable while it is set.
    """
    previous = os.environ.get("OAUTHLIB_RELAX_TOKEN_SCOPE")
    os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = "1"
    try:
        yield
    finally:
        if previous is None:
            os.environ.pop("OAUTHLIB_RELAX_TOKEN_SCOPE", None)
        else:
            os.environ["OAUTHLIB_RELAX_TOKEN_SCOPE"] = previous


def _parse_token_expiry(value: str) -> datetime:
    """Parse DB token_expiry into naive UTC for google-auth.

    Python 3.10's fromisoformat rejects fractional seconds that aren't
    exactly 3 or 6 digits (e.g. '...38.35908+00:00' from Google refresh).
    """
    s = value.replace("Z", "+00:00")
    match = re.match(
        r"^(.*T\d{2}:\d{2}:\d{2})(\.\d+)?([+-]\d{2}:\d{2}|[+-]\d{4})?$",
        s,
    )
    if match:
        base, frac, tz = match.groups()
        if frac:
            digits = frac[1:]
            frac = "." + (digits + "000000")[:6]
        else:
            frac = ""
        s = f"{base}{frac}{tz or ''}"

    expiry = datetime.fromisoformat(s)
    if expiry.tzinfo is not None:
        expiry = expiry.astimezone(timezone.utc).replace(tzinfo=None)
    return expiry


class IntegrationError(Exception):
    """Raised when integration operations fail."""

    pass


class OAuthStateError(IntegrationError):
    """Raised when OAuth state validation fails (invalid or expired)."""

    pass


def _require_user(user_id: Optional[str]) -> str:
    """The owning user. There is no signed-in client session to fall back to."""
    if not user_id:
        raise IntegrationError("user_id is required")
    return user_id


class OAuthProviderNotAllowed(IntegrationError):
    """Raised before token exchange when a callback rejects a provider."""

    def __init__(self, provider: str, allowed_providers: set[str]) -> None:
        self.provider = provider
        self.allowed_providers = allowed_providers
        super().__init__(
            f"Provider {provider!r} is not allowed for this OAuth callback"
        )


def get_provider_integration(
    client: Client,
    provider: str,
    user_id: Optional[str] = None,
) -> dict[str, Any] | None:
    """Load one provider integration row for a user."""
    user_id = _require_user(user_id)
    try:
        return db_integrations.get_integration(client, user_id, provider)
    except DbError as e:
        raise IntegrationError(f"Failed to get {provider} integration: {e}") from e


def complete_integration_reauthorization(
    client: Client,
    user_id: str,
    provider: str,
    access_token: str,
    refresh_token: Optional[str],
    token_expiry: Optional[str],
    scopes: list[str],
    provider_email: Optional[str],
) -> str:
    """Atomically upsert credentials and schedule reconnect recovery.

    One transaction, so a reconnect can never save new
    credentials without also, for ``google_calendar``, durably superseding
    any in-flight recovery and scheduling a fresh one in the same
    transaction (docs/specs/oauth-reconnect-catch-up.md). Gmail/Outlook need
    no recovery record here: `integrations_ensure_email_sync_state` already
    resumes them from durable provider cursors the moment this upsert makes
    the integration active again.

    Args:
        client: The process database.

    Returns:
        The integration's id.

    Raises:
        IntegrationError: If the write fails.
    """
    try:
        integration_id = db_recovery.complete_integration_reauthorization(
            client,
            user_id,
            provider,
            access_token,
            refresh_token=refresh_token,
            token_expiry=db_integrations.timestamp(token_expiry),
            scopes=scopes,
            provider_email=provider_email,
        )
        logger.info(f"Saved {provider} integration for user {user_id}")
        return integration_id
    except DbError as e:
        raise IntegrationError(f"Failed to save integration: {e}") from e


def save_oauth_credentials(
    client: Client,
    user_id: str,
    provider: str,
    credentials: Credentials,
    provider_email: str = None,
) -> None:
    """Save OAuth tokens to integrations table.

    Args:
        client: The process database.
        user_id: User ID to save credentials for.
        provider: Integration provider ('gmail', 'google_photos', 'google_calendar').
        credentials: Google OAuth credentials object.
        provider_email: Optional email associated with the provider account.

    Raises:
        IntegrationError: If save fails.
    """
    token_expiry = None
    if credentials.expiry:
        token_expiry = credentials.expiry.isoformat()

    complete_integration_reauthorization(
        client,
        user_id=user_id,
        provider=provider,
        access_token=credentials.token,
        refresh_token=credentials.refresh_token,
        token_expiry=token_expiry,
        scopes=list(credentials.scopes) if credentials.scopes else [],
        provider_email=provider_email,
    )


def save_provider_tokens(
    client: Client,
    user_id: str,
    provider: str,
    token_result: dict[str, Any],
    provider_email: str | None = None,
) -> None:
    """Save a non-Google OAuth token result, such as an MSAL response."""
    access_token = token_result.get("access_token")
    if not access_token:
        raise IntegrationError("OAuth token response did not include an access token")

    expires_in = token_result.get("expires_in")
    token_expiry = None
    if expires_in is not None:
        token_expiry = (
            datetime.now(timezone.utc) + timedelta(seconds=int(expires_in))
        ).isoformat()

    raw_scope = token_result.get("scope")
    if isinstance(raw_scope, str):
        scopes = raw_scope.split()
    else:
        scopes = list(token_result.get("scopes") or [])

    complete_integration_reauthorization(
        client,
        user_id=user_id,
        provider=provider,
        access_token=access_token,
        refresh_token=token_result.get("refresh_token"),
        token_expiry=token_expiry,
        scopes=scopes,
        provider_email=provider_email,
    )


def get_oauth_credentials(
    client: Client,
    config: Config,
    provider: str,
    user_id: Optional[str] = None,
) -> Optional[Credentials]:
    """Load OAuth credentials from DB for a user.

    Reconstructs Google Credentials object with client_id/secret from config
    to enable token refresh.

    Args:
        client: The process database.
        config: Configuration with Google OAuth client credentials.
        provider: Integration provider name.
        user_id: The owning user (required).

    Returns:
        Google Credentials object, or None if no integration found.
    """
    user_id = _require_user(user_id)

    try:
        row = db_integrations.get_integration(client, user_id, provider)
        if row is None:
            return None

        # Check if integration is in non-active state
        if row.get("status") in ("expired", "revoked", "error"):
            logger.warning(f"{provider} integration is {row['status']}")
            return None

        # google-auth compares expiry to naive UTC; store as naive UTC.
        expiry = None
        if row.get("token_expiry"):
            expiry = _parse_token_expiry(row["token_expiry"])

        # Reconstruct credentials with client_id/secret for refresh
        creds = Credentials(
            token=row["access_token"],
            refresh_token=row.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=config.google_client_id,
            client_secret=config.google_client_secret,
            scopes=row.get("scopes") or [],
            expiry=expiry,
        )

        return creds

    except DbError as e:
        raise IntegrationError(f"Failed to get integration: {e}") from e


def update_integration_status(
    client: Client,
    provider: str,
    status: str,
    user_id: Optional[str] = None,
) -> None:
    """Update the status of an integration.

    Args:
        client: The process database.
        provider: Integration provider name.
        status: New status ('active', 'expired', 'revoked', 'error').
        user_id: The owning user (required).
    """
    user_id = _require_user(user_id)

    try:
        db_integrations.set_integration_status(client, user_id, provider, status)
        logger.debug(f"Updated {provider} integration status to {status}")
    except DbError as e:
        raise IntegrationError(f"Failed to update integration status: {e}") from e


async def claim_integration_recovery(
    pool,
    worker_id: str,
    lock_seconds: int = 300,
) -> Optional[dict[str, Any]]:
    """Atomically claim the next pending integration recovery generation.

    Args:
        pool: The process database.
        worker_id: Unique identifier for this worker process.
        lock_seconds: How long to hold the claim lock.

    Returns:
        The claimed recovery row, or None if nothing is pending.

    Raises:
        IntegrationError: If the claim fails.
    """
    try:
        return await pool.run(
            db_recovery.claim_integration_recovery, pool, worker_id, lock_seconds
        )
    except Exception as e:
        raise IntegrationError(f"Failed to claim integration recovery: {e}") from e


async def unlock_expired_integration_recoveries(pool) -> int:
    """Return crashed-worker recovery claims to pending.

    Returns:
        Number of recovery generations unlocked.

    Raises:
        IntegrationError: If the unlock fails.
    """
    try:
        return await pool.run(db_recovery.unlock_expired_integration_recoveries, pool) or 0
    except Exception as e:
        raise IntegrationError(
            f"Failed to unlock expired integration recoveries: {e}"
        ) from e


def update_oauth_credentials(
    client: Client,
    provider: str,
    credentials: Credentials,
    user_id: Optional[str] = None,
) -> None:
    """Update OAuth tokens after refresh.

    Args:
        client: The process database.
        provider: Integration provider name.
        credentials: Updated Google credentials.
        user_id: The owning user (required).
    """
    user_id = _require_user(user_id)

    token_expiry = None
    if credentials.expiry:
        # Persist as UTC ISO; strip tz for consistency with google-auth naive expiry
        expiry = credentials.expiry
        if expiry.tzinfo is not None:
            expiry = expiry.astimezone(timezone.utc).replace(tzinfo=None)
        token_expiry = expiry.replace(tzinfo=timezone.utc).isoformat()

    try:
        db_integrations.update_integration_tokens(
            client,
            user_id,
            provider,
            access_token=credentials.token,
            token_expiry=token_expiry,
        )
        logger.debug(f"Updated {provider} OAuth tokens")
    except DbError as e:
        raise IntegrationError(f"Failed to update tokens: {e}") from e


def update_provider_tokens(
    client: Client,
    provider: str,
    *,
    access_token: str,
    refresh_token: str | None,
    token_expiry: datetime | str | None,
    user_id: Optional[str] = None,
) -> None:
    """Persist refreshed tokens for a provider-agnostic OAuth integration."""
    user_id = _require_user(user_id)

    try:
        db_integrations.update_integration_tokens(
            client,
            user_id,
            provider,
            access_token=access_token,
            refresh_token=refresh_token,
            token_expiry=token_expiry,
        )
        logger.debug("Updated %s provider tokens", provider)
    except DbError as e:
        raise IntegrationError(f"Failed to update provider tokens: {e}") from e


def get_credentials(
    client: Client,
    user_id: str,
    provider: str,
) -> Optional[Credentials]:
    """Get OAuth credentials for a specific user and provider.

    Loads tokens for ``user_id`` (required for service-role workers) and
    refreshes them when expired.

    Args:
        client: The process database.
        user_id: User ID that owns the integration.
        provider: Integration provider name.

    Returns:
        Google Credentials object, or None if no integration found.
    """
    from google.auth.exceptions import RefreshError
    from google.auth.transport.requests import Request

    from selko.config import load_config
    config = load_config()

    creds = get_oauth_credentials(client, config, provider, user_id=user_id)
    if not creds:
        return None

    if creds.expired and creds.refresh_token:
        try:
            logger.info("%s token expired, refreshing for user %s...", provider, user_id)
            creds.refresh(Request())
            for attempt in range(3):
                try:
                    update_oauth_credentials(
                        client, provider, creds, user_id=user_id
                    )
                    logger.info("%s token refreshed and saved", provider)
                    break
                except Exception as save_err:
                    logger.error(
                        "Failed to save refreshed %s token (attempt %d): %s",
                        provider,
                        attempt + 1,
                        save_err,
                    )
                    if attempt == 2:
                        logger.error(
                            "CRITICAL: Refreshed %s token could not be saved after 3 attempts",
                            provider,
                        )
        except RefreshError as e:
            logger.warning("%s token refresh failed: %s", provider, e)
            update_integration_status(
                client, provider, "expired", user_id=user_id
            )
            return None

    return creds


# --- OAuth state management (DB-backed) ---


def _get_service_client_for_oauth() -> Client:
    """The process database, for OAuth state operations (keyed by the state token)."""
    from selko.config import load_config
    from selko.services.auth import get_service_client
    config = load_config()
    return get_service_client(config)


def _save_oauth_state(
    state: str,
    user_id: str,
    provider: str,
    redirect_uri: str,
    code_verifier: Optional[str] = None,
) -> None:
    """Save OAuth state to database.

    Args:
        state: Cryptographically random state token.
        user_id: User ID initiating the flow.
        provider: OAuth provider name.
        redirect_uri: Callback URI for the flow.
        code_verifier: PKCE code_verifier to reuse on token exchange.
    """
    client = _get_service_client_for_oauth()

    try:
        db_integrations.save_oauth_state(
            client, user_id, state, provider, redirect_uri, code_verifier
        )
    except DbError as e:
        raise IntegrationError(f"Failed to save OAuth state: {e}") from e


def _validate_and_consume_oauth_state(state: str) -> dict:
    """Validate OAuth state and consume it (delete after use).

    Args:
        state: State parameter from callback.

    Returns:
        Dict with user_id, provider, redirect_uri, code_verifier.

    Raises:
        OAuthStateError: If state is invalid or expired.
    """
    client = _get_service_client_for_oauth()

    try:
        # Read and delete in one transaction: a state can be used once, even
        # by two concurrent callbacks. An expired state is deleted too.
        row = db_integrations.consume_oauth_state(client, state)
        if row is None:
            raise OAuthStateError("Invalid or expired state parameter")
        if row["expired"]:
            raise OAuthStateError("State parameter expired")

        return {
            "user_id": row["user_id"],
            "provider": row["provider"],
            "redirect_uri": row["redirect_uri"],
            "code_verifier": row.get("code_verifier"),
        }

    except OAuthStateError:
        raise
    except DbError as e:
        raise IntegrationError(f"Failed to validate OAuth state: {e}") from e


def _clean_expired_oauth_states() -> None:
    """Clean up expired OAuth states from the database."""
    try:
        client = _get_service_client_for_oauth()
        removed = db_integrations.delete_expired_oauth_states(client)
        if removed:
            logger.debug(f"Cleaned up {removed} expired OAuth states")
    except Exception as e:
        # Non-critical cleanup — log and continue
        logger.warning(f"Failed to clean up expired OAuth states: {e}")


def oauth_callback_uri(config: Config, provider: str) -> str:
    """The API's own OAuth callback for a provider's consent."""
    if provider == "outlook":
        return f"{config.api_public_url}/integrations/microsoft/callback"
    return f"{config.api_public_url}/integrations/google/callback"


def initiate_oauth_flow(
    config: Config,
    provider: str,
    user_id: str,
    redirect_uri: str,
) -> dict[str, str]:
    """Initiate OAuth flow for a provider.

    Generates an authorization URL with state parameter for CSRF protection.
    State is persisted in the database to survive server restarts.

    Args:
        config: Configuration with Google OAuth client credentials.
        provider: 'google' (Gmail + Calendar in one consent), 'outlook', or a
            single Google product ('gmail', 'google_calendar').
        user_id: User ID initiating the flow.
        redirect_uri: URI to redirect to after authorization.

    Returns:
        Dict with 'auth_url' and 'state' keys.

    Raises:
        IntegrationError: If client credentials not configured or invalid provider.
    """
    # Microsoft has its own MSAL authorization flow but shares state storage.
    if provider == "outlook":
        from selko.services.outlook import build_auth_url

        state = secrets.token_urlsafe(32)
        _save_oauth_state(state, user_id, provider, redirect_uri)
        _clean_expired_oauth_states()
        return {
            "auth_url": build_auth_url(config, state, redirect_uri),
            "state": state,
        }

    if provider == "google":
        scopes = GOOGLE_SCOPES
    elif provider == "gmail":
        scopes = GMAIL_SCOPES
    elif provider == "google_calendar":
        scopes = CALENDAR_SCOPES
    elif provider == "google_photos":
        scopes = PHOTOS_SCOPES
    else:
        raise IntegrationError(f"Unsupported provider: {provider}")

    if not config.google_client_id or not config.google_client_secret:
        raise IntegrationError(
            "Google OAuth client credentials not configured. "
            "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in your .env file."
        )

    try:
        # Create flow from client config
        client_config = {
            "web": {
                "client_id": config.google_client_id,
                "client_secret": config.google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri],
            }
        }
        flow = Flow.from_client_config(
            client_config,
            scopes=scopes,
            redirect_uri=redirect_uri,
            autogenerate_code_verifier=True,
        )

        # Generate cryptographically random state
        state = secrets.token_urlsafe(32)

        # Generate authorization URL (also creates flow.code_verifier for PKCE)
        auth_url, _ = flow.authorization_url(
            state=state,
            access_type="offline",  # Request refresh token
            prompt="consent",  # Force consent screen to ensure refresh token
        )

        code_verifier = flow.code_verifier
        if not code_verifier:
            raise IntegrationError(
                "Failed to generate PKCE code_verifier for OAuth flow"
            )

        # Persist state + PKCE verifier so callback can complete token exchange
        _save_oauth_state(
            state, user_id, provider, redirect_uri, code_verifier=code_verifier
        )

        # Clean up expired states (non-blocking)
        _clean_expired_oauth_states()

        logger.info(f"Generated OAuth URL for {provider} (user {user_id})")
        return {"auth_url": auth_url, "state": state}

    except IntegrationError:
        raise
    except ValueError as e:
        raise IntegrationError(f"Invalid OAuth configuration: {e}") from e


def complete_oauth_flow(
    config: Config,
    code: str,
    state: str,
    allowed_providers: set[str] | None = None,
) -> tuple[Credentials | dict[str, Any], str, str]:
    """Complete OAuth flow by exchanging authorization code for tokens.

    Args:
        config: Configuration with Google OAuth client credentials.
        code: Authorization code from callback.
        state: State parameter for CSRF validation.
        allowed_providers: Optional provider allowlist checked immediately after
            state validation and before exchanging the authorization code.

    Returns:
        Tuple of (credentials, user_id, provider).

    Raises:
        OAuthStateError: If state invalid or expired.
        IntegrationError: If token exchange fails.
    """
    # Validate and consume state from database
    state_data = _validate_and_consume_oauth_state(state)

    user_id = state_data["user_id"]
    provider = state_data["provider"]
    redirect_uri = state_data["redirect_uri"]
    code_verifier = state_data.get("code_verifier")

    if allowed_providers is not None and provider not in allowed_providers:
        raise OAuthProviderNotAllowed(provider, allowed_providers)

    if provider == "outlook":
        from selko.services.outlook import exchange_code

        token_result = exchange_code(config, code, redirect_uri)
        logger.info("OAuth flow completed for Outlook (user %s)", user_id)
        return token_result, user_id, provider

    # Determine scopes based on provider
    if provider == "google":
        scopes = GOOGLE_SCOPES
    elif provider == "gmail":
        scopes = GMAIL_SCOPES
    elif provider == "google_calendar":
        scopes = CALENDAR_SCOPES
    elif provider == "google_photos":
        scopes = PHOTOS_SCOPES
    else:
        raise IntegrationError(f"Unsupported provider: {provider}")

    if not code_verifier:
        raise IntegrationError(
            "OAuth state missing PKCE code_verifier; please restart the connection"
        )

    try:
        # Create flow with same redirect_uri and persisted PKCE verifier
        client_config = {
            "web": {
                "client_id": config.google_client_id,
                "client_secret": config.google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri],
            }
        }
        flow = Flow.from_client_config(
            client_config,
            scopes=scopes,
            redirect_uri=redirect_uri,
            code_verifier=code_verifier,
            autogenerate_code_verifier=False,
        )

        # Exchange authorization code for tokens
        if provider == "google":
            with _partial_scope_grant_allowed():
                flow.fetch_token(code=code)
        else:
            flow.fetch_token(code=code)
        credentials = flow.credentials

        logger.info(f"OAuth flow completed for {provider} (user {user_id})")
        return credentials, user_id, provider

    except IntegrationError:
        raise
    except Exception as e:
        raise IntegrationError(f"Token exchange failed: {e}") from e


def delete_integration(
    client: Client,
    provider: str,
    user_id: Optional[str] = None,
) -> None:
    """Delete an integration (disconnect).

    Its sync state, mirror and recoveries cascade with it.

    Args:
        client: The process database.
        provider: Integration provider to disconnect.
        user_id: The owning user (required).

    Raises:
        IntegrationError: If deletion fails.
    """
    user_id = _require_user(user_id)

    try:
        db_integrations.delete_integration(client, user_id, provider)
        logger.info(f"Deleted {provider} integration for user {user_id}")
    except DbError as e:
        raise IntegrationError(f"Failed to delete integration: {e}") from e
