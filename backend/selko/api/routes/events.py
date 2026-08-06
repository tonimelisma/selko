"""Event sync endpoints.

These endpoints require server-side secrets (Google Calendar API credentials).
For direct event queries and status updates, use Supabase client from frontend.
"""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from supabase import Client

from selko.api.deps import (
    CurrentUser,
    get_authenticated_client,
    get_current_user,
    get_service_role_client,
)
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
)
from selko.services.events import (
    EventsError,
    apply_pending_change,
    reject_pending_change,
    undo_history_event,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["events"])


@router.post("/{event_id}/sync", response_model=CalendarSyncResponse)
async def sync_event(
    event_id: UUID,
    client: Annotated[Client, Depends(get_authenticated_client)],
    user: CurrentUser = Depends(get_current_user),
) -> CalendarSyncResponse:
    """Queue an approved or previously failed event for calendar sync.

    Background workers are the sole owners of Google Calendar writes. This
    endpoint is idempotent for approved, syncing, and synced events. An
    explicit retry resets an exhausted ``sync_failed`` event to ``approved``
    so a worker can claim it with a fresh attempt budget.

    Args:
        event_id: UUID of the event to sync.

    Returns:
        Current queue/sync state.

    Raises:
        403: Not authorized to sync this event.
        404: Event not found.
        500: Queueing the retry failed.
    """
    try:
        # Verify ownership and status - use maybe_single for graceful 404
        response_fields = (
            "user_id, status, synced_at, google_calendar_event_id"
        )
        event_result = (
            client.table("events")
            .select(response_fields)
            .eq("id", str(event_id))
            .maybe_single()
            .execute()
        )

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

        current_status = event_result.data["status"]
        if current_status not in ("approved", "syncing", "synced", "sync_failed"):
            raise HTTPException(
                status_code=400,
                detail=error_detail(
                    ErrorCode.INVALID_REQUEST,
                    f"Event must be approved before syncing (current status: {current_status})",
                ),
            )

        if current_status == "sync_failed":
            # A dead-lettered event has exhausted its worker attempt budget.
            # Explicit user retry grants a fresh budget and lets the worker
            # reconcile any ambiguous prior Google insert before creating.
            (
                client.table("events")
                .update(
                    {
                        "status": "approved",
                        "sync_attempts": 0,
                        "sync_error": None,
                        "locked_by": None,
                        "locked_until": None,
                        "next_retry_at": None,
                        "dead_letter_reason": None,
                        "dead_letter_at": None,
                    }
                )
                .eq("id", str(event_id))
                .eq("status", "sync_failed")
                .execute()
            )

        # Nudge the calendar scheduler immediately — user is waiting for sync.
        # This is the in-process wake for egress inc 5 (arch A). If the pool is
        # not running (ENABLE_BACKGROUND_PROCESSING=false) or the nudge is missed,
        # the next tick (30s) catches it — degraded latency, never lost.
        try:
            from selko.api.app import worker_pool as _pool

            if _pool is not None:
                _pool.nudge()
        except Exception:
            pass

        # Re-read so a worker claim that wins immediately is reported as
        # ``syncing`` rather than treated as an approval error.
        updated_event = (
            client.table("events")
            .select(response_fields)
            .eq("id", str(event_id))
            .single()
            .execute()
        )
        return CalendarSyncResponse(
            event_id=str(event_id),
            google_calendar_event_id=updated_event.data.get(
                "google_calendar_event_id"
            ),
            synced_at=updated_event.data.get("synced_at"),
            status=updated_event.data["status"],
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to queue event sync: {e}")
        raise HTTPException(
            status_code=500,
            detail=error_detail(ErrorCode.SYNC_FAILED, "Failed to queue event sync"),
        )


@router.post("/{event_id}/unsync", response_model=EventUnsyncResponse)
async def unsync_event(
    event_id: UUID,
    client: Annotated[Client, Depends(get_authenticated_client)],
    service_client: Annotated[Client, Depends(get_service_role_client)],
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
        delete_calendar_event(service_client, user.id, str(event_id))

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
        # Nudge calendar scheduler for the newly approved event (egress inc 5).
        try:
            from selko.api.app import worker_pool as _pool

            if _pool is not None:
                _pool.nudge()
        except Exception:
            pass
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
    service_client: Annotated[Client, Depends(get_service_role_client)],
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
            service_client, str(event_id), str(user.id), force=body.force
        )
        return EventUndoResponse(event_id=str(event_id), status=status)  # type: ignore[arg-type]
    except CalendarDivergedError as e:
        raise HTTPException(
            status_code=409,
            detail={
                **error_detail(ErrorCode.CALENDAR_DIVERGED, str(e)),
                "conflict": {
                    "changed_fields": e.changed_fields,
                    "differences": e.differences,
                    "google_event_url": e.google_event_url,
                },
            },
        ) from e
    except (EventsError, CalendarsError) as e:
        raise HTTPException(
            status_code=400,
            detail=error_detail(ErrorCode.INVALID_REQUEST, str(e)),
        ) from e
