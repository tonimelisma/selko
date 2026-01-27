"""Integrations service for Selko.

Handles OAuth token storage and retrieval from the integrations table.
Uses RLS - all operations are scoped to the authenticated user.
"""

import logging
import secrets
from datetime import datetime, timedelta
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

# In-memory state storage for OAuth flow (MVP)
# Maps state -> {user_id, provider, created_at, redirect_uri}
_oauth_states: dict[str, dict] = {}


class IntegrationError(Exception):
    """Raised when integration operations fail."""

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
            {"status": status, "updated_at": datetime.utcnow().isoformat()}
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
                "updated_at": datetime.utcnow().isoformat(),
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


def initiate_oauth_flow(
    config: Config,
    provider: str,
    user_id: str,
    redirect_uri: str,
) -> dict[str, str]:
    """Initiate OAuth flow for a provider.

    Generates an authorization URL with state parameter for CSRF protection.

    Args:
        config: Configuration with Google OAuth client credentials.
        provider: Integration provider ('gmail', 'google_calendar').
        user_id: User ID initiating the flow.
        redirect_uri: URI to redirect to after authorization.

    Returns:
        Dict with 'auth_url' and 'state' keys.

    Raises:
        IntegrationError: If credentials file not found or invalid provider.
    """
    # Determine scopes based on provider
    if provider == "gmail":
        scopes = GMAIL_SCOPES
    elif provider == "google_calendar":
        scopes = CALENDAR_SCOPES
    else:
        raise IntegrationError(f"Unsupported provider: {provider}")

    if not config.credentials_file.exists():
        raise IntegrationError(
            f"Credentials file not found: {config.credentials_file}. "
            "Download OAuth client credentials from Google Cloud Console."
        )

    try:
        # Create flow from client secrets file
        flow = Flow.from_client_secrets_file(
            str(config.credentials_file),
            scopes=scopes,
            redirect_uri=redirect_uri,
        )

        # Generate cryptographically random state
        state = secrets.token_urlsafe(32)

        # Store state in memory (expires in 10 minutes)
        _oauth_states[state] = {
            "user_id": user_id,
            "provider": provider,
            "created_at": datetime.utcnow(),
            "redirect_uri": redirect_uri,
        }

        # Clean up expired states (older than 10 minutes)
        _clean_expired_states()

        # Generate authorization URL
        auth_url, _ = flow.authorization_url(
            state=state,
            access_type="offline",  # Request refresh token
            prompt="consent",  # Force consent screen to ensure refresh token
        )

        logger.info(f"Generated OAuth URL for {provider} (user {user_id})")
        return {"auth_url": auth_url, "state": state}

    except FileNotFoundError as e:
        raise IntegrationError(f"Credentials file not found: {e}") from e
    except ValueError as e:
        raise IntegrationError(f"Invalid credentials file: {e}") from e


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
        IntegrationError: If state invalid, expired, or token exchange fails.
    """
    # Validate state
    state_data = _oauth_states.get(state)
    if not state_data:
        raise IntegrationError("Invalid or expired state parameter")

    # Check state age (10 minute expiry)
    age = datetime.utcnow() - state_data["created_at"]
    if age > timedelta(minutes=10):
        _oauth_states.pop(state, None)
        raise IntegrationError("State parameter expired")

    user_id = state_data["user_id"]
    provider = state_data["provider"]
    redirect_uri = state_data["redirect_uri"]

    # Determine scopes based on provider
    if provider == "gmail":
        scopes = GMAIL_SCOPES
    elif provider == "google_calendar":
        scopes = CALENDAR_SCOPES
    else:
        raise IntegrationError(f"Unsupported provider: {provider}")

    try:
        # Create flow with same redirect_uri
        flow = Flow.from_client_secrets_file(
            str(config.credentials_file),
            scopes=scopes,
            redirect_uri=redirect_uri,
        )

        # Exchange authorization code for tokens
        flow.fetch_token(code=code)
        credentials = flow.credentials

        # Clean up state
        _oauth_states.pop(state, None)

        logger.info(f"OAuth flow completed for {provider} (user {user_id})")
        return credentials, user_id, provider

    except Exception as e:
        _oauth_states.pop(state, None)
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


def _clean_expired_states() -> None:
    """Clean up expired OAuth states (older than 10 minutes)."""
    now = datetime.utcnow()
    expired_keys = [
        state
        for state, data in _oauth_states.items()
        if now - data["created_at"] > timedelta(minutes=10)
    ]
    for key in expired_keys:
        _oauth_states.pop(key, None)
    if expired_keys:
        logger.debug(f"Cleaned up {len(expired_keys)} expired OAuth states")
