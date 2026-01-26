"""Events API routes."""

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from supabase import Client

from selko.api.deps import get_authenticated_client, get_gemini_client
from selko.api.schemas.events import (
    EventResponse,
    EventSourceResponse,
    EventWithSources,
)
from selko.config import Config
from selko.services import events

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/events", tags=["events"])


@router.get("/new", response_model=list[EventResponse])
async def list_new_events(
    client: Annotated[Client, Depends(get_authenticated_client)],
) -> list[EventResponse]:
    """List events pending approval, grouped by sender."""
    try:
        user_id = client.auth.get_user().user.id
        events_data = events.get_events_new(client, user_id)
        
        # Transform to response model
        result = []
        for event_data in events_data:
            # Count sources
            sources = event_data.get("event_sources", [])
            source_count = len([s for s in sources if not s.get("is_undone")])
            
            # Get primary sender (first source)
            primary_sender = "Unknown"
            if sources:
                first_source = sources[0]
                email = first_source.get("emails", {})
                primary_sender = email.get("from_name") or email.get("from_email", "Unknown")
            
            result.append(EventResponse(
                id=event_data["id"],
                title=event_data["title"],
                start_datetime=event_data.get("start_datetime"),
                end_datetime=event_data.get("end_datetime"),
                all_day=event_data.get("all_day", False),
                location=event_data.get("location"),
                status=event_data["status"],
                source_count=source_count,
                primary_sender=primary_sender,
                created_at=event_data["created_at"],
                updated_at=event_data["updated_at"],
            ))
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to list new events: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/approved", response_model=list[EventResponse])
async def list_approved_events(
    client: Annotated[Client, Depends(get_authenticated_client)],
) -> list[EventResponse]:
    """List approved/synced events."""
    try:
        user_id = client.auth.get_user().user.id
        events_data = events.get_events_approved(client, user_id)
        
        result = []
        for event_data in events_data:
            # Get source count
            sources_result = client.table("event_sources").select("id").eq(
                "event_id", event_data["id"]
            ).eq("is_undone", False).execute()
            source_count = len(sources_result.data)
            
            # Get primary sender
            first_source = client.table("event_sources").select(
                "emails(from_name, from_email)"
            ).eq("event_id", event_data["id"]).order("created_at").limit(1).execute()
            
            primary_sender = "Unknown"
            if first_source.data and first_source.data[0].get("emails"):
                email = first_source.data[0]["emails"]
                primary_sender = email.get("from_name") or email.get("from_email", "Unknown")
            
            result.append(EventResponse(
                id=event_data["id"],
                title=event_data["title"],
                start_datetime=event_data.get("start_datetime"),
                end_datetime=event_data.get("end_datetime"),
                all_day=event_data.get("all_day", False),
                location=event_data.get("location"),
                status=event_data["status"],
                source_count=source_count,
                primary_sender=primary_sender,
                created_at=event_data["created_at"],
                updated_at=event_data["updated_at"],
            ))
        
        return result
        
    except Exception as e:
        logger.error(f"Failed to list approved events: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/updates")
async def list_updates(
    client: Annotated[Client, Depends(get_authenticated_client)],
):
    """List change log (updates, cancellations, rejections)."""
    try:
        user_id = client.auth.get_user().user.id
        updates_data = events.get_events_updates(client, user_id)
        
        return updates_data
        
    except Exception as e:
        logger.error(f"Failed to list updates: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{event_id}", response_model=EventWithSources)
async def get_event_detail(
    event_id: UUID,
    client: Annotated[Client, Depends(get_authenticated_client)],
) -> EventWithSources:
    """Get event with all source emails."""
    try:
        user_id = client.auth.get_user().user.id
        event_data = events.get_event_with_sources(client, str(event_id))
        
        # Check ownership
        if event_data["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="Not authorized")
        
        # Transform sources
        sources = []
        for source_data in event_data.get("event_sources", []):
            email = source_data.get("emails", {})
            sources.append(EventSourceResponse(
                id=source_data["id"],
                email_id=source_data["email_id"],
                email_subject=email.get("subject", ""),
                email_sender=email.get("from_email", ""),
                email_sender_name=email.get("from_name"),
                email_date=email.get("date_sent"),
                source_type=source_data["source_type"],
                source_quote=source_data.get("extracted_data", {}).get("source_quote", ""),
                is_undone=source_data.get("is_undone", False),
                created_at=source_data["created_at"],
            ))
        
        # Get primary sender
        primary_sender = "Unknown"
        if sources:
            primary_sender = sources[0].email_sender_name or sources[0].email_sender
        
        return EventWithSources(
            id=event_data["id"],
            title=event_data["title"],
            start_datetime=event_data.get("start_datetime"),
            end_datetime=event_data.get("end_datetime"),
            all_day=event_data.get("all_day", False),
            location=event_data.get("location"),
            status=event_data["status"],
            source_count=len([s for s in sources if not s.is_undone]),
            primary_sender=primary_sender,
            created_at=event_data["created_at"],
            updated_at=event_data["updated_at"],
            description=event_data.get("description", ""),
            source_attribution=event_data.get("source_attribution", ""),
            google_calendar_event_id=event_data.get("google_calendar_event_id"),
            synced_at=event_data.get("synced_at"),
            sources=sources,
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to get event detail: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{event_id}/approve")
async def approve_event(
    event_id: UUID,
    client: Annotated[Client, Depends(get_authenticated_client)],
):
    """Approve event for calendar sync."""
    try:
        user_id = client.auth.get_user().user.id
        
        # Verify ownership
        event_result = client.table("events").select("user_id").eq(
            "id", str(event_id)
        ).single().execute()
        if event_result.data["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="Not authorized")
        
        events.approve_event(client, str(event_id))
        
        return {"status": "approved"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to approve event: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{event_id}/reject")
async def reject_event(
    event_id: UUID,
    client: Annotated[Client, Depends(get_authenticated_client)],
):
    """Reject event."""
    try:
        user_id = client.auth.get_user().user.id
        
        # Verify ownership
        event_result = client.table("events").select("user_id").eq(
            "id", str(event_id)
        ).single().execute()
        if event_result.data["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="Not authorized")
        
        events.reject_event(client, str(event_id))
        
        return {"status": "rejected"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to reject event: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{event_id}/restore")
async def restore_event(
    event_id: UUID,
    client: Annotated[Client, Depends(get_authenticated_client)],
):
    """Restore rejected event to New."""
    try:
        user_id = client.auth.get_user().user.id
        
        # Verify ownership
        event_result = client.table("events").select("user_id").eq(
            "id", str(event_id)
        ).single().execute()
        if event_result.data["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="Not authorized")
        
        events.restore_rejected_event(client, str(event_id))
        
        return {"status": "restored"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to restore event: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{event_id}/sources")
async def list_event_sources(
    event_id: UUID,
    client: Annotated[Client, Depends(get_authenticated_client)],
):
    """List all emails that contributed to event."""
    try:
        user_id = client.auth.get_user().user.id
        
        # Verify ownership
        event_result = client.table("events").select("user_id").eq(
            "id", str(event_id)
        ).single().execute()
        if event_result.data["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="Not authorized")
        
        # Get sources
        sources_result = client.table("event_sources").select(
            "*, emails(*)"
        ).eq("event_id", str(event_id)).order("created_at").execute()
        
        return sources_result.data
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to list event sources: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{event_id}/sources/{source_id}/undo")
async def undo_source(
    event_id: UUID,
    source_id: UUID,
    client: Annotated[Client, Depends(get_authenticated_client)],
):
    """Undo specific email's contribution."""
    try:
        user_id = client.auth.get_user().user.id
        
        # Verify ownership
        event_result = client.table("events").select("user_id").eq(
            "id", str(event_id)
        ).single().execute()
        if event_result.data["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="Not authorized")
        
        events.undo_email_contribution(client, str(source_id))
        
        return {"status": "undone"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to undo source: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/{event_id}/sources/{source_id}/redo")
async def redo_source(
    event_id: UUID,
    source_id: UUID,
    client: Annotated[Client, Depends(get_authenticated_client)],
):
    """Re-apply undone contribution."""
    try:
        user_id = client.auth.get_user().user.id
        
        # Verify ownership
        event_result = client.table("events").select("user_id").eq(
            "id", str(event_id)
        ).single().execute()
        if event_result.data["user_id"] != user_id:
            raise HTTPException(status_code=403, detail="Not authorized")
        
        events.redo_email_contribution(client, str(source_id))
        
        return {"status": "redone"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to redo source: {e}")
        raise HTTPException(status_code=500, detail=str(e))
