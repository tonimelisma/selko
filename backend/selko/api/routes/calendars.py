"""Calendar API endpoints.

These endpoints require server-side secrets (Google Calendar API credentials).
For calendar settings, use Supabase client from frontend.
"""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from supabase import Client

from selko.api.deps import get_authenticated_client
from selko.api.schemas.common import ErrorCode, error_detail
from selko.api.schemas.events import CalendarListResponse
from selko.services import calendars

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calendars", tags=["calendars"])


@router.get("", response_model=list[CalendarListResponse])
async def list_calendars(
    client: Annotated[Client, Depends(get_authenticated_client)],
) -> list[CalendarListResponse]:
    """List all user's Google Calendars.

    Fetches calendars from Google Calendar API.

    Returns:
        List of calendars with id, name, is_primary, is_selected.

    Raises:
        404: No Google Calendar integration found.
        500: Failed to fetch calendars.
    """
    try:
        user_id = client.auth.get_user().user.id
        calendars_data = calendars.list_calendars(client, user_id)

        return [
            CalendarListResponse(
                id=cal["id"],
                name=cal["name"],
                is_primary=cal["is_primary"],
                is_selected=cal["is_selected"],
            )
            for cal in calendars_data
        ]

    except Exception as e:
        logger.error(f"Failed to list calendars: {e}")
        if "No Google Calendar credentials" in str(e):
            raise HTTPException(
                status_code=404,
                detail=error_detail(ErrorCode.CREDENTIALS_NOT_FOUND, "No Google Calendar integration found. Connect Calendar first."),
            )
        raise HTTPException(
            status_code=500,
            detail=error_detail(ErrorCode.DATABASE_ERROR, "Failed to list calendars"),
        )
