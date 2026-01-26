"""Calendars API routes."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from supabase import Client

from selko.api.deps import get_authenticated_client
from selko.api.schemas.events import (
    CalendarListResponse,
    CalendarSettingsRequest,
    CalendarSettingsResponse,
)
from selko.services import calendars

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/calendars", tags=["calendars"])


@router.get("", response_model=list[CalendarListResponse])
async def list_calendars(
    client: Annotated[Client, Depends(get_authenticated_client)],
) -> list[CalendarListResponse]:
    """List all user's Google Calendars."""
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
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/settings", response_model=CalendarSettingsResponse)
async def get_settings(
    client: Annotated[Client, Depends(get_authenticated_client)],
) -> CalendarSettingsResponse:
    """Get target calendar and default invitees."""
    try:
        user_id = client.auth.get_user().user.id
        settings = calendars.get_calendar_settings(client, user_id)
        
        return CalendarSettingsResponse(
            target_calendar_id=settings.get("target_calendar_id"),
            target_calendar_name=settings.get("target_calendar_name"),
            default_invitees=settings.get("default_invitees"),
        )
        
    except Exception as e:
        logger.error(f"Failed to get calendar settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/settings", response_model=CalendarSettingsResponse)
async def update_settings(
    request: CalendarSettingsRequest,
    client: Annotated[Client, Depends(get_authenticated_client)],
) -> CalendarSettingsResponse:
    """Update target calendar and default invitees."""
    try:
        user_id = client.auth.get_user().user.id
        
        calendars.update_calendar_settings(
            client,
            user_id,
            request.target_calendar_id,
            request.default_invitees,
        )
        
        # Return updated settings
        settings = calendars.get_calendar_settings(client, user_id)
        
        return CalendarSettingsResponse(
            target_calendar_id=settings.get("target_calendar_id"),
            target_calendar_name=settings.get("target_calendar_name"),
            default_invitees=settings.get("default_invitees"),
        )
        
    except Exception as e:
        logger.error(f"Failed to update calendar settings: {e}")
        raise HTTPException(status_code=500, detail=str(e))
