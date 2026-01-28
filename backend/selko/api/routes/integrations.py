"""OAuth integration endpoints.

These endpoints handle OAuth flows requiring server-side secrets.
For direct integration queries, use Supabase client from frontend.
"""

import logging
from typing import Annotated
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse

from selko.api.deps import CurrentUser, get_config, get_current_user
from selko.config import Config
from selko.services.gmail import build_service, get_user_profile
from selko.services.integrations import (
    IntegrationError,
    complete_oauth_flow,
    initiate_oauth_flow,
    save_oauth_credentials,
)

# Allowed redirect URIs for OAuth flows
# Add production URLs as needed
ALLOWED_REDIRECT_HOSTS = {
    "localhost",
    "127.0.0.1",
    "api.selko.app",  # Production API
}

ALLOWED_REDIRECT_PATHS = {
    "/integrations/google/callback",  # Unified for all Google providers
}

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations", tags=["integrations"])


def _validate_redirect_uri(redirect_uri: str) -> bool:
    """Validate redirect URI against allowlist to prevent open redirect attacks.

    Args:
        redirect_uri: The URI to validate.

    Returns:
        True if valid, False otherwise.
    """
    try:
        parsed = urlparse(redirect_uri)
        # Check scheme is http or https
        if parsed.scheme not in ("http", "https"):
            return False
        # Check host is in allowlist
        host = parsed.hostname
        if host not in ALLOWED_REDIRECT_HOSTS:
            return False
        # Check path is a valid callback path
        if parsed.path not in ALLOWED_REDIRECT_PATHS:
            return False
        return True
    except Exception:
        return False


@router.get("/gmail/auth")
async def gmail_oauth_initiate(
    user: CurrentUser = Depends(get_current_user),
    config: Config = Depends(get_config),
    redirect_uri: Annotated[str, Query(description="OAuth callback URI")] = "http://localhost:8000/integrations/google/callback",
) -> RedirectResponse:
    """Initiate Gmail OAuth flow.

    Redirects user to Google consent screen to authorize Gmail access.
    After authorization, Google will redirect to the callback endpoint.

    Args:
        redirect_uri: URI to redirect to after authorization (defaults to local callback).

    Returns:
        Redirect to Google OAuth consent screen.

    Raises:
        400: Invalid redirect URI.
        500: OAuth initiation failed.
    """
    # Validate redirect_uri to prevent open redirect attacks
    if not _validate_redirect_uri(redirect_uri):
        logger.warning(f"Invalid redirect_uri attempted: {redirect_uri}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid redirect URI",
        )

    try:
        result = initiate_oauth_flow(
            config=config,
            provider="gmail",
            user_id=user.id,
            redirect_uri=redirect_uri,
        )

        # Redirect user to Google OAuth consent screen
        return RedirectResponse(url=result["auth_url"], status_code=status.HTTP_302_FOUND)

    except IntegrationError as e:
        logger.error(f"Failed to initiate OAuth: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initiate OAuth flow",
        )


@router.get("/google/callback")
async def google_oauth_callback(
    code: Annotated[str, Query(description="Authorization code from Google")],
    state: Annotated[str, Query(description="State parameter for CSRF validation")],
    config: Config = Depends(get_config),
) -> dict:
    """Handle Google OAuth callback (public endpoint).

    Unified callback for all Google integrations (Gmail, Calendar, etc.).
    The provider is determined from the state parameter.

    Exchanges authorization code for access and refresh tokens.
    Stores tokens in the integrations table.

    This endpoint is PUBLIC - no JWT authentication required.
    Security is provided by state parameter validation.

    Args:
        code: Authorization code from Google.
        state: State parameter for CSRF validation.

    Returns:
        Success message with integration status.

    Raises:
        400: Invalid or expired state.
        500: Token exchange or save failed.
    """
    try:
        # Validate state and extract user_id FIRST
        credentials, user_id, provider = complete_oauth_flow(
            config=config,
            code=code,
            state=state,
        )

        # Create service role client (bypasses RLS for explicit user_id)
        from selko.services.auth import get_service_client
        client = get_service_client(config)

        # Get provider-specific profile info
        provider_email = None
        if provider == "gmail":
            try:
                service = build_service(credentials)
                profile = get_user_profile(service)
                provider_email = profile.get("emailAddress")
            except Exception as e:
                logger.warning(f"Could not get Gmail profile: {e}")
        # For google_calendar and other providers, we don't fetch profile info
        # (Calendar API doesn't have a user profile endpoint)

        # Save credentials with EXPLICIT user_id
        save_oauth_credentials(client, user_id, provider, credentials, provider_email)

        logger.info(f"{provider} OAuth completed successfully for user {user_id}")

        # Build provider-specific success message
        provider_display = {
            "gmail": "Gmail",
            "google_calendar": "Google Calendar",
        }.get(provider, provider)

        return {
            "status": "success",
            "provider": provider,
            "provider_email": provider_email,
            "message": f"{provider_display} integration connected successfully",
        }

    except IntegrationError as e:
        logger.error(f"OAuth callback failed: {e}")
        error_msg = str(e)
        if "Invalid or expired state" in error_msg or "State parameter expired" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="OAuth state invalid or expired. Please try again.",
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="OAuth callback failed",
        )


@router.get("/calendar/auth")
async def calendar_oauth_initiate(
    user: CurrentUser = Depends(get_current_user),
    config: Config = Depends(get_config),
    redirect_uri: Annotated[str, Query(description="OAuth callback URI")] = "http://localhost:8000/integrations/google/callback",
) -> RedirectResponse:
    """Initiate Google Calendar OAuth flow.

    Redirects user to Google consent screen to authorize Calendar access.
    After authorization, Google will redirect to the unified callback endpoint.

    Args:
        redirect_uri: URI to redirect to after authorization (defaults to local callback).

    Returns:
        Redirect to Google OAuth consent screen.

    Raises:
        400: Invalid redirect URI.
        500: OAuth initiation failed.
    """
    # Validate redirect_uri to prevent open redirect attacks
    if not _validate_redirect_uri(redirect_uri):
        logger.warning(f"Invalid redirect_uri attempted: {redirect_uri}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid redirect URI",
        )

    try:
        result = initiate_oauth_flow(
            config=config,
            provider="google_calendar",
            user_id=user.id,
            redirect_uri=redirect_uri,
        )

        # Redirect user to Google OAuth consent screen
        return RedirectResponse(url=result["auth_url"], status_code=status.HTTP_302_FOUND)

    except IntegrationError as e:
        logger.error(f"Failed to initiate OAuth: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to initiate OAuth flow",
        )
