"""Calendars service for Google Calendar integration."""

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
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
        except Exception as e:
            logger.warning(f"Failed to get calendar name: {e}")

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


def _build_calendar_event_body(
    event: dict[str, Any],
    settings: dict[str, Any],
) -> dict[str, Any]:
    """Build Google Calendar event body from Selko event.

    Args:
        event: Selko event dict from database.
        settings: Calendar settings with default_invitees.

    Returns:
        Dict suitable for Google Calendar API.
    """
    # Prepare description with attribution
    description = event.get("description", "") or ""
    attribution = event.get("source_attribution", "") or ""
    if attribution:
        description = f"{description}\n\n{attribution}" if description else attribution

    calendar_event = {
        "summary": event.get("title"),
        "location": event.get("location"),
        "description": description,
        "start": {},
        "end": {},
        # Add extended properties for traceability
        "extendedProperties": {
            "private": {
                "selko_event_id": event.get("id"),
            }
        },
    }

    # Handle dates
    if event.get("all_day"):
        # All-day event
        start_dt = event.get("start_datetime")
        if start_dt:
            # Handle both datetime strings and datetime objects
            if isinstance(start_dt, str):
                date_str = start_dt.split("T")[0]
            else:
                date_str = start_dt.strftime("%Y-%m-%d")
            calendar_event["start"]["date"] = date_str
            calendar_event["end"]["date"] = date_str
    else:
        # Timed event
        start_dt = event.get("start_datetime")
        end_dt = event.get("end_datetime")

        if start_dt:
            if isinstance(start_dt, str):
                calendar_event["start"]["dateTime"] = start_dt
            else:
                calendar_event["start"]["dateTime"] = start_dt.isoformat()
            calendar_event["start"]["timeZone"] = "UTC"

        if end_dt:
            if isinstance(end_dt, str):
                calendar_event["end"]["dateTime"] = end_dt
            else:
                calendar_event["end"]["dateTime"] = end_dt.isoformat()
            calendar_event["end"]["timeZone"] = "UTC"
        elif start_dt:
            # Default to same as start (1 hour duration handled by Calendar API)
            if isinstance(start_dt, str):
                calendar_event["end"]["dateTime"] = start_dt
            else:
                calendar_event["end"]["dateTime"] = start_dt.isoformat()
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

    return calendar_event


def _log_sync(
    supabase_client: Client,
    user_id: str,
    event_id: str,
    google_calendar_event_id: str,
    action: str,
    snapshot: dict[str, Any],
) -> None:
    """Log a calendar sync operation.

    Args:
        supabase_client: Authenticated Supabase client.
        user_id: UUID of user.
        event_id: UUID of Selko event.
        google_calendar_event_id: Google Calendar event ID.
        action: One of 'created', 'updated', 'deleted'.
        snapshot: What we sent to Google Calendar.
    """
    try:
        supabase_client.table("calendar_sync_log").insert({
            "event_id": event_id,
            "user_id": user_id,
            "google_calendar_event_id": google_calendar_event_id,
            "action": action,
            "snapshot_synced": snapshot,
        }).execute()
        logger.debug(f"Logged sync: {action} for event {event_id}")
    except Exception as e:
        # Don't fail the sync if logging fails
        logger.warning(f"Failed to log sync operation: {e}")


def sync_event_to_calendar(
    supabase_client: Client, user_id: str, event_id: str
) -> str:
    """Write event to Google Calendar with invitees (idempotent).

    If the event has already been synced (has google_calendar_event_id):
    - Tries to update the existing calendar event
    - If the calendar event was deleted (404), creates a new one

    If the event hasn't been synced yet:
    - Creates a new calendar event

    All operations are logged to calendar_sync_log for audit trail.

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
        calendar_id = settings.get("target_calendar_id") or "primary"

        # Build Calendar API client
        service = build("calendar", "v3", credentials=creds)

        # Build the event body
        calendar_event = _build_calendar_event_body(event, settings)

        existing_google_id = event.get("google_calendar_event_id")

        if existing_google_id:
            # Event was previously synced - try to update or recreate
            google_event_id, action = _update_or_recreate_calendar_event(
                service, calendar_id, existing_google_id, calendar_event
            )
        else:
            # First time sync - create new event
            created_event = service.events().insert(
                calendarId=calendar_id,
                body=calendar_event
            ).execute()
            google_event_id = created_event["id"]
            action = "created"

        # Update event record in database
        supabase_client.table("events").update({
            "google_calendar_event_id": google_event_id,
            "status": "synced",
            "synced_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", event_id).execute()

        # Log the sync operation
        _log_sync(
            supabase_client,
            user_id,
            event_id,
            google_event_id,
            action,
            calendar_event,
        )

        logger.info(f"Synced event {event_id} to calendar {calendar_id} ({action})")
        return google_event_id

    except Exception as e:
        # Mark as sync_failed
        try:
            supabase_client.table("events").update({
                "status": "sync_failed"
            }).eq("id", event_id).execute()
        except Exception as update_error:
            logger.warning(f"Failed to update event status to sync_failed: {update_error}")
        raise CalendarsError(f"Failed to sync event to calendar: {e}") from e


def _update_or_recreate_calendar_event(
    service,
    calendar_id: str,
    existing_google_id: str,
    calendar_event: dict[str, Any],
) -> tuple[str, str]:
    """Update existing calendar event or recreate if deleted.

    Args:
        service: Google Calendar API service.
        calendar_id: Target calendar ID.
        existing_google_id: Existing Google Calendar event ID.
        calendar_event: New event body to sync.

    Returns:
        Tuple of (google_event_id, action) where action is 'updated' or 'created'.
    """
    try:
        # Try to get the existing event
        existing_event = service.events().get(
            calendarId=calendar_id,
            eventId=existing_google_id
        ).execute()

        # Event exists - update it
        # Merge our data into the existing event to preserve user edits
        existing_event["summary"] = calendar_event.get("summary")
        existing_event["location"] = calendar_event.get("location")
        existing_event["description"] = calendar_event.get("description")
        existing_event["start"] = calendar_event.get("start")
        existing_event["end"] = calendar_event.get("end")

        # Preserve or update extended properties
        if "extendedProperties" not in existing_event:
            existing_event["extendedProperties"] = {"private": {}}
        if "private" not in existing_event["extendedProperties"]:
            existing_event["extendedProperties"]["private"] = {}
        existing_event["extendedProperties"]["private"]["selko_event_id"] = (
            calendar_event.get("extendedProperties", {}).get("private", {}).get("selko_event_id")
        )

        # Update attendees if we have default invitees
        if "attendees" in calendar_event:
            existing_event["attendees"] = calendar_event["attendees"]

        service.events().update(
            calendarId=calendar_id,
            eventId=existing_google_id,
            body=existing_event
        ).execute()

        return existing_google_id, "updated"

    except HttpError as e:
        if e.resp.status == 404:
            # Event was deleted from calendar - recreate it
            logger.info(f"Calendar event {existing_google_id} was deleted, recreating...")
            created_event = service.events().insert(
                calendarId=calendar_id,
                body=calendar_event
            ).execute()
            return created_event["id"], "created"
        else:
            # Other error - re-raise
            raise


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
        calendar_id = settings.get("target_calendar_id") or "primary"

        # Build Calendar API client
        service = build("calendar", "v3", credentials=creds)

        # Fetch existing event
        existing_event = service.events().get(
            calendarId=calendar_id,
            eventId=google_event_id
        ).execute()

        # Update fields
        description = event.get("description", "") or ""
        attribution = event.get("source_attribution", "") or ""
        if attribution:
            description = f"{description}\n\n{attribution}" if description else attribution

        existing_event["summary"] = event.get("title")
        existing_event["location"] = event.get("location")
        existing_event["description"] = description

        # Update dates
        start_dt = event.get("start_datetime")
        end_dt = event.get("end_datetime")

        if event.get("all_day"):
            if start_dt:
                if isinstance(start_dt, str):
                    date_str = start_dt.split("T")[0]
                else:
                    date_str = start_dt.strftime("%Y-%m-%d")
                existing_event["start"] = {"date": date_str}
                existing_event["end"] = {"date": date_str}
        else:
            if start_dt:
                if isinstance(start_dt, str):
                    existing_event["start"] = {
                        "dateTime": start_dt,
                        "timeZone": "UTC"
                    }
                else:
                    existing_event["start"] = {
                        "dateTime": start_dt.isoformat(),
                        "timeZone": "UTC"
                    }
            if end_dt:
                if isinstance(end_dt, str):
                    existing_event["end"] = {
                        "dateTime": end_dt,
                        "timeZone": "UTC"
                    }
                else:
                    existing_event["end"] = {
                        "dateTime": end_dt.isoformat(),
                        "timeZone": "UTC"
                    }

        # Update event
        service.events().update(
            calendarId=calendar_id,
            eventId=google_event_id,
            body=existing_event
        ).execute()

        # Log the update
        calendar_event = _build_calendar_event_body(event, settings)
        _log_sync(
            supabase_client,
            user_id,
            event_id,
            google_event_id,
            "updated",
            calendar_event,
        )

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
            calendar_id = settings.get("target_calendar_id") or "primary"

            service = build("calendar", "v3", credentials=creds)

            try:
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
            except HttpError as e:
                if e.resp.status == 404:
                    logger.warning(f"Calendar event {google_event_id} already deleted")
                else:
                    raise

        logger.info(f"Cancelled event {event_id}")

    except Exception as e:
        raise CalendarsError(f"Failed to cancel event: {e}") from e
