"""Calendars service for Google Calendar integration."""

import logging
from typing import Any, Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from supabase import Client

from selko.services.integrations import get_credentials

logger = logging.getLogger(__name__)


class CalendarsError(Exception):
    """Raised when calendar operations fail."""

    pass


def list_calendars(
    supabase_client: Client, user_id: str
) -> list[dict[str, Any]]:
    """List all Google Calendars for user.
    
    Args:
        supabase_client: Authenticated Supabase client.
        user_id: UUID of user.
        
    Returns:
        List of calendar dicts with id, name, is_primary, is_selected.
        
    Raises:
        CalendarsError: If listing fails.
    """
    try:
        # Get user's Google credentials
        creds = get_credentials(supabase_client, user_id, "google_calendar")
        if not creds:
            raise CalendarsError("No Google Calendar credentials found")
        
        # Build Calendar API client
        service = build("calendar", "v3", credentials=creds)
        
        # List calendars
        calendar_list = service.calendarList().list().execute()
        
        # Get user's target calendar setting
        settings = get_calendar_settings(supabase_client, user_id)
        target_calendar_id = settings.get("target_calendar_id")
        
        calendars = []
        for cal in calendar_list.get("items", []):
            calendars.append({
                "id": cal["id"],
                "name": cal["summary"],
                "is_primary": cal.get("primary", False),
                "is_selected": cal["id"] == target_calendar_id if target_calendar_id else cal.get("primary", False),
            })
        
        return calendars
        
    except Exception as e:
        raise CalendarsError(f"Failed to list calendars: {e}") from e


def get_calendar_settings(
    supabase_client: Client, user_id: str
) -> dict[str, Any]:
    """Get target calendar and default invitees.
    
    Args:
        supabase_client: Authenticated Supabase client.
        user_id: UUID of user.
        
    Returns:
        Dict with target_calendar_id, target_calendar_name, default_invitees.
    """
    result = supabase_client.table("user_calendar_settings").select("*").eq(
        "user_id", user_id
    ).execute()
    
    if not result.data:
        return {
            "target_calendar_id": None,
            "target_calendar_name": None,
            "default_invitees": None,
        }
    
    settings = result.data[0]
    
    # Get calendar name if target is set
    calendar_name = None
    if settings.get("target_calendar_id"):
        try:
            calendars = list_calendars(supabase_client, user_id)
            for cal in calendars:
                if cal["id"] == settings["target_calendar_id"]:
                    calendar_name = cal["name"]
                    break
        except:
            pass
    
    return {
        "target_calendar_id": settings.get("target_calendar_id"),
        "target_calendar_name": calendar_name,
        "default_invitees": settings.get("default_invitees"),
    }


def update_calendar_settings(
    supabase_client: Client,
    user_id: str,
    target_calendar_id: Optional[str] = None,
    default_invitees: Optional[str] = None,
) -> None:
    """Update calendar settings.
    
    Args:
        supabase_client: Authenticated Supabase client.
        user_id: UUID of user.
        target_calendar_id: Google Calendar ID to sync to (None = primary).
        default_invitees: Comma-separated emails to add to all events.
    """
    # Upsert settings
    supabase_client.table("user_calendar_settings").upsert({
        "user_id": user_id,
        "target_calendar_id": target_calendar_id,
        "default_invitees": default_invitees,
    }).execute()
    
    logger.info(f"Updated calendar settings for user {user_id}")


def sync_event_to_calendar(
    supabase_client: Client, user_id: str, event_id: str
) -> str:
    """Write event to Google Calendar with invitees.
    
    Args:
        supabase_client: Authenticated Supabase client.
        user_id: UUID of user.
        event_id: UUID of event to sync.
        
    Returns:
        Google Calendar event ID.
        
    Raises:
        CalendarsError: If sync fails.
    """
    try:
        # Fetch event
        event_result = supabase_client.table("events").select("*").eq(
            "id", event_id
        ).single().execute()
        event = event_result.data
        
        # Get credentials and settings
        creds = get_credentials(supabase_client, user_id, "google_calendar")
        if not creds:
            raise CalendarsError("No Google Calendar credentials found")
        
        settings = get_calendar_settings(supabase_client, user_id)
        calendar_id = settings.get("target_calendar_id", "primary")
        
        # Build Calendar API client
        service = build("calendar", "v3", credentials=creds)
        
        # Prepare event data
        description = event.get("description", "")
        attribution = event.get("source_attribution", "")
        if attribution:
            description = f"{description}\n\n{attribution}" if description else attribution
        
        calendar_event = {
            "summary": event.get("title"),
            "location": event.get("location"),
            "description": description,
            "start": {},
            "end": {},
        }
        
        # Handle dates
        if event.get("all_day"):
            # All-day event
            start_dt = event.get("start_datetime")
            if start_dt:
                calendar_event["start"]["date"] = start_dt.split("T")[0]
                calendar_event["end"]["date"] = start_dt.split("T")[0]
        else:
            # Timed event
            if event.get("start_datetime"):
                calendar_event["start"]["dateTime"] = event["start_datetime"]
                calendar_event["start"]["timeZone"] = "UTC"
            if event.get("end_datetime"):
                calendar_event["end"]["dateTime"] = event["end_datetime"]
                calendar_event["end"]["timeZone"] = "UTC"
            elif event.get("start_datetime"):
                # Default to 1 hour duration
                calendar_event["end"]["dateTime"] = event["start_datetime"]
                calendar_event["end"]["timeZone"] = "UTC"
        
        # Add default invitees
        invitees = settings.get("default_invitees")
        if invitees:
            attendees = []
            for email in invitees.split(","):
                email = email.strip()
                if email:
                    attendees.append({"email": email})
            if attendees:
                calendar_event["attendees"] = attendees
        
        # Create event
        created_event = service.events().insert(
            calendarId=calendar_id,
            body=calendar_event
        ).execute()
        
        google_event_id = created_event["id"]
        
        # Update event record
        supabase_client.table("events").update({
            "google_calendar_event_id": google_event_id,
            "status": "synced",
            "synced_at": created_event.get("created"),
        }).eq("id", event_id).execute()
        
        logger.info(f"Synced event {event_id} to calendar {calendar_id}")
        return google_event_id
        
    except Exception as e:
        # Mark as sync_failed
        supabase_client.table("events").update({
            "status": "sync_failed"
        }).eq("id", event_id).execute()
        raise CalendarsError(f"Failed to sync event to calendar: {e}") from e


def update_calendar_event(
    supabase_client: Client, user_id: str, event_id: str
) -> None:
    """Update existing calendar event.
    
    Args:
        supabase_client: Authenticated Supabase client.
        user_id: UUID of user.
        event_id: UUID of event to update.
        
    Raises:
        CalendarsError: If update fails.
    """
    try:
        # Fetch event
        event_result = supabase_client.table("events").select("*").eq(
            "id", event_id
        ).single().execute()
        event = event_result.data
        
        google_event_id = event.get("google_calendar_event_id")
        if not google_event_id:
            raise CalendarsError("Event not synced to calendar yet")
        
        # Get credentials and settings
        creds = get_credentials(supabase_client, user_id, "google_calendar")
        if not creds:
            raise CalendarsError("No Google Calendar credentials found")
        
        settings = get_calendar_settings(supabase_client, user_id)
        calendar_id = settings.get("target_calendar_id", "primary")
        
        # Build Calendar API client
        service = build("calendar", "v3", credentials=creds)
        
        # Fetch existing event
        existing_event = service.events().get(
            calendarId=calendar_id,
            eventId=google_event_id
        ).execute()
        
        # Update fields
        description = event.get("description", "")
        attribution = event.get("source_attribution", "")
        if attribution:
            description = f"{description}\n\n{attribution}" if description else attribution
        
        existing_event["summary"] = event.get("title")
        existing_event["location"] = event.get("location")
        existing_event["description"] = description
        
        # Update dates
        if event.get("all_day"):
            start_dt = event.get("start_datetime")
            if start_dt:
                existing_event["start"] = {"date": start_dt.split("T")[0]}
                existing_event["end"] = {"date": start_dt.split("T")[0]}
        else:
            if event.get("start_datetime"):
                existing_event["start"] = {
                    "dateTime": event["start_datetime"],
                    "timeZone": "UTC"
                }
            if event.get("end_datetime"):
                existing_event["end"] = {
                    "dateTime": event["end_datetime"],
                    "timeZone": "UTC"
                }
        
        # Update event
        service.events().update(
            calendarId=calendar_id,
            eventId=google_event_id,
            body=existing_event
        ).execute()
        
        logger.info(f"Updated calendar event for {event_id}")
        
    except Exception as e:
        raise CalendarsError(f"Failed to update calendar event: {e}") from e


def cancel_calendar_event(
    supabase_client: Client, user_id: str, event_id: str
) -> None:
    """Prefix title with 'CANCELLED: ' in calendar.
    
    Args:
        supabase_client: Authenticated Supabase client.
        user_id: UUID of user.
        event_id: UUID of event to cancel.
        
    Raises:
        CalendarsError: If cancellation fails.
    """
    try:
        # Fetch event
        event_result = supabase_client.table("events").select("*").eq(
            "id", event_id
        ).single().execute()
        event = event_result.data
        
        # Update title with CANCELLED prefix
        title = event.get("title", "")
        if not title.startswith("CANCELLED: "):
            title = f"CANCELLED: {title}"
            
            # Update local DB
            supabase_client.table("events").update({
                "title": title,
                "status": "cancelled",
            }).eq("id", event_id).execute()
        
        # Update calendar if synced
        google_event_id = event.get("google_calendar_event_id")
        if google_event_id:
            creds = get_credentials(supabase_client, user_id, "google_calendar")
            if not creds:
                logger.warning("No credentials to update calendar event")
                return
            
            settings = get_calendar_settings(supabase_client, user_id)
            calendar_id = settings.get("target_calendar_id", "primary")
            
            service = build("calendar", "v3", credentials=creds)
            
            existing_event = service.events().get(
                calendarId=calendar_id,
                eventId=google_event_id
            ).execute()
            
            existing_event["summary"] = title
            
            service.events().update(
                calendarId=calendar_id,
                eventId=google_event_id,
                body=existing_event
            ).execute()
        
        logger.info(f"Cancelled event {event_id}")
        
    except Exception as e:
        raise CalendarsError(f"Failed to cancel event: {e}") from e
