"""Google Photos OAuth integration endpoint.

Handles the OAuth flow for Google Photos integration.
The callback is shared via /integrations/google/callback.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse

from selko.api.deps import CurrentUser, get_config, get_current_user
from selko.api.schemas.common import ErrorCode, error_detail
from selko.config import Config
from selko.services.integrations import (
    IntegrationError,
    initiate_oauth_flow,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("/photos/auth")
async def photos_oauth_initiate(
    user: CurrentUser = Depends(get_current_user),
    config: Config = Depends(get_config),
    redirect_uri: Annotated[str, Query(description="OAuth callback URI")] = "http://localhost:8000/integrations/google/callback",
) -> RedirectResponse:
    """Initiate Google Photos OAuth flow.

    Redirects user to Google consent screen to authorize Photos access.
    After authorization, Google will redirect to the unified callback endpoint.

    Args:
        redirect_uri: URI to redirect to after authorization (defaults to local callback).

    Returns:
        Redirect to Google OAuth consent screen.

    Raises:
        400: Invalid redirect URI.
        500: OAuth initiation failed.
    """
    # Validate redirect_uri using the same validation from integrations module
    from selko.api.routes.integrations import _validate_redirect_uri

    if not _validate_redirect_uri(redirect_uri):
        logger.warning(f"Invalid redirect_uri attempted: {redirect_uri}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=error_detail(ErrorCode.INVALID_REQUEST, "Invalid redirect URI"),
        )

    try:
        result = initiate_oauth_flow(
            config=config,
            provider="google_photos",
            user_id=user.id,
            redirect_uri=redirect_uri,
        )

        # Redirect user to Google OAuth consent screen
        return RedirectResponse(url=result["auth_url"], status_code=status.HTTP_302_FOUND)

    except IntegrationError as e:
        logger.error(f"Failed to initiate Google Photos OAuth: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=error_detail(ErrorCode.OAUTH_FAILED, "Failed to initiate OAuth flow"),
        )
