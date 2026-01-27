"""OAuth integration endpoints.

These endpoints handle OAuth flows requiring server-side secrets.
For direct integration queries, use Supabase client from frontend.
"""

import logging
from typing import Annotated

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

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("/gmail/auth")
async def gmail_oauth_initiate(
    user: CurrentUser = Depends(get_current_user),
    config: Config = Depends(get_config),
    redirect_uri: Annotated[str, Query(description="OAuth callback URI")] = "http://localhost:8000/integrations/gmail/callback",
) -> RedirectResponse:
    """Initiate Gmail OAuth flow.

    Redirects user to Google consent screen to authorize Gmail access.
    After authorization, Google will redirect to the callback endpoint.

    Args:
        redirect_uri: URI to redirect to after authorization (defaults to local callback).

    Returns:
        Redirect to Google OAuth consent screen.

    Raises:
        500: OAuth initiation failed.
    """

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
            detail=f"Failed to initiate OAuth: {str(e)}",
        )


@router.get("/gmail/callback")
async def gmail_oauth_callback(
    code: Annotated[str, Query(description="Authorization code from Google")],
    state: Annotated[str, Query(description="State parameter for CSRF validation")],
    config: Config = Depends(get_config),
) -> dict:
    """Handle Gmail OAuth callback (public endpoint).

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

        # Get Gmail profile to store provider email
        gmail_address = None
        try:
            service = build_service(credentials)
            profile = get_user_profile(service)
            gmail_address = profile.get("emailAddress")
        except Exception as e:
            logger.warning(f"Could not get Gmail profile: {e}")

        # Save credentials with EXPLICIT user_id
        save_oauth_credentials(client, user_id, provider, credentials, gmail_address)

        logger.info(f"Gmail OAuth completed successfully for user {user_id}")

        return {
            "status": "success",
            "provider": provider,
            "provider_email": gmail_address,
            "message": "Gmail integration connected successfully",
        }

    except IntegrationError as e:
        logger.error(f"OAuth callback failed: {e}")
        error_msg = str(e)
        if "Invalid or expired state" in error_msg or "State parameter expired" in error_msg:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=error_msg,
            )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"OAuth callback failed: {error_msg}",
        )
