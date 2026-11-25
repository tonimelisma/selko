"""Event sync endpoints.

These endpoints require server-side secrets (Google Calendar API credentials).
Review transitions go through the data layer's named transitions
(`selko.db.proposals`, `selko.db.calendar_work`) so approval always creates
worker-owned work. Every read is scoped to the signed-in user.
"""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from selko.api.deps import (
    CurrentUser,
    get_authenticated_client,
    get_current_user,
    get_service_role_client,
)
from selko.api.schemas.common import ErrorCode, error_detail
from selko.db import calendar_work as db_calendar_work
from selko.db import events as db_events
from selko.db import proposals as db_proposals
from selko.db.connection import Database
from selko.api.schemas.events import (
    CalendarSyncResponse,
    EventChangeResponse,
    EventUndoRequest,
    EventUndoResponse,
)
from selko.services.calendars import (
    CalendarDivergedError,
    CalendarsError,
)
from selko.services.events import (
    EventsError,
    apply_change_proposal,
    reject_change_proposal,
    derive_delivery_status,
    undo_history_event,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["events"])


@router.post("/{event_id}/sync", response_model=CalendarSyncResponse)
async def sync_event(
    event_id: UUID,
    client: Annotated[Database, Depends(get_authenticated_client)],
    service_client: Annotated[Database, Depends(get_service_role_client)],
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
        404: Event not found (or not the caller's).
        500: Queueing the retry failed.
    """
    try:
        event = db_events.get_with_work_items(client, user.id, str(event_id))
        # Another user's event is indistinguishable from a missing one.
        if event is None:
            raise HTTPException(
                status_code=404,
                detail=error_detail(ErrorCode.EVENT_NOT_FOUND, "Event not found"),
            )

        current_status = derive_delivery_status(event)
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
            desired_event = {
                key: event.get(key)
                for key in (
                    "title", "start_datetime", "end_datetime", "all_day",
                    "location", "description", "importance", "source_attribution",
                )
            }
            db_calendar_work.enqueue_calendar_work(
                service_client, user.id, str(event_id), "upsert", desired_event, None, False
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
        updated_event = db_events.get_with_work_items(client, user.id, str(event_id)) or event
        return CalendarSyncResponse(
            event_id=str(event_id),
            google_calendar_event_id=updated_event.get("google_calendar_event_id"),
            synced_at=updated_event.get("synced_at"),
            status=derive_delivery_status(updated_event),
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to queue event sync: {e}")
        raise HTTPException(
            status_code=500,
            detail=error_detail(ErrorCode.SYNC_FAILED, "Failed to queue event sync"),
        )


def _get_owned_event(client: Database, user_id: str, event_id: UUID) -> dict:
    event = db_events.get(client, user_id, str(event_id))
    if event is None:
        # Another user's event is indistinguishable from a missing one.
        raise HTTPException(
            status_code=404,
            detail=error_detail(ErrorCode.EVENT_NOT_FOUND, "Event not found"),
        )
    return event


def _get_owned_pending_proposal(client: Database, user_id: str, event_id: UUID) -> dict:
    proposal = db_proposals.get_pending(client, user_id, str(event_id))
    if proposal is None:
        raise HTTPException(
            status_code=400,
            detail=error_detail(ErrorCode.INVALID_REQUEST, "Event has no pending change proposal"),
        )
    return proposal


@router.post("/{event_id}/apply-change", response_model=EventChangeResponse)
async def apply_change(
    event_id: UUID,
    client: Annotated[Database, Depends(get_authenticated_client)],
    service_client: Annotated[Database, Depends(get_service_role_client)],
    user: CurrentUser = Depends(get_current_user),
) -> EventChangeResponse:
    """Apply the event's authoritative pending change proposal."""
    _get_owned_event(client, user.id, event_id)
    proposal = _get_owned_pending_proposal(client, user.id, event_id)
    try:
        applied = apply_change_proposal(
            service_client, str(event_id), proposal["id"], user_id=user.id
        )
        # Nudge calendar scheduler for the newly approved event (egress inc 5).
        try:
            from selko.api.app import worker_pool as _pool

            if _pool is not None:
                _pool.nudge()
        except Exception:
            pass
        # apply_change_proposal returns the update_fields it wrote, which carry
        # review_status. There is no "status" key: events.status was deleted by
        # 20260829000001 and this line was not updated with it, so every accept
        # raised KeyError and returned 500. Users could not accept a change at
        # all for eight days, and no test noticed because no test calls this
        # route -- only the service function underneath it.
        return EventChangeResponse(event_id=str(event_id), status=applied["review_status"])
    except EventsError as e:
        raise HTTPException(
            status_code=400,
            detail=error_detail(ErrorCode.INVALID_REQUEST, str(e)),
        ) from e


@router.post("/{event_id}/reject-change", response_model=EventChangeResponse)
async def reject_change(
    event_id: UUID,
    client: Annotated[Database, Depends(get_authenticated_client)],
    service_client: Annotated[Database, Depends(get_service_role_client)],
    user: CurrentUser = Depends(get_current_user),
) -> EventChangeResponse:
    """Reject the event's authoritative pending change proposal."""
    _get_owned_event(client, user.id, event_id)
    proposal = _get_owned_pending_proposal(client, user.id, event_id)
    try:
        status = reject_change_proposal(
            service_client, str(event_id), proposal["id"], user_id=user.id
        )
        return EventChangeResponse(event_id=str(event_id), status=status)
    except EventsError as e:
        raise HTTPException(
            status_code=400,
            detail=error_detail(ErrorCode.INVALID_REQUEST, str(e)),
        ) from e


@router.post("/{event_id}/undo", response_model=EventUndoResponse)
async def undo_event(
    event_id: UUID,
    client: Annotated[Database, Depends(get_authenticated_client)],
    service_client: Annotated[Database, Depends(get_service_role_client)],
    user: CurrentUser = Depends(get_current_user),
    body: EventUndoRequest = EventUndoRequest(),
) -> EventUndoResponse:
    """Undo a History action back to New or Changes review lane.

    When the event is synced, queues a worker-owned compensation for the
    pre-Selko state (delete for new approvals, restore snapshot for applied
    changes). The request performs no provider write. If the user edited GCal
    after Selko's last write, returns 409 unless ``force`` is true.
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
