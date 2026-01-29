"""Events service for event extraction, deduplication, and management."""

import logging
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from supabase import Client

from selko.services import gemini
from selko.services.llm_logging import LLMLoggingService

logger = logging.getLogger(__name__)


class EventsError(Exception):
    """Raised when event operations fail."""

    pass


def process_email_for_events(
    supabase_client: Client,
    gemini_client: Any,
    email_id: str,
    user_id: str,
    logging_service: Optional[LLMLoggingService] = None,
) -> dict[str, Any]:
    """Main pipeline function to extract events from an email.

    Steps:
    1. Check if sender is ignored
    2. Extract events from email using Gemini
    3. For each event, check if it matches existing events (dedup)
    4. Create new or update existing events
    5. Check sender rules for auto-approve

    Args:
        supabase_client: Authenticated Supabase client.
        gemini_client: Initialized Gemini client.
        email_id: UUID of email to process.
        user_id: UUID of user who owns the email.
        logging_service: Optional LLM logging service for call auditing.

    Returns:
        Dict with processing results (num_events, num_new, num_updated).

    Raises:
        EventsError: If processing fails.
    """
    try:
        # Mark email as processing
        supabase_client.table("emails").update({
            "processing_status": "processing",
            "processed_at": datetime.now().isoformat()
        }).eq("id", email_id).execute()
        
        # Fetch email data
        email_metadata, email_text, attachments = gemini.fetch_email_with_attachments(
            supabase_client, email_id
        )
        
        sender_email = email_metadata.get("from_email", "")
        
        # Check if sender is ignored
        sender_rule = check_sender_rules(supabase_client, user_id, sender_email)
        if sender_rule and sender_rule.get("action") == "ignore":
            logger.info(f"Sender {sender_email} is ignored, skipping event extraction")
            supabase_client.table("emails").update({
                "processing_status": "skipped",
            }).eq("id", email_id).execute()
            return {"num_events": 0, "num_new": 0, "num_updated": 0, "skipped": True}
        
        # Extract events using Gemini
        extraction = gemini.extract_calendar_events(
            gemini_client,
            email_text,
            email_metadata,
            attachments,
            logging_service=logging_service,
            user_id=user_id,
            email_id=email_id,
        )
        
        if not extraction.events_found or not extraction.events:
            logger.info("No events found in email")
            supabase_client.table("emails").update({
                "processing_status": "processed",
            }).eq("id", email_id).execute()
            return {"num_events": 0, "num_new": 0, "num_updated": 0}
        
        num_new = 0
        num_updated = 0
        
        # Process each extracted event
        for event in extraction.events:
            event_data = {
                "title": event.title,
                "start_datetime": event.start_datetime.isoformat() if event.start_datetime else None,
                "end_datetime": event.end_datetime.isoformat() if event.end_datetime else None,
                "all_day": getattr(event, 'all_day', False),
                "location": event.location,
                "description": event.description,
                "source_quote": getattr(event, 'source_quote', ''),
            }
            
            # Find matching event (date-based + LLM comparison)
            matched_event_id = find_matching_event(
                supabase_client,
                gemini_client,
                user_id,
                event_data,
                logging_service=logging_service,
            )
            
            if matched_event_id:
                # Update existing event
                update_event(
                    supabase_client,
                    gemini_client,
                    matched_event_id,
                    event_data,
                    email_id,
                    "update",
                    logging_service=logging_service,
                    user_id=user_id,
                )
                num_updated += 1
            else:
                # Create new event
                create_event(
                    supabase_client,
                    user_id,
                    event_data,
                    email_id
                )
                num_new += 1
        
        # Mark email as processed
        supabase_client.table("emails").update({
            "processing_status": "processed",
        }).eq("id", email_id).execute()
        
        logger.info(f"Processed email {email_id}: {num_new} new, {num_updated} updated events")
        
        return {
            "num_events": len(extraction.events),
            "num_new": num_new,
            "num_updated": num_updated
        }
        
    except Exception as e:
        # Mark email as failed
        supabase_client.table("emails").update({
            "processing_status": "failed",
            "processing_error": str(e)
        }).eq("id", email_id).execute()
        raise EventsError(f"Failed to process email for events: {e}") from e


def find_matching_event(
    supabase_client: Client,
    gemini_client: Any,
    user_id: str,
    event_data: dict[str, Any],
    logging_service: Optional[LLMLoggingService] = None,
) -> Optional[str]:
    """Find if event matches any existing events (date-based + LLM).

    Args:
        supabase_client: Authenticated Supabase client.
        gemini_client: Initialized Gemini client.
        user_id: UUID of user.
        event_data: Extracted event data.
        logging_service: Optional LLM logging service for call auditing.

    Returns:
        Event ID if match found, None otherwise.
    """
    start_dt = event_data.get("start_datetime")
    if not start_dt:
        return None
    
    # Parse date
    try:
        if isinstance(start_dt, str):
            start_date = datetime.fromisoformat(start_dt.replace('Z', '+00:00')).date()
        else:
            start_date = start_dt.date()
    except (ValueError, AttributeError) as e:
        logger.debug(f"Date parse failed: {e}")
        return None
    
    # Query events on same date
    result = supabase_client.table("events").select("*").eq(
        "user_id", user_id
    ).gte(
        "start_datetime", f"{start_date}T00:00:00Z"
    ).lte(
        "start_datetime", f"{start_date}T23:59:59Z"
    ).execute()
    
    candidates = result.data
    if not candidates:
        return None
    
    # Use LLM to compare
    try:
        matched_id = gemini.compare_events(
            gemini_client,
            event_data,
            candidates,
            logging_service=logging_service,
            user_id=user_id,
        )
        return matched_id
    except Exception as e:
        logger.warning(f"LLM comparison failed, no match: {e}")
        return None


def create_event(
    supabase_client: Client,
    user_id: str,
    event_data: dict[str, Any],
    email_id: str,
) -> str:
    """Create new event and link to email source.
    
    Args:
        supabase_client: Authenticated Supabase client.
        user_id: UUID of user.
        event_data: Event data to create.
        email_id: UUID of source email.
        
    Returns:
        UUID of created event.
    """
    # Create event record
    event_result = supabase_client.table("events").insert({
        "user_id": user_id,
        "title": event_data.get("title"),
        "start_datetime": event_data.get("start_datetime"),
        "end_datetime": event_data.get("end_datetime"),
        "all_day": event_data.get("all_day", False),
        "location": event_data.get("location"),
        "description": event_data.get("description"),
        "status": "pending_review",
    }).execute()
    
    event_id = event_result.data[0]["id"]
    
    # Create event_source link
    supabase_client.table("event_sources").insert({
        "event_id": event_id,
        "email_id": email_id,
        "source_type": "new_invitation",
        "extracted_data": event_data,
        "event_snapshot_before": None,  # No snapshot for new events
    }).execute()
    
    # Generate source attribution
    attribution = generate_source_attribution(supabase_client, event_id)
    if attribution:
        supabase_client.table("events").update({
            "source_attribution": attribution
        }).eq("id", event_id).execute()
    
    logger.info(f"Created new event {event_id}")
    return event_id


def update_event(
    supabase_client: Client,
    gemini_client: Any,
    event_id: str,
    new_data: dict[str, Any],
    email_id: str,
    source_type: str,
    logging_service: Optional[LLMLoggingService] = None,
    user_id: Optional[str] = None,
) -> None:
    """Auto-merge new data into existing event.

    Args:
        supabase_client: Authenticated Supabase client.
        gemini_client: Initialized Gemini client.
        event_id: UUID of event to update.
        new_data: New event data from email.
        email_id: UUID of source email.
        source_type: Type of source (update, cancellation, etc).
        logging_service: Optional LLM logging service for call auditing.
        user_id: User UUID for logging.
    """
    # Fetch current event
    result = supabase_client.table("events").select("*").eq("id", event_id).single().execute()
    existing_event = result.data
    
    # Store snapshot before merge
    snapshot = {
        "title": existing_event.get("title"),
        "start_datetime": existing_event.get("start_datetime"),
        "end_datetime": existing_event.get("end_datetime"),
        "all_day": existing_event.get("all_day"),
        "location": existing_event.get("location"),
        "description": existing_event.get("description"),
    }
    
    # Use LLM to merge
    merged_data = gemini.merge_event_data(
        gemini_client,
        existing_event,
        new_data,
        source_type,
        logging_service=logging_service,
        user_id=user_id,
    )
    
    # Update event
    supabase_client.table("events").update({
        "title": merged_data.get("title"),
        "start_datetime": merged_data.get("start_datetime"),
        "end_datetime": merged_data.get("end_datetime"),
        "all_day": merged_data.get("all_day", False),
        "location": merged_data.get("location"),
        "description": merged_data.get("description"),
        "updated_at": datetime.now().isoformat(),
    }).eq("id", event_id).execute()
    
    # Create event_source link
    supabase_client.table("event_sources").insert({
        "event_id": event_id,
        "email_id": email_id,
        "source_type": source_type,
        "extracted_data": new_data,
        "event_snapshot_before": snapshot,
    }).execute()
    
    # Update source attribution
    attribution = generate_source_attribution(supabase_client, event_id)
    if attribution:
        supabase_client.table("events").update({
            "source_attribution": attribution
        }).eq("id", event_id).execute()
    
    logger.info(f"Updated event {event_id} from email {email_id}")


def get_events_new(supabase_client: Client, user_id: str) -> list[dict[str, Any]]:
    """Get pending approval events grouped by sender."""
    result = supabase_client.table("events").select(
        "*, event_sources(*, emails(*))"
    ).eq("user_id", user_id).eq("status", "pending_review").order(
        "start_datetime"
    ).execute()
    
    return result.data


def get_events_approved(supabase_client: Client, user_id: str) -> list[dict[str, Any]]:
    """Get approved/synced events."""
    result = supabase_client.table("events").select("*").eq(
        "user_id", user_id
    ).in_("status", ["approved", "synced"]).order("start_datetime").execute()
    
    return result.data


def get_events_updates(supabase_client: Client, user_id: str) -> list[dict[str, Any]]:
    """Get change log (updates, cancellations, rejections)."""
    result = supabase_client.table("event_sources").select(
        "*, events(*), emails(*)"
    ).in_(
        "source_type", ["update", "cancellation"]
    ).order("created_at", desc=True).execute()
    
    # Filter by user_id
    updates = [
        source for source in result.data
        if source.get("events", {}).get("user_id") == user_id
    ]
    
    return updates


def get_event_with_sources(
    supabase_client: Client, event_id: str
) -> dict[str, Any]:
    """Fetch event with all source emails."""
    result = supabase_client.table("events").select(
        "*, event_sources(*, emails(*))"
    ).eq("id", event_id).single().execute()
    
    return result.data


def approve_event(supabase_client: Client, event_id: str) -> None:
    """Approve event for calendar sync."""
    supabase_client.table("events").update({
        "status": "approved"
    }).eq("id", event_id).execute()
    
    logger.info(f"Approved event {event_id}")


def reject_event(supabase_client: Client, event_id: str) -> None:
    """Reject event."""
    supabase_client.table("events").update({
        "status": "rejected"
    }).eq("id", event_id).execute()
    
    logger.info(f"Rejected event {event_id}")


def restore_rejected_event(supabase_client: Client, event_id: str) -> None:
    """Restore rejected event to New."""
    supabase_client.table("events").update({
        "status": "pending_review"
    }).eq("id", event_id).execute()
    
    logger.info(f"Restored event {event_id}")


def undo_email_contribution(
    supabase_client: Client, event_source_id: str
) -> None:
    """Rollback specific email's changes using snapshot.
    
    Args:
        supabase_client: Authenticated Supabase client.
        event_source_id: UUID of event_source to undo.
    """
    # Fetch event_source
    result = supabase_client.table("event_sources").select("*").eq(
        "id", event_source_id
    ).single().execute()
    
    source = result.data
    event_id = source.get("event_id")
    snapshot = source.get("event_snapshot_before")
    
    if not snapshot:
        raise EventsError("No snapshot available for undo")
    
    # Restore snapshot
    supabase_client.table("events").update(snapshot).eq("id", event_id).execute()
    
    # Mark source as undone
    supabase_client.table("event_sources").update({
        "is_undone": True
    }).eq("id", event_source_id).execute()
    
    # Regenerate source attribution (excluding undone sources)
    attribution = generate_source_attribution(supabase_client, event_id)
    if attribution:
        supabase_client.table("events").update({
            "source_attribution": attribution
        }).eq("id", event_id).execute()
    
    logger.info(f"Undid event_source {event_source_id}")


def redo_email_contribution(
    supabase_client: Client, event_source_id: str
) -> None:
    """Re-apply undone contribution."""
    supabase_client.table("event_sources").update({
        "is_undone": False
    }).eq("id", event_source_id).execute()
    
    # Regenerate source attribution
    result = supabase_client.table("event_sources").select("event_id").eq(
        "id", event_source_id
    ).single().execute()
    event_id = result.data["event_id"]
    
    attribution = generate_source_attribution(supabase_client, event_id)
    if attribution:
        supabase_client.table("events").update({
            "source_attribution": attribution
        }).eq("id", event_id).execute()
    
    logger.info(f"Redid event_source {event_source_id}")


def check_sender_rules(
    supabase_client: Client, user_id: str, sender_email: str
) -> Optional[dict[str, Any]]:
    """Check if auto-approve/ignore applies to sender.
    
    Args:
        supabase_client: Authenticated Supabase client.
        user_id: UUID of user.
        sender_email: Email address of sender.
        
    Returns:
        Sender rule dict if found, None otherwise.
    """
    # Check exact email match first
    result = supabase_client.table("sender_rules").select("*").eq(
        "user_id", user_id
    ).eq("sender_email", sender_email).execute()
    
    if result.data:
        return result.data[0]
    
    # Check domain match
    domain = sender_email.split("@")[-1] if "@" in sender_email else ""
    if domain:
        result = supabase_client.table("sender_rules").select("*").eq(
            "user_id", user_id
        ).eq("sender_domain", domain).execute()
        
        if result.data:
            return result.data[0]
    
    return None


def generate_source_attribution(
    supabase_client: Client, event_id: str
) -> str:
    """Generate natural English attribution for event.
    
    Args:
        supabase_client: Authenticated Supabase client.
        event_id: UUID of event.
        
    Returns:
        Natural English attribution string.
    """
    # Fetch all non-undone sources
    result = supabase_client.table("event_sources").select(
        "*, emails(*)"
    ).eq("event_id", event_id).eq("is_undone", False).order("created_at").execute()
    
    sources = result.data
    if not sources:
        return ""
    
    # Build attribution using helper function
    sources_with_email_data = []
    for source in sources:
        email = source.get("emails", {})
        sources_with_email_data.append({
            "source_type": source.get("source_type"),
            "email_sender": email.get("from_email"),
            "email_sender_name": email.get("from_name"),
            "email_date": email.get("date_sent"),
            "created_at": source.get("created_at"),
            "is_undone": source.get("is_undone", False),
        })
    
    return gemini.generate_source_attribution(sources_with_email_data)


# --- Status-based worker claiming functions for calendar sync ---


def claim_approved_event_for_sync(
    client: Client,
    worker_id: str,
    lock_duration_seconds: int = 300,
) -> Optional[dict[str, Any]]:
    """Atomically claim the next approved event for calendar sync.

    Uses PostgreSQL FOR UPDATE SKIP LOCKED to safely claim events without
    conflicts between multiple workers.

    Args:
        client: Authenticated Supabase client (should use service role).
        worker_id: Unique identifier for this worker process.
        lock_duration_seconds: How long to hold the lock (default: 5 minutes).

    Returns:
        Event dict if claimed, None if no approved events available.

    Raises:
        EventsError: If claim operation fails.
    """
    try:
        result = client.rpc('claim_approved_event', {
            'p_worker_id': worker_id,
            'p_lock_duration_seconds': lock_duration_seconds,
        }).execute()

        if result.data and len(result.data) > 0:
            event = result.data[0]
            title = event.get("title", "(no title)")[:50]
            logger.info(
                f"Worker {worker_id} claimed event {event['id']}: {title} "
                f"(attempt {event['sync_attempts']}/{event['max_sync_attempts']})"
            )
            return event

        return None

    except Exception as e:
        raise EventsError(f"Failed to claim approved event: {e}") from e


def complete_event_sync(client: Client, event_id: str, google_event_id: str) -> None:
    """Mark event as synced successfully and clear the lock.

    Args:
        client: Authenticated Supabase client (should use service role).
        event_id: UUID of event to mark as synced.
        google_event_id: ID of the created Google Calendar event.

    Raises:
        EventsError: If update fails.
    """
    try:
        client.table("events").update({
            "status": "synced",
            "google_calendar_event_id": google_event_id,
            "synced_at": datetime.now().isoformat(),
            "sync_error": None,
            "locked_by": None,
            "locked_until": None,
        }).eq("id", event_id).execute()

        logger.info(f"Completed sync for event {event_id} -> {google_event_id}")

    except Exception as e:
        raise EventsError(f"Failed to complete event sync: {e}") from e


def fail_event_sync(
    client: Client,
    event_id: str,
    error: str,
) -> None:
    """Mark event sync as failed.

    If sync_attempts < max_sync_attempts, sets status back to 'approved' for retry.
    Otherwise, sets status to 'sync_failed' permanently.

    Args:
        client: Authenticated Supabase client (should use service role).
        event_id: UUID of event that failed syncing.
        error: Error message to store.

    Raises:
        EventsError: If update fails.
    """
    try:
        # Fetch current event to check retry eligibility
        result = client.table("events").select(
            "sync_attempts, max_sync_attempts"
        ).eq("id", event_id).single().execute()

        event = result.data
        should_retry = event["sync_attempts"] < event["max_sync_attempts"]

        update_data = {
            "status": "approved" if should_retry else "sync_failed",
            "sync_error": error,
            "locked_by": None,
            "locked_until": None,
        }

        client.table("events").update(update_data).eq("id", event_id).execute()

        if should_retry:
            logger.warning(
                f"Event {event_id} sync failed "
                f"(attempt {event['sync_attempts']}/{event['max_sync_attempts']}): {error}. "
                f"Will retry."
            )
        else:
            logger.error(
                f"Event {event_id} sync failed permanently "
                f"after {event['sync_attempts']} attempts: {error}"
            )

    except Exception as e:
        raise EventsError(f"Failed to mark event sync as failed: {e}") from e


def unlock_expired_event_locks(client: Client) -> int:
    """Reset expired event sync locks back to approved.

    Handles the case where a worker crashes mid-sync and the lock expires.

    Args:
        client: Authenticated Supabase client (should use service role).

    Returns:
        Number of events unlocked.

    Raises:
        EventsError: If unlock fails.
    """
    try:
        result = client.rpc('unlock_expired_event_locks').execute()
        count = result.data if result.data else 0

        if count > 0:
            logger.warning(f"Unlocked {count} expired event sync locks")

        return count

    except Exception as e:
        raise EventsError(f"Failed to unlock expired event locks: {e}") from e
