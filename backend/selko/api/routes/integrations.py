"""Integration endpoints."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from fastapi.responses import RedirectResponse
from supabase import Client, PostgrestAPIError

from selko.api.deps import CurrentUser, get_authenticated_client, get_current_user, get_config
from selko.config import Config
from selko.api.schemas.integrations import IntegrationResponse
from selko.services.gmail import build_service, get_user_profile
from selko.services.integrations import (
    IntegrationError,
    complete_oauth_flow,
    delete_integration,
    initiate_oauth_flow,
    save_oauth_credentials,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/integrations", tags=["integrations"])

# Valid integration providers
VALID_PROVIDERS = {"gmail", "google_photos", "google_calendar"}


@router.get("", response_model=list[IntegrationResponse])
async def list_integrations(
    client: Client = Depends(get_authenticated_client),
    user: CurrentUser = Depends(get_current_user),
) -> list[IntegrationResponse]:
    """List all integrations for the authenticated user.

    Returns all connected integrations (Gmail, Google Photos, Google Calendar).
    Tokens are excluded from the response for security.

    Returns:
        List of integrations.
    """
    try:
        result = (
            client.table("integrations")
            .select(
                "id, user_id, provider, status, provider_email, "
                "scopes, token_expiry, last_history_id, last_sync_at, created_at, updated_at"
            )
            .eq("user_id", user.id)
            .order("provider")
            .execute()
        )

        return [IntegrationResponse(**row) for row in result.data]

    except PostgrestAPIError as e:
        logger.error(f"Failed to list integrations: {e.message}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve integrations",
        )


@router.get("/{provider}", response_model=IntegrationResponse)
async def get_integration(
    provider: Annotated[str, Path(description="Integration provider name")],
    client: Client = Depends(get_authenticated_client),
    user: CurrentUser = Depends(get_current_user),
) -> IntegrationResponse:
    """Get a specific integration by provider name.

    Args:
        provider: Integration provider ('gmail', 'google_photos', 'google_calendar').

    Returns:
        Integration details (tokens excluded).

    Raises:
        400: Invalid provider name.
        404: Integration not found.
    """
    if provider not in VALID_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid provider. Valid options: {', '.join(sorted(VALID_PROVIDERS))}",
        )

    try:
        result = (
            client.table("integrations")
            .select(
                "id, user_id, provider, status, provider_email, "
                "scopes, token_expiry, last_history_id, last_sync_at, created_at, updated_at"
            )
            .eq("user_id", user.id)
            .eq("provider", provider)
            .maybe_single()
            .execute()
        )

        if result is None or not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No {provider} integration found",
            )

        return IntegrationResponse(**result.data)

    except HTTPException:
        raise
    except PostgrestAPIError as e:
        logger.error(f"Failed to get integration: {e.message}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve integration",
        )


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


@router.delete("/{provider}", status_code=status.HTTP_204_NO_CONTENT)
async def disconnect_integration(
    provider: Annotated[str, Path(description="Integration provider name")],
    client: Client = Depends(get_authenticated_client),
    user: CurrentUser = Depends(get_current_user),
) -> None:
    """Disconnect an integration.

    Deletes the integration and all associated tokens from the database.

    Args:
        provider: Integration provider ('gmail', 'google_photos', 'google_calendar').

    Raises:
        400: Invalid provider name.
        500: Deletion failed.
    """
    if provider not in VALID_PROVIDERS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid provider. Valid options: {', '.join(sorted(VALID_PROVIDERS))}",
        )

    try:
        delete_integration(client, provider)
        logger.info(f"Disconnected {provider} for user {user.id}")

    except IntegrationError as e:
        logger.error(f"Failed to disconnect integration: {e}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to disconnect integration: {str(e)}",
        )
