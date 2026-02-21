"""Integrations service for Selko.

Handles OAuth token storage and retrieval from the integrations table.
Uses RLS - all operations are scoped to the authenticated user.
"""

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from postgrest.exceptions import APIError
from supabase import Client, PostgrestAPIError

from selko.config import Config
from selko.services.auth import get_current_user_id

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


class IntegrationError(Exception):
    """Raised when integration operations fail."""

    pass


class OAuthStateError(IntegrationError):
    """Raised when OAuth state validation fails (invalid or expired)."""

    pass


def save_oauth_credentials(
    client: Client,
    user_id: str,
    provider: str,
    credentials: Credentials,
    provider_email: str = None,
) -> None:
    """Save OAuth tokens to integrations table.

    Args:
        client: Supabase client (authenticated or service role).
        user_id: User ID to save credentials for.
        provider: Integration provider ('gmail', 'google_photos', 'google_calendar').
        credentials: Google OAuth credentials object.
        provider_email: Optional email associated with the provider account.

    Raises:
        IntegrationError: If save fails.
    """

    # Prepare token expiry
    token_expiry = None
    if credentials.expiry:
        token_expiry = credentials.expiry.isoformat()

    data = {
        "user_id": user_id,
        "provider": provider,
        "status": "active",
        "access_token": credentials.token,
        "refresh_token": credentials.refresh_token,
        "token_expiry": token_expiry,
        "scopes": list(credentials.scopes) if credentials.scopes else [],
        "provider_email": provider_email,
    }

    try:
        client.table("integrations").upsert(
            data, on_conflict="user_id,provider"
        ).execute()
        logger.info(f"Saved {provider} integration for user {user_id}")
    except PostgrestAPIError as e:
        raise IntegrationError(f"Failed to save integration: {e.message}") from e


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
        client: Authenticated Supabase client.
        config: Configuration with Google OAuth client credentials.
        provider: Integration provider name.
        user_id: Optional user ID (required if using service role client).

    Returns:
        Google Credentials object, or None if no integration found.
    """
    if user_id is None:
        user_id = get_current_user_id(client)

    try:
        result = (
            client.table("integrations")
            .select("*")
            .eq("user_id", user_id)
            .eq("provider", provider)
            .maybe_single()
            .execute()
        )

        # maybe_single() returns None when no rows found
        if result is None or not result.data:
            return None

        row = result.data

        # Check if integration is in non-active state
        if row.get("status") in ("expired", "revoked", "error"):
            logger.warning(f"{provider} integration is {row['status']}")
            return None

        # Reconstruct credentials with client_id/secret for refresh
        creds = Credentials(
            token=row["access_token"],
            refresh_token=row.get("refresh_token"),
            token_uri="https://oauth2.googleapis.com/token",
            client_id=config.google_client_id,
            client_secret=config.google_client_secret,
            scopes=row.get("scopes", []),
        )

        return creds

    except APIError as e:
        # maybe_single() throws APIError with code 204 when no rows found
        if e.code == "204":
            return None
        raise IntegrationError(f"Failed to get integration: {e.message}") from e
    except PostgrestAPIError as e:
        raise IntegrationError(f"Failed to get integration: {e.message}") from e


def update_integration_status(
    client: Client,
    provider: str,
    status: str,
) -> None:
    """Update the status of an integration.

    Args:
        client: Authenticated Supabase client.
        provider: Integration provider name.
        status: New status ('active', 'expired', 'revoked', 'error').
    """
    user_id = get_current_user_id(client)

    try:
        client.table("integrations").update(
            {"status": status, "updated_at": datetime.now(timezone.utc).isoformat()}
        ).eq("user_id", user_id).eq("provider", provider).execute()
        logger.debug(f"Updated {provider} integration status to {status}")
    except PostgrestAPIError as e:
        raise IntegrationError(f"Failed to update integration status: {e.message}") from e


def update_oauth_credentials(
    client: Client,
    provider: str,
    credentials: Credentials,
) -> None:
    """Update OAuth tokens after refresh.

    Args:
        client: Authenticated Supabase client.
        provider: Integration provider name.
        credentials: Updated Google credentials.
    """
    user_id = get_current_user_id(client)

    token_expiry = None
    if credentials.expiry:
        token_expiry = credentials.expiry.isoformat()

    try:
        client.table("integrations").update(
            {
                "access_token": credentials.token,
                "token_expiry": token_expiry,
                "status": "active",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        ).eq("user_id", user_id).eq("provider", provider).execute()
        logger.debug(f"Updated {provider} OAuth tokens")
    except PostgrestAPIError as e:
        raise IntegrationError(f"Failed to update tokens: {e.message}") from e


def get_credentials(
    client: Client,
    user_id: str,
    provider: str,
) -> Optional[Credentials]:
    """Get OAuth credentials for a specific user and provider.

    This is a simplified version that doesn't require Config since it's called
    from API context where we already have an authenticated client.

    Args:
        client: Authenticated Supabase client.
        user_id: User ID (not used, client auth handles this).
        provider: Integration provider name.

    Returns:
        Google Credentials object, or None if no integration found.
    """
    # Load config to get client_id/secret
    from selko.config import load_config
    config = load_config()

    return get_oauth_credentials(client, config, provider)


# --- OAuth state management (DB-backed) ---


def _get_service_client_for_oauth() -> Client:
    """Get a service role client for OAuth state operations.

    OAuth states table uses service_role RLS policy, so we need a
    service role client to read/write states.
    """
    from selko.config import load_config
    from selko.services.auth import get_service_client
    config = load_config()
    return get_service_client(config)


def _save_oauth_state(
    state: str,
    user_id: str,
    provider: str,
    redirect_uri: str,
) -> None:
    """Save OAuth state to database.

    Args:
        state: Cryptographically random state token.
        user_id: User ID initiating the flow.
        provider: OAuth provider name.
        redirect_uri: Callback URI for the flow.
    """
    client = _get_service_client_for_oauth()
    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(minutes=10)

    try:
        client.table("oauth_states").insert({
            "state": state,
            "user_id": user_id,
            "provider": provider,
            "redirect_uri": redirect_uri,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
        }).execute()
    except PostgrestAPIError as e:
        raise IntegrationError(f"Failed to save OAuth state: {e.message}") from e


def _validate_and_consume_oauth_state(state: str) -> dict:
    """Validate OAuth state and consume it (delete after use).

    Args:
        state: State parameter from callback.

    Returns:
        Dict with user_id, provider, redirect_uri.

    Raises:
        OAuthStateError: If state is invalid or expired.
    """
    client = _get_service_client_for_oauth()

    try:
        result = (
            client.table("oauth_states")
            .select("*")
            .eq("state", state)
            .maybe_single()
            .execute()
        )

        if result is None or not result.data:
            raise OAuthStateError("Invalid or expired state parameter")

        row = result.data

        # Check expiry
        expires_at = datetime.fromisoformat(row["expires_at"])
        if datetime.now(timezone.utc) > expires_at:
            # Clean up expired state
            client.table("oauth_states").delete().eq("state", state).execute()
            raise OAuthStateError("State parameter expired")

        # Consume state (one-time use)
        client.table("oauth_states").delete().eq("state", state).execute()

        return {
            "user_id": row["user_id"],
            "provider": row["provider"],
            "redirect_uri": row["redirect_uri"],
        }

    except OAuthStateError:
        raise
    except APIError as e:
        if e.code == "204":
            raise OAuthStateError("Invalid or expired state parameter") from e
        raise IntegrationError(f"Failed to validate OAuth state: {e.message}") from e
    except PostgrestAPIError as e:
        raise IntegrationError(f"Failed to validate OAuth state: {e.message}") from e


def _clean_expired_oauth_states() -> None:
    """Clean up expired OAuth states from the database."""
    try:
        client = _get_service_client_for_oauth()
        now = datetime.now(timezone.utc).isoformat()
        result = (
            client.table("oauth_states")
            .delete()
            .lt("expires_at", now)
            .execute()
        )
        if result.data:
            logger.debug(f"Cleaned up {len(result.data)} expired OAuth states")
    except Exception as e:
        # Non-critical cleanup — log and continue
        logger.warning(f"Failed to clean up expired OAuth states: {e}")


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
        provider: Integration provider ('gmail', 'google_calendar').
        user_id: User ID initiating the flow.
        redirect_uri: URI to redirect to after authorization.

    Returns:
        Dict with 'auth_url' and 'state' keys.

    Raises:
        IntegrationError: If client credentials not configured or invalid provider.
    """
    # Determine scopes based on provider
    if provider == "gmail":
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
        )

        # Generate cryptographically random state
        state = secrets.token_urlsafe(32)

        # Persist state to database
        _save_oauth_state(state, user_id, provider, redirect_uri)

        # Clean up expired states (non-blocking)
        _clean_expired_oauth_states()

        # Generate authorization URL
        auth_url, _ = flow.authorization_url(
            state=state,
            access_type="offline",  # Request refresh token
            prompt="consent",  # Force consent screen to ensure refresh token
        )

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
) -> tuple[Credentials, str, str]:
    """Complete OAuth flow by exchanging authorization code for tokens.

    Args:
        config: Configuration with Google OAuth client credentials.
        code: Authorization code from callback.
        state: State parameter for CSRF validation.

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

    # Determine scopes based on provider
    if provider == "gmail":
        scopes = GMAIL_SCOPES
    elif provider == "google_calendar":
        scopes = CALENDAR_SCOPES
    elif provider == "google_photos":
        scopes = PHOTOS_SCOPES
    else:
        raise IntegrationError(f"Unsupported provider: {provider}")

    try:
        # Create flow with same redirect_uri
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
        )

        # Exchange authorization code for tokens
        flow.fetch_token(code=code)
        credentials = flow.credentials

        logger.info(f"OAuth flow completed for {provider} (user {user_id})")
        return credentials, user_id, provider

    except Exception as e:
        raise IntegrationError(f"Token exchange failed: {e}") from e


def delete_integration(
    client: Client,
    provider: str,
) -> None:
    """Delete an integration (disconnect).

    Args:
        client: Authenticated Supabase client.
        provider: Integration provider to disconnect.

    Raises:
        IntegrationError: If deletion fails.
    """
    user_id = get_current_user_id(client)

    try:
        client.table("integrations").delete().eq("user_id", user_id).eq("provider", provider).execute()
        logger.info(f"Deleted {provider} integration for user {user_id}")
    except PostgrestAPIError as e:
        raise IntegrationError(f"Failed to delete integration: {e.message}") from e
