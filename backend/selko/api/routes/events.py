"""Event sync endpoints.

These endpoints require server-side secrets (Google Calendar API credentials).
For direct event queries and status updates, use Supabase client from frontend.
"""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Response, status
from supabase import Client

from selko.api.deps import CurrentUser, get_authenticated_client, get_current_user, get_quota_service
from selko.api.schemas.common import ErrorCode, error_detail
from selko.api.schemas.events import (
    CalendarSyncResponse,
    EventChangeResponse,
    EventUndoRequest,
    EventUndoResponse,
    EventUnsyncResponse,
)
from selko.services.calendars import (
    CalendarDivergedError,
    CalendarsError,
    delete_calendar_event,
    sync_event_to_calendar,
)
from selko.services.events import (
    EventsError,
    apply_pending_change,
    reject_pending_change,
    undo_history_event,
)
from selko.services.quotas import QuotaService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["events"])


@router.post("/{event_id}/sync", response_model=CalendarSyncResponse)
async def sync_event(
    event_id: UUID,
    response: Response,
    client: Annotated[Client, Depends(get_authenticated_client)],
    user: CurrentUser = Depends(get_current_user),
    quota_service: QuotaService = Depends(get_quota_service),
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
        429: Calendar sync quota exceeded.
        500: Calendar sync failed.
    """
    # Check calendar sync quota BEFORE any expensive operations
    quota_result = quota_service.check_and_increment(user.id, "calendar_syncs")
    if not quota_result.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=error_detail(ErrorCode.QUOTA_EXCEEDED, "Daily calendar sync quota exceeded"),
            headers={
                "X-RateLimit-Limit": str(quota_result.limit),
                "X-RateLimit-Remaining": "0",
                "X-RateLimit-Reset": quota_result.resets_at,
            },
        )

    # Add quota headers to response
    response.headers["X-RateLimit-Limit"] = str(quota_result.limit)
    response.headers["X-RateLimit-Remaining"] = str(quota_result.remaining)
    response.headers["X-RateLimit-Reset"] = quota_result.resets_at

    try:
        # Verify ownership and status - use maybe_single for graceful 404
        event_result = client.table("events").select("user_id, status, synced_at").eq(
            "id", str(event_id)
        ).maybe_single().execute()

        # maybe_single() returns result where .data is None when no rows found
        if event_result is None or event_result.data is None:
            raise HTTPException(
                status_code=404,
                detail=error_detail(ErrorCode.EVENT_NOT_FOUND, "Event not found"),
            )

        if event_result.data["user_id"] != user.id:
            raise HTTPException(
                status_code=403,
                detail=error_detail(ErrorCode.FORBIDDEN, "Not authorized"),
            )

        # Validate event is approved
        if event_result.data["status"] not in ("approved", "synced"):
            raise HTTPException(
                status_code=400,
                detail=error_detail(
                    ErrorCode.INVALID_REQUEST,
                    f"Event must be approved before syncing (current status: {event_result.data['status']})",
                ),
            )

        # Sync to calendar
        google_event_id = sync_event_to_calendar(client, user.id, str(event_id))

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
                detail=error_detail(ErrorCode.CREDENTIALS_NOT_FOUND, "No Google Calendar integration found. Connect Calendar first."),
            )
        raise HTTPException(
            status_code=500,
            detail=error_detail(ErrorCode.SYNC_FAILED, "Calendar sync failed"),
        )
    except Exception as e:
        logger.error(f"Failed to sync event: {e}")
        raise HTTPException(
            status_code=500,
            detail=error_detail(ErrorCode.SYNC_FAILED, "Event sync failed"),
        )


@router.post("/{event_id}/unsync", response_model=EventUnsyncResponse)
async def unsync_event(
    event_id: UUID,
    client: Annotated[Client, Depends(get_authenticated_client)],
    user: CurrentUser = Depends(get_current_user),
) -> EventUnsyncResponse:
    """Remove a synced event from Google Calendar and revert to pending_review.

    Deletes the event from the user's Google Calendar and clears the sync
    fields. The event is reverted to pending_review status so the user can
    re-approve and re-sync if desired.

    Args:
        event_id: UUID of the event to unsync.

    Returns:
        Unsync result with event_id and new status.

    Raises:
        400: Event is not in synced status.
        403: Not authorized to unsync this event.
        404: Event not found or no calendar integration.
        500: Calendar unsync failed.
    """
    try:
        # Verify ownership and status
        event_result = client.table("events").select("user_id, status").eq(
            "id", str(event_id)
        ).maybe_single().execute()

        if event_result is None or event_result.data is None:
            raise HTTPException(
                status_code=404,
                detail=error_detail(ErrorCode.EVENT_NOT_FOUND, "Event not found"),
            )

        if event_result.data["user_id"] != user.id:
            raise HTTPException(
                status_code=403,
                detail=error_detail(ErrorCode.FORBIDDEN, "Not authorized"),
            )

        # Validate event is synced
        if event_result.data["status"] != "synced":
            raise HTTPException(
                status_code=400,
                detail=error_detail(
                    ErrorCode.INVALID_REQUEST,
                    f"Only synced events can be unsynced (current status: {event_result.data['status']})",
                ),
            )

        # Delete from Google Calendar and revert status
        delete_calendar_event(client, user.id, str(event_id))

        return EventUnsyncResponse(
            event_id=str(event_id),
            status="pending_review",
        )

    except HTTPException:
        raise
    except CalendarsError as e:
        logger.error(f"Calendar unsync failed: {e}")
        if "No Google Calendar credentials" in str(e):
            raise HTTPException(
                status_code=404,
                detail=error_detail(ErrorCode.CREDENTIALS_NOT_FOUND, "No Google Calendar integration found. Connect Calendar first."),
            )
        raise HTTPException(
            status_code=500,
            detail=error_detail(ErrorCode.SYNC_FAILED, "Calendar unsync failed"),
        )
    except Exception as e:
        logger.error(f"Failed to unsync event: {e}")
        raise HTTPException(
            status_code=500,
            detail=error_detail(ErrorCode.SYNC_FAILED, "Event unsync failed"),
        )


def _get_owned_event(client: Client, user_id: str, event_id: UUID) -> dict:
    event_result = client.table("events").select("user_id, status").eq(
        "id", str(event_id)
    ).maybe_single().execute()
    if event_result is None or event_result.data is None:
        raise HTTPException(
            status_code=404,
            detail=error_detail(ErrorCode.EVENT_NOT_FOUND, "Event not found"),
        )
    if event_result.data["user_id"] != user_id:
        raise HTTPException(
            status_code=403,
            detail=error_detail(ErrorCode.FORBIDDEN, "Not authorized"),
        )
    return event_result.data


@router.post("/{event_id}/apply-change", response_model=EventChangeResponse)
async def apply_change(
    event_id: UUID,
    client: Annotated[Client, Depends(get_authenticated_client)],
    user: CurrentUser = Depends(get_current_user),
) -> EventChangeResponse:
    """Apply a pending_change proposal and mark the event approved."""
    event = _get_owned_event(client, user.id, event_id)
    if event["status"] != "pending_change":
        raise HTTPException(
            status_code=400,
            detail=error_detail(
                ErrorCode.INVALID_REQUEST,
                f"Event must be pending_change (current status: {event['status']})",
            ),
        )
    try:
        apply_pending_change(client, str(event_id))
        return EventChangeResponse(event_id=str(event_id), status="approved")
    except EventsError as e:
        raise HTTPException(
            status_code=400,
            detail=error_detail(ErrorCode.INVALID_REQUEST, str(e)),
        ) from e


@router.post("/{event_id}/reject-change", response_model=EventChangeResponse)
async def reject_change(
    event_id: UUID,
    client: Annotated[Client, Depends(get_authenticated_client)],
    user: CurrentUser = Depends(get_current_user),
) -> EventChangeResponse:
    """Discard a pending_change proposal."""
    event = _get_owned_event(client, user.id, event_id)
    if event["status"] != "pending_change":
        raise HTTPException(
            status_code=400,
            detail=error_detail(
                ErrorCode.INVALID_REQUEST,
                f"Event must be pending_change (current status: {event['status']})",
            ),
        )
    try:
        status = reject_pending_change(client, str(event_id))
        return EventChangeResponse(event_id=str(event_id), status=status)
    except EventsError as e:
        raise HTTPException(
            status_code=400,
            detail=error_detail(ErrorCode.INVALID_REQUEST, str(e)),
        ) from e


@router.post("/{event_id}/undo", response_model=EventUndoResponse)
async def undo_event(
    event_id: UUID,
    client: Annotated[Client, Depends(get_authenticated_client)],
    user: CurrentUser = Depends(get_current_user),
    body: EventUndoRequest = EventUndoRequest(),
) -> EventUndoResponse:
    """Undo a History action back to New or Changes review lane.

    When the event is synced, also reverts Google Calendar to the pre-Selko
    state (delete for new approvals, restore snapshot for applied changes).
    If the user edited GCal after Selko's last write, returns 409 unless
    ``force`` is true.
    """
    _get_owned_event(client, user.id, event_id)
    try:
        status = undo_history_event(
            client, str(event_id), str(user.id), force=body.force
        )
        return EventUndoResponse(event_id=str(event_id), status=status)  # type: ignore[arg-type]
    except CalendarDivergedError as e:
        raise HTTPException(
            status_code=409,
            detail=error_detail(ErrorCode.CALENDAR_DIVERGED, str(e)),
        ) from e
    except (EventsError, CalendarsError) as e:
        raise HTTPException(
            status_code=400,
            detail=error_detail(ErrorCode.INVALID_REQUEST, str(e)),
        ) from e
