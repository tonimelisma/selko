"""Integration endpoints."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, status
from supabase import Client, PostgrestAPIError

from selko.api.deps import CurrentUser, get_authenticated_client, get_current_user
from selko.api.schemas.integrations import IntegrationResponse

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
