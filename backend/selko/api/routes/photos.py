"""Google Photos OAuth integration endpoint.

Handles the OAuth flow for Google Photos integration.
The callback is shared via /integrations/google/callback.
"""

import logging
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Header, Query

from selko.api.deps import CurrentUser, get_config, get_current_user
from selko.config import Config
from selko.api.routes.integrations import _oauth_initiate_response

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations", tags=["integrations"])


@router.get("/photos/auth")
async def photos_oauth_initiate(
    user: CurrentUser = Depends(get_current_user),
    config: Config = Depends(get_config),
    redirect_uri: Annotated[
        str | None, Query(description="OAuth callback URI")
    ] = None,
    accept: Annotated[str | None, Header()] = None,
) -> Any:
    """Initiate Google Photos OAuth flow.

    With ``Accept: application/json``, returns ``{"auth_url": "..."}``.
    Otherwise redirects (302) to Google.
    """
    return _oauth_initiate_response(
        config=config,
        provider="google_photos",
        user_id=user.id,
        redirect_uri=redirect_uri,
        accept=accept,
    )
