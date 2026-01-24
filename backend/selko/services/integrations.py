"""Integrations service for Selko.

Handles OAuth token storage and retrieval from the integrations table.
Uses RLS - all operations are scoped to the authenticated user.
"""

import logging
from datetime import datetime
from typing import Optional

from google.oauth2.credentials import Credentials
from postgrest.exceptions import APIError
from supabase import Client, PostgrestAPIError

from selko.config import Config
from selko.services.auth import get_current_user_id

logger = logging.getLogger(__name__)


class IntegrationError(Exception):
    """Raised when integration operations fail."""

    pass


def save_oauth_credentials(
    client: Client,
    provider: str,
    credentials: Credentials,
    provider_email: str = None,
) -> None:
    """Save OAuth tokens to integrations table for the current user.

    Args:
        client: Authenticated Supabase client.
        provider: Integration provider ('gmail', 'google_photos', 'google_calendar').
        credentials: Google OAuth credentials object.
        provider_email: Optional email associated with the provider account.

    Raises:
        IntegrationError: If save fails.
    """
    user_id = get_current_user_id(client)

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
) -> Optional[Credentials]:
    """Load OAuth credentials from DB for the current user.

    Reconstructs Google Credentials object with client_id/secret from config
    to enable token refresh.

    Args:
        client: Authenticated Supabase client.
        config: Configuration with Google OAuth client credentials.
        provider: Integration provider name.

    Returns:
        Google Credentials object, or None if no integration found.
    """
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
