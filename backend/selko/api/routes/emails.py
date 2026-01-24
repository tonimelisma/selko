"""Email endpoints."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from supabase import Client, PostgrestAPIError

from selko.api.deps import CurrentUser, get_authenticated_client, get_current_user
from selko.api.schemas.common import PaginatedResponse
from selko.api.schemas.emails import EmailResponse

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/emails", tags=["emails"])


@router.get("", response_model=PaginatedResponse[EmailResponse])
async def list_emails(
    client: Client = Depends(get_authenticated_client),
    user: CurrentUser = Depends(get_current_user),
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> PaginatedResponse[EmailResponse]:
    """List emails for the authenticated user.

    Emails are returned in reverse chronological order (newest first).
    Uses pagination with offset and limit.

    Args:
        offset: Number of records to skip (default 0).
        limit: Maximum records to return (default 20, max 100).

    Returns:
        Paginated list of emails.
    """
    try:
        # Get total count for pagination
        count_result = (
            client.table("emails")
            .select("id", count="exact")
            .eq("user_id", user.id)
            .execute()
        )
        total = count_result.count or 0

        # Get paginated results
        result = (
            client.table("emails")
            .select("*")
            .eq("user_id", user.id)
            .order("date_sent", desc=True)
            .range(offset, offset + limit - 1)
            .execute()
        )

        emails = [EmailResponse(**row) for row in result.data]

        return PaginatedResponse(
            items=emails,
            total=total,
            offset=offset,
            limit=limit,
        )

    except PostgrestAPIError as e:
        logger.error(f"Failed to list emails: {e.message}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve emails",
        )


@router.get("/{email_id}", response_model=EmailResponse)
async def get_email(
    email_id: Annotated[str, Path(description="Email UUID")],
    client: Client = Depends(get_authenticated_client),
    user: CurrentUser = Depends(get_current_user),
) -> EmailResponse:
    """Get a single email by ID.

    Args:
        email_id: UUID of the email to retrieve.

    Returns:
        Email details.

    Raises:
        404: Email not found or not owned by user.
    """
    try:
        result = (
            client.table("emails")
            .select("*")
            .eq("id", email_id)
            .eq("user_id", user.id)
            .maybe_single()
            .execute()
        )

        if result is None or not result.data:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Email not found",
            )

        return EmailResponse(**result.data)

    except HTTPException:
        raise
    except PostgrestAPIError as e:
        logger.error(f"Failed to get email: {e.message}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to retrieve email",
        )
