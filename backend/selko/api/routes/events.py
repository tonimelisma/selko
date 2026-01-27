"""Event sync endpoints.

These endpoints require server-side secrets (Google Calendar API credentials).
For direct event queries and status updates, use Supabase client from frontend.
"""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from supabase import Client

from selko.api.deps import get_authenticated_client
from selko.api.schemas.events import CalendarSyncResponse
from selko.services.calendars import CalendarsError, sync_event_to_calendar

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["events"])


@router.post("/{event_id}/sync", response_model=CalendarSyncResponse)
async def sync_event(
    event_id: UUID,
    client: Annotated[Client, Depends(get_authenticated_client)],
) -> CalendarSyncResponse:
    """Sync approved event to Google Calendar.

    Writes the event to the user's configured Google Calendar. The event must
    be in 'approved' status before syncing.

    Args:
        event_id: UUID of the event to sync.

    Returns:
        Sync result with Google Calendar event ID.

    Raises:
        403: Not authorized to sync this event.
        404: Event not found or no calendar integration.
        500: Calendar sync failed.
    """
    try:
        user_id = client.auth.get_user().user.id

        # Verify ownership and status - use maybe_single for graceful 404
        event_result = client.table("events").select("user_id, status, synced_at").eq(
            "id", str(event_id)
        ).maybe_single().execute()

        # maybe_single() returns result where .data is None when no rows found
        if event_result is None or event_result.data is None:
            raise HTTPException(status_code=404, detail="Event not found")

        if event_result.data["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="Not authorized")

        # Validate event is approved
        if event_result.data["status"] not in ("approved", "synced"):
            raise HTTPException(
                status_code=400,
                detail=f"Event must be approved before syncing (current status: {event_result.data['status']})"
            )

        # Sync to calendar
        google_event_id = sync_event_to_calendar(client, user_id, str(event_id))

        # Fetch updated event to get synced_at
        updated_event = client.table("events").select("synced_at").eq(
            "id", str(event_id)
        ).single().execute()

        return CalendarSyncResponse(
            event_id=str(event_id),
            google_calendar_event_id=google_event_id,
            synced_at=updated_event.data["synced_at"],
            status="synced"
        )

    except HTTPException:
        raise
    except CalendarsError as e:
        logger.error(f"Calendar sync failed: {e}")
        if "No Google Calendar credentials" in str(e):
            raise HTTPException(
                status_code=404,
                detail="No Google Calendar integration found. Connect Calendar first."
            )
        raise HTTPException(
            status_code=500,
            detail=f"Calendar sync failed: {str(e)}"
        )
    except Exception as e:
        logger.error(f"Failed to sync event: {e}")
        raise HTTPException(status_code=500, detail=str(e))
