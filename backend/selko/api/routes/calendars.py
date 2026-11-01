"""Calendar API endpoints.

These endpoints require server-side secrets (Google and Microsoft OAuth).
For calendar settings, use Supabase client from frontend.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from supabase import Client

from selko.api.deps import (
    CurrentUser,
    get_current_user,
    get_service_role_client,
)
from selko.api.schemas.common import ErrorCode, error_detail
from selko.api.schemas.events import CalendarListResponse
from selko.services import calendars

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calendars", tags=["calendars"])


@router.get("", response_model=list[CalendarListResponse])
async def list_calendars(
    service_client: Annotated[Client, Depends(get_service_role_client)],
    user: CurrentUser = Depends(get_current_user),
) -> list[CalendarListResponse]:
    """List the calendars Selko can write to, across Google and Outlook.

    Returns:
        List of calendars with id, name, is_primary, is_selected, provider.

    Raises:
        404: No calendar integration found.
        500: Failed to fetch calendars.
    """
    try:
        calendars_data = calendars.list_calendars(service_client, user.id)

        return [
            CalendarListResponse(
                id=cal["id"],
                name=cal["name"],
                is_primary=cal["is_primary"],
                is_selected=cal["is_selected"],
                provider=cal.get("provider", "google_calendar"),
            )
            for cal in calendars_data
        ]

    except Exception as e:
        logger.error(f"Failed to list calendars: {e}")
        if "No Google Calendar credentials" in str(e) or "No Outlook Calendar credentials" in str(e):
            raise HTTPException(
                status_code=404,
                detail=error_detail(ErrorCode.CREDENTIALS_NOT_FOUND, "No calendar integration found. Connect a calendar first."),
            )
        raise HTTPException(
            status_code=500,
            detail=error_detail(ErrorCode.DATABASE_ERROR, "Failed to list calendars"),
        )
