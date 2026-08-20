"""Calendars service for Google Calendar integration."""

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from supabase import Client

from selko.services.google_errors import (
    INSUFFICIENT_SCOPE_REASONS,
    RATE_LIMIT_REASONS,
    google_error_reason,
)
from selko.services.integrations import get_credentials, update_integration_status

logger = logging.getLogger(__name__)

SELKO_FOOTER = "\n\n---\nThis event is managed by Selko."


@dataclass(frozen=True)
class CalendarFailureClassification:
    """Typed outcome of classifying a calendar sync failure.

    Attributes:
        code: One of the ``events.sync_failure_code`` vocabulary values.
        retryable: Whether the normal sync-attempt retry/backoff applies.
        counts_toward_circuit_breaker: Whether this failure reflects provider
            health (and should trip the shared ``google_calendar`` circuit)
            versus a single user's auth state, which must not.
        user_message: Safe to show to the affected user.
        operator_detail: Full detail for logs/dead-letter, never shown to users.
    """

    code: str
    retryable: bool
    counts_toward_circuit_breaker: bool
    user_message: str
    operator_detail: str


class CalendarsError(Exception):
    """Raised when calendar operations fail."""

    def __init__(
        self,
        message: str,
        classification: Optional[CalendarFailureClassification] = None,
    ) -> None:
        super().__init__(message)
        self.classification = classification


class CalendarAuthRequiredError(CalendarsError):
    """Raised when a calendar operation cannot proceed without reauthorization.

    Distinct from a generic ``CalendarsError`` so failure classification can
    branch on exception type instead of matching the message text.
    """

    pass


def classify_calendar_error(exc: Exception) -> CalendarFailureClassification:
    """Classify a calendar sync exception into a typed, actionable outcome.

    This is the single place that interprets provider error shapes. Callers
    (worker orchestration, retry/dead-letter logic) must branch on the
    returned ``code``/flags, never on ``str(exc)``.
    """
    if isinstance(exc, CalendarAuthRequiredError):
        return CalendarFailureClassification(
            code="oauth_required",
            retryable=False,
            counts_toward_circuit_breaker=False,
            user_message="Google Calendar needs to be reconnected.",
            operator_detail=str(exc),
        )

    if isinstance(exc, HttpError):
        status = getattr(exc.resp, "status", None)
        reason = google_error_reason(exc)

        if status == 401:
            return CalendarFailureClassification(
                code="oauth_required",
                retryable=False,
                counts_toward_circuit_breaker=False,
                user_message="Google Calendar needs to be reconnected.",
                operator_detail=str(exc),
            )
        if status == 403 and reason in INSUFFICIENT_SCOPE_REASONS:
            return CalendarFailureClassification(
                code="oauth_scope_required",
                retryable=False,
                counts_toward_circuit_breaker=False,
                user_message="Google Calendar needs additional permission.",
                operator_detail=str(exc),
            )
        if status == 403 and reason in RATE_LIMIT_REASONS:
            return CalendarFailureClassification(
                code="rate_limited",
                retryable=True,
                counts_toward_circuit_breaker=True,
                user_message="Google Calendar is temporarily busy; retrying.",
                operator_detail=str(exc),
            )
        if status == 429:
            return CalendarFailureClassification(
                code="rate_limited",
                retryable=True,
                counts_toward_circuit_breaker=True,
                user_message="Google Calendar is temporarily busy; retrying.",
                operator_detail=str(exc),
            )
        if status == 403:
            return CalendarFailureClassification(
                code="permission_denied",
                retryable=True,
                counts_toward_circuit_breaker=False,
                user_message="Selko doesn't have permission to write to this calendar.",
                operator_detail=str(exc),
            )
        if status in (500, 502, 503, 504):
            return CalendarFailureClassification(
                code="provider_transient",
                retryable=True,
                counts_toward_circuit_breaker=True,
                user_message="Google Calendar is temporarily unavailable; retrying.",
                operator_detail=str(exc),
            )
        if status == 400:
            return CalendarFailureClassification(
                code="invalid_event",
                retryable=True,
                counts_toward_circuit_breaker=False,
                user_message="This event couldn't be synced to Google Calendar.",
                operator_detail=str(exc),
            )

    return CalendarFailureClassification(
        code="unknown",
        retryable=True,
        counts_toward_circuit_breaker=True,
        user_message="This event couldn't be synced to Google Calendar.",
        operator_detail=str(exc),
    )


async def requeue_calendar_recovery_batch(
    pool,
    recovery_id: str,
    worker_id: str,
    batch_size: int = 100,
) -> int:
    """Tag one claimed recovery generation's OAuth-blocked events.

    Pure bookkeeping (docs/specs/oauth-reconnect-catch-up.md section 3): the
    tagged events are already ``approved`` with ``sync_attempts`` preserved,
    so they become eligible for the normal calendar sync worker the moment
    ``claim_approved_event`` sees the integration active again. Tagging only
    exists to give the UI a recovery-scoped progress count.

    Args:
        pool: asyncpg session-pooler pool.
        recovery_id: The recovery generation, previously claimed via
            `claim_integration_recovery`.
        worker_id: Must match the worker that holds the claim.
        batch_size: Events tagged per internal pass (bounded server-side).

    Returns:
        Number of events tagged in this call, or -1 if the claim was lost
        (expired or reclaimed by another worker) before this ran.

    Raises:
        CalendarsError: If the RPC call fails.
    """
    try:
        return await pool.fetchval(
            "SELECT public.requeue_calendar_recovery_batch($1, $2, $3)",
            recovery_id, worker_id, batch_size,
        )
    except Exception as e:
        raise CalendarsError(
            f"Failed to requeue calendar recovery batch: {e}"
        ) from e


async def refresh_waiting_calendar_recoveries(pool, batch_size: int = 20) -> int:
    """Recompute progress for `waiting` recoveries, finalizing drained ones.

    No claim/lock needed: every step is a single atomic SQL pass over
    already-tagged events, not an external call.

    Returns:
        Number of recovery generations processed this call.

    Raises:
        CalendarsError: If the RPC call fails.
    """
    try:
        return await pool.fetchval(
            "SELECT public.refresh_waiting_calendar_recoveries($1)", batch_size
        ) or 0
    except Exception as e:
        raise CalendarsError(
            f"Failed to refresh waiting calendar recoveries: {e}"
        ) from e


class CalendarDivergedError(CalendarsError):
    """Raised when the live Google Calendar event differs from Selko's last write.

    Attributes:
        changed_fields: Human-readable field names that diverged.
    """

    def __init__(
        self,
        message: str,
        changed_fields: list[str] | None = None,
        differences: list[dict[str, Any]] | None = None,
        google_event_url: str | None = None,
    ) -> None:
        super().__init__(message)
        self.changed_fields = changed_fields or []
        self.differences = differences or []
        self.google_event_url = google_event_url


def fetch_calendar_events_for_date_range(
    supabase_client: Client,
    user_id: str,
    time_min: str,
    time_max: str,
    user_timezone: Optional[str] = None,
) -> list[dict[str, Any]]:
    """Fetch user's Google Calendar events for a date range.

    Used for deduplication: check if an event already exists on the user's
    calendar before creating a new one.

    Args:
        supabase_client: Authenticated Supabase client.
        user_id: UUID of user.
        time_min: ISO datetime string for range start.
        time_max: ISO datetime string for range end.
        user_timezone: IANA timezone for GCal response projection.

    Returns:
        List of Google Calendar event dicts. Empty list on any error.
    """
    try:
        creds = get_credentials(supabase_client, user_id, "google_calendar")
        if not creds:
            logger.debug("No Google Calendar credentials for GCal read-back")
            return []

        settings = get_calendar_settings(supabase_client, user_id)
        calendar_id = settings.get("target_calendar_id") or "primary"
        tz = user_timezone or settings.get("timezone") or "America/New_York"

        service = build("calendar", "v3", credentials=creds)

        result = service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            maxResults=50,
            timeZone=tz,
        ).execute()

        return result.get("items", [])

    except Exception as e:
        logger.warning(f"GCal read-back failed for user {user_id}: {e}")
        return []


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
        if isinstance(e, HttpError) and getattr(e.resp, "status", None) == 401:
            update_integration_status(
                supabase_client,
                "google_calendar",
                "expired",
                user_id=user_id,
            )
        raise CalendarsError(f"Failed to list calendars: {e}") from e


_DEFAULT_ALL_DAY_SETTINGS: dict[str, Any] = {
    "all_day_display_mode": "all_day",
    "all_day_custom_start": None,
    "all_day_custom_end": None,
}


def get_calendar_settings(
    supabase_client: Client, user_id: str
) -> dict[str, Any]:
    """Get target calendar and default invitees.

    Args:
        supabase_client: Authenticated Supabase client.
        user_id: UUID of user.

    Returns:
        Dict with target_calendar_id, target_calendar_name, default_invitees,
        timezone, and all-day materialization preference fields.
    """
    result = supabase_client.table("user_calendar_settings").select("*").eq(
        "user_id", user_id
    ).execute()

    if not result.data:
        return {
            "target_calendar_id": None,
            "target_calendar_name": None,
            "default_invitees": None,
            "timezone": "America/New_York",
            **_DEFAULT_ALL_DAY_SETTINGS,
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
        "timezone": settings.get("timezone", "America/New_York"),
        "all_day_display_mode": settings.get("all_day_display_mode") or "all_day",
        "all_day_custom_start": settings.get("all_day_custom_start"),
        "all_day_custom_end": settings.get("all_day_custom_end"),
    }


def get_all_day_policy_and_timezone(
    supabase_client: Client, user_id: str
) -> tuple["AllDayPolicy", str]:
    """Lean fetch of timezone + all-day preference (no GCal list call).

    Returns:
        (AllDayPolicy, IANA timezone name)
    """
    from selko.services.calendar_policy import all_day_policy_from_settings

    try:
        result = (
            supabase_client.table("user_calendar_settings")
            .select(
                "timezone, all_day_display_mode, "
                "all_day_custom_start, all_day_custom_end"
            )
            .eq("user_id", user_id)
            .execute()
        )
        row: dict[str, Any] = {}
        if (
            result.data
            and isinstance(result.data, list)
            and result.data
            and isinstance(result.data[0], dict)
        ):
            row = result.data[0]
    except Exception as e:
        logger.warning(f"Failed to fetch all-day policy for user {user_id}: {e}")
        row = {}

    timezone_name = row.get("timezone") or "America/New_York"
    policy = all_day_policy_from_settings(row)
    return policy, timezone_name


def update_calendar_settings(
    supabase_client: Client,
    user_id: str,
    target_calendar_id: Optional[str] = None,
    default_invitees: Optional[str] = None,
    *,
    all_day_display_mode: Optional[str] = None,
    all_day_custom_start: Optional[str] = None,
    all_day_custom_end: Optional[str] = None,
    update_all_day_policy: bool = False,
) -> None:
    """Update calendar settings.

    Args:
        supabase_client: Authenticated Supabase client.
        user_id: UUID of user.
        target_calendar_id: Google Calendar ID to sync to (None = primary).
        default_invitees: Comma-separated emails to add to all events.
        all_day_display_mode: How to materialize date-only extractions events.
        all_day_custom_start: Custom window start (HH:MM[:SS]) when mode=custom.
        all_day_custom_end: Custom window end (HH:MM[:SS]) when mode=custom.
        update_all_day_policy: When True, write the all-day preference fields.
            Custom times are only cleared when switching modes if explicitly
            passed as None while mode is not custom — callers should omit
            custom times when switching presets so saved custom values remain.
    """
    payload: dict[str, Any] = {
        "user_id": user_id,
        "target_calendar_id": target_calendar_id,
        "default_invitees": default_invitees,
    }

    if update_all_day_policy or all_day_display_mode is not None:
        from selko.services.calendar_policy import validate_all_day_policy

        mode = all_day_display_mode or "all_day"
        policy = validate_all_day_policy(
            mode,
            custom_start=all_day_custom_start,
            custom_end=all_day_custom_end,
        )
        payload["all_day_display_mode"] = policy.mode.value
        # Preserve previously saved custom times when switching to a preset:
        # only write custom columns when provided or when mode is custom.
        if policy.mode.value == "custom":
            payload["all_day_custom_start"] = (
                policy.custom_start.isoformat(timespec="minutes")
                if policy.custom_start
                else None
            )
            payload["all_day_custom_end"] = (
                policy.custom_end.isoformat(timespec="minutes")
                if policy.custom_end
                else None
            )
        elif all_day_custom_start is not None or all_day_custom_end is not None:
            if all_day_custom_start is not None:
                payload["all_day_custom_start"] = all_day_custom_start
            if all_day_custom_end is not None:
                payload["all_day_custom_end"] = all_day_custom_end

    supabase_client.table("user_calendar_settings").upsert(payload).execute()

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
    # Prepare description with attribution and Selko footer
    description = event.get("description", "") or ""
    attribution = event.get("source_attribution", "") or ""
    if attribution:
        description = f"{description}\n\n{attribution}" if description else attribution

    # Append Selko footer if not already present
    if SELKO_FOOTER.strip() not in description:
        description += SELKO_FOOTER

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

    # Use user timezone from settings instead of hardcoded UTC
    user_tz = settings.get("timezone", "America/New_York")

    from selko.services.civil_time import gcal_all_day_fields, gcal_timed_fields

    # Handle dates
    if event.get("all_day"):
        # All-day event: local start date + exclusive local end date
        start_dt = event.get("start_datetime")
        if start_dt:
            start_fields, end_fields = gcal_all_day_fields(
                start_dt, event.get("end_datetime"), user_tz
            )
            calendar_event["start"] = start_fields
            calendar_event["end"] = end_fields
    else:
        # Timed event: naive local dateTime + IANA timeZone (never offset+tz)
        start_dt = event.get("start_datetime")
        end_dt = event.get("end_datetime")

        if start_dt:
            fields = gcal_timed_fields(start_dt, user_tz)
            if fields:
                calendar_event["start"] = fields

        if end_dt:
            fields = gcal_timed_fields(end_dt, user_tz)
            if fields:
                calendar_event["end"] = fields
        elif start_dt:
            fields = gcal_timed_fields(start_dt, user_tz)
            if fields:
                calendar_event["end"] = fields

    # Add recurrence rule if present
    recurrence_rule = event.get("recurrence_rule")
    if recurrence_rule:
        calendar_event["recurrence"] = [recurrence_rule]

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


def _find_calendar_event_by_selko_id(
    service: Any,
    calendar_id: str,
    event_id: str,
) -> str | None:
    """Find a previously created event after an ambiguous insert failure."""
    result = service.events().list(
        calendarId=calendar_id,
        privateExtendedProperty=f"selko_event_id={event_id}",
        showDeleted=False,
        maxResults=2,
    ).execute()
    items = result.get("items", []) if isinstance(result, dict) else []
    if len(items) > 1:
        logger.warning(
            "Found multiple Google Calendar events for Selko event %s", event_id
        )
    for item in items:
        google_event_id = item.get("id")
        if google_event_id:
            return google_event_id
    return None


def sync_event_to_calendar(
    supabase_client: Client,
    user_id: str,
    event_id: str,
    *,
    write_local_state: bool = True,
    expected_provider_revision: str | None = None,
    force_overwrite: bool = False,
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
            raise CalendarAuthRequiredError("No Google Calendar credentials found")

        settings = get_calendar_settings(supabase_client, user_id)
        calendar_id = settings.get("target_calendar_id") or "primary"

        # Build Calendar API client
        service = build("calendar", "v3", credentials=creds)

        # Build the event body
        calendar_event = _build_calendar_event_body(event, settings)

        existing_google_id = event.get("google_calendar_event_id")

        if existing_google_id:
            if expected_provider_revision and not force_overwrite:
                observed = service.events().get(
                    calendarId=calendar_id, eventId=existing_google_id
                ).execute()
                observed_revision = observed.get("etag") or observed.get("updated")
                if observed_revision != expected_provider_revision:
                    raise CalendarDivergedError(
                        "Google Calendar changed after Selko queued this write.",
                        changed_fields=["provider_revision"],
                        google_event_url=observed.get("htmlLink"),
                    )
            # Event was previously synced - try to update or recreate
            google_event_id, action = _update_or_recreate_calendar_event(
                service, calendar_id, existing_google_id, calendar_event
            )
        else:
            # Reconcile an ambiguous earlier insert before creating. Google may
            # have accepted the original insert even when its response timed
            # out or the subsequent database update failed.
            recovered_google_id = _find_calendar_event_by_selko_id(
                service, calendar_id, event_id
            )
            if recovered_google_id:
                google_event_id, action = _update_or_recreate_calendar_event(
                    service, calendar_id, recovered_google_id, calendar_event
                )
            else:
                created_event = service.events().insert(
                    calendarId=calendar_id,
                    body=calendar_event
                ).execute()
                google_event_id = created_event["id"]
                action = "created"

        # The durable worker owns the local transition. Direct callers retain
        # the historical behavior for non-worker maintenance flows.
        if write_local_state:
            supabase_client.table("events").update({
                "google_calendar_event_id": google_event_id,
                "status": "synced",
                "synced_at": datetime.now(timezone.utc).isoformat(),
                "sync_error": None,
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
        classification = classify_calendar_error(e)

        if classification.code in ("oauth_required", "oauth_scope_required"):
            update_integration_status(
                supabase_client,
                "google_calendar",
                "expired",
                user_id=user_id,
            )
            # Leave status/attempt bookkeeping to the caller: an OAuth-blocked
            # sync isn't a real attempt against the user's calendar, so it
            # must not be dead-lettered or count toward the shared circuit
            # breaker. Only tag the classification here for observability.
            update_payload: dict[str, Any] = {
                "sync_failure_code": classification.code,
                "sync_error": classification.user_message,
            }
        else:
            update_payload = {
                "status": "sync_failed",
                "sync_error": str(e),
                "sync_failure_code": classification.code,
            }

        if write_local_state:
            try:
                supabase_client.table("events").update(update_payload).eq(
                    "id", event_id
                ).execute()
            except Exception as update_error:
                logger.warning(f"Failed to update event after sync failure: {update_error}")

        raise CalendarsError(
            f"Failed to sync event to calendar: {e}", classification=classification
        ) from e


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
        user_tz = settings.get("timezone", "America/New_York")

        from selko.services.civil_time import gcal_all_day_fields, gcal_timed_fields

        if event.get("all_day"):
            if start_dt:
                start_fields, end_fields = gcal_all_day_fields(start_dt, end_dt, user_tz)
                existing_event["start"] = start_fields
                existing_event["end"] = end_fields
        else:
            if start_dt:
                fields = gcal_timed_fields(start_dt, user_tz)
                if fields:
                    existing_event["start"] = fields
            if end_dt:
                fields = gcal_timed_fields(end_dt, user_tz)
                if fields:
                    existing_event["end"] = fields

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


def cancel_event_to_calendar(
    supabase_client: Client,
    user_id: str,
    event_id: str,
    *,
    expected_provider_revision: str | None = None,
    force_overwrite: bool = False,
    delete_remote: bool = False,
) -> None:
    """Apply a queued cancellation or remote deletion.

    Provider I/O is worker-owned. The local ``cancel_queued`` -> ``cancelled``
    transition is completed by the worker with an owner/generation fence.
    """
    try:
        event_result = supabase_client.table("events").select("*").eq(
            "id", event_id
        ).single().execute()
        event = event_result.data or {}
        google_event_id = event.get("google_calendar_event_id")
        if not google_event_id:
            logger.info("Event %s has no remote calendar copy; cancellation is local-only", event_id)
            return

        service, calendar_id = _calendar_service_for_user(supabase_client, user_id)
        try:
            existing_event = service.events().get(
                calendarId=calendar_id,
                eventId=google_event_id,
            ).execute()
            observed_revision = existing_event.get("etag") or existing_event.get("updated")
            if expected_provider_revision and not force_overwrite and observed_revision != expected_provider_revision:
                raise CalendarDivergedError(
                    "Google Calendar changed after Selko queued this cancellation.",
                    changed_fields=["provider_revision"],
                    google_event_url=existing_event.get("htmlLink"),
                )
            if delete_remote:
                service.events().delete(
                    calendarId=calendar_id,
                    eventId=google_event_id,
                ).execute()
                action = "deleted"
            else:
                title = str(event.get("title") or existing_event.get("summary") or "")
                if not title.startswith("CANCELLED: "):
                    existing_event["summary"] = f"CANCELLED: {title}"
                service.events().update(
                    calendarId=calendar_id,
                    eventId=google_event_id,
                    body=existing_event,
                ).execute()
                action = "cancelled"
        except HttpError as exc:
            if getattr(exc.resp, "status", None) == 404:
                logger.info("Calendar event %s already deleted", google_event_id)
                action = "deleted" if delete_remote else "cancelled"
            else:
                raise
        _log_sync(
            supabase_client,
            user_id,
            event_id,
            google_event_id,
            action,
            {"deleted_google_event_id": google_event_id}
            if delete_remote else {"cancelled_google_event_id": google_event_id},
        )
        logger.info("Applied cancellation to calendar event %s", event_id)
    except CalendarsError:
        raise
    except Exception as exc:
        raise CalendarsError(f"Failed to cancel event in calendar: {exc}") from exc


def _strip_selko_footer(description: str | None) -> str:
    """Remove Selko management footer for apples-to-apples description compare."""
    text = (description or "").strip()
    footer = SELKO_FOOTER.strip()
    if footer and footer in text:
        text = text.replace(footer, "").strip()
    # Also strip a leading/trailing --- separator left behind
    if text.endswith("---"):
        text = text[: -len("---")].strip()
    return " ".join(text.split())


def _normalize_gcal_bound(bound: Any) -> tuple[str, str] | None:
    """Normalize a GCal start/end dict to a comparable (kind, value) tuple."""
    if not isinstance(bound, dict):
        return None
    if bound.get("date"):
        return ("date", str(bound["date"]))
    date_time = bound.get("dateTime")
    if not date_time:
        return None
    value = str(date_time)
    try:
        parsed = datetime.fromisoformat(
            value[:-1] + "+00:00" if value.endswith("Z") else value
        )
    except ValueError:
        return ("dateTime", value)

    if parsed.tzinfo is None:
        timezone_name = bound.get("timeZone")
        if not timezone_name:
            return ("dateTime", value)
        try:
            parsed = parsed.replace(tzinfo=ZoneInfo(str(timezone_name)))
        except (ZoneInfoNotFoundError, ValueError):
            return ("dateTime", f"{value}|{timezone_name}")

    return ("dateTime", parsed.astimezone(timezone.utc).isoformat())


def _calendar_event_differences(
    live_gcal: dict[str, Any],
    snapshot_synced: dict[str, Any],
    changed_fields: list[str],
) -> list[dict[str, Any]]:
    """Return safe structured values for a calendar drift decision."""
    field_keys = {
        "title": "summary",
        "location": "location",
        "start": "start",
        "end": "end",
        "description": "description",
    }
    return [
        {
            "field": field,
            "selko": snapshot_synced.get(field_keys[field]),
            "google": live_gcal.get(field_keys[field]),
        }
        for field in changed_fields
        if field in field_keys
    ]


def calendar_event_diverged(
    live_gcal: dict[str, Any],
    snapshot_synced: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Compare material fields between live GCal and last Selko write.

    Returns:
        (diverged, changed_fields) where changed_fields are human labels.
    """
    changed: list[str] = []

    live_summary = (live_gcal.get("summary") or "").strip()
    snap_summary = (snapshot_synced.get("summary") or "").strip()
    if live_summary != snap_summary:
        changed.append("title")

    live_location = (live_gcal.get("location") or "").strip()
    snap_location = (snapshot_synced.get("location") or "").strip()
    if live_location != snap_location:
        changed.append("location")

    if _normalize_gcal_bound(live_gcal.get("start")) != _normalize_gcal_bound(
        snapshot_synced.get("start")
    ):
        changed.append("start")

    if _normalize_gcal_bound(live_gcal.get("end")) != _normalize_gcal_bound(
        snapshot_synced.get("end")
    ):
        changed.append("end")

    live_desc = _strip_selko_footer(live_gcal.get("description"))
    snap_desc = _strip_selko_footer(snapshot_synced.get("description"))
    if live_desc != snap_desc:
        changed.append("description")

    return (bool(changed), changed)


def get_latest_sync_snapshot(
    supabase_client: Client, event_id: str
) -> dict[str, Any] | None:
    """Return the latest created/updated calendar_sync_log snapshot for an event."""
    result = (
        supabase_client.table("calendar_sync_log")
        .select("snapshot_synced, action, synced_at")
        .eq("event_id", event_id)
        .in_("action", ["created", "updated"])
        .order("synced_at", desc=True)
        .limit(1)
        .execute()
    )
    rows = result.data or []
    if not rows:
        return None
    snap = rows[0].get("snapshot_synced")
    return snap if isinstance(snap, dict) else None


def _calendar_service_for_user(
    supabase_client: Client, user_id: str
) -> tuple[Any, str]:
    """Build Calendar API client and resolve target calendar id."""
    creds = get_credentials(supabase_client, user_id, "google_calendar")
    if not creds:
        raise CalendarsError("No Google Calendar credentials found")
    settings = get_calendar_settings(supabase_client, user_id)
    calendar_id = settings.get("target_calendar_id") or "primary"
    service = build("calendar", "v3", credentials=creds)
    return service, calendar_id


def get_calendar_event(
    supabase_client: Client, user_id: str, google_event_id: str
) -> dict[str, Any] | None:
    """Fetch a live Google Calendar event. Returns None if missing (404)."""
    try:
        service, calendar_id = _calendar_service_for_user(supabase_client, user_id)
        return service.events().get(
            calendarId=calendar_id, eventId=google_event_id
        ).execute()
    except HttpError as e:
        if e.resp.status == 404:
            return None
        raise CalendarsError(f"Failed to fetch calendar event: {e}") from e
    except CalendarsError:
        raise
    except Exception as e:
        raise CalendarsError(f"Failed to fetch calendar event: {e}") from e


def assert_calendar_not_diverged(
    supabase_client: Client,
    user_id: str,
    event_id: str,
    google_event_id: str,
    *,
    force: bool = False,
) -> None:
    """Block Undo when live GCal differs from last Selko write (unless force).

    Missing sync log with a live event is treated as diverged (require force).
    Live 404 is not diverged — caller treats it as already gone.
    """
    if force:
        return

    live = get_calendar_event(supabase_client, user_id, google_event_id)
    if live is None:
        return

    snapshot = get_latest_sync_snapshot(supabase_client, event_id)
    if snapshot is None:
        raise CalendarDivergedError(
            "This calendar event may have changed since Selko synced it. "
            "Use Force Undo to revert anyway.",
            changed_fields=["unknown"],
            google_event_url=live.get("htmlLink"),
        )

    diverged, fields = calendar_event_diverged(live, snapshot)
    if diverged:
        field_list = ", ".join(fields)
        raise CalendarDivergedError(
            f"This event was edited in Google Calendar after Selko synced it "
            f"({field_list}). Use Force Undo to revert to the pre-Selko state.",
            changed_fields=fields,
            differences=_calendar_event_differences(live, snapshot, fields),
            google_event_url=live.get("htmlLink"),
        )


def delete_calendar_event_only(
    supabase_client: Client, user_id: str, event_id: str
) -> None:
    """Delete the remote GCal event and clear local sync fields (no status change).

    404 on Google Calendar is treated as success. Caller owns event status.
    """
    try:
        event_result = supabase_client.table("events").select("*").eq(
            "id", event_id
        ).single().execute()
        event = event_result.data

        google_event_id = event.get("google_calendar_event_id")
        if not google_event_id:
            raise CalendarsError("Event is not synced to Google Calendar")

        service, calendar_id = _calendar_service_for_user(supabase_client, user_id)

        try:
            service.events().delete(
                calendarId=calendar_id, eventId=google_event_id
            ).execute()
        except HttpError as e:
            if e.resp.status == 404:
                logger.warning(
                    f"Calendar event {google_event_id} already deleted from Google Calendar"
                )
            else:
                raise

        supabase_client.table("events").update({
            "google_calendar_event_id": None,
            "synced_at": None,
        }).eq("id", event_id).execute()

        _log_sync(
            supabase_client,
            user_id,
            event_id,
            google_event_id,
            "deleted",
            {"deleted_google_event_id": google_event_id},
        )

        logger.info(f"Deleted calendar event for {event_id} (sync fields cleared)")

    except CalendarsError:
        raise
    except Exception as e:
        raise CalendarsError(f"Failed to delete calendar event: {e}") from e


def restore_calendar_event_from_selko_fields(
    supabase_client: Client,
    user_id: str,
    event_id: str,
    selko_fields: dict[str, Any],
) -> None:
    """PATCH the live GCal event to match restored Selko fields (keep google id)."""
    try:
        event_result = supabase_client.table("events").select("*").eq(
            "id", event_id
        ).single().execute()
        event = event_result.data

        google_event_id = event.get("google_calendar_event_id")
        if not google_event_id:
            raise CalendarsError("Event is not synced to Google Calendar")

        # Merge restored fields onto the current event row for body build
        merged = {**event, **selko_fields, "id": event_id}
        settings = get_calendar_settings(supabase_client, user_id)
        calendar_event = _build_calendar_event_body(merged, settings)

        service, calendar_id = _calendar_service_for_user(supabase_client, user_id)
        google_event_id, action = _update_or_recreate_calendar_event(
            service, calendar_id, google_event_id, calendar_event
        )

        # If recreate issued a new id, persist it
        if google_event_id != event.get("google_calendar_event_id"):
            supabase_client.table("events").update({
                "google_calendar_event_id": google_event_id,
                "synced_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", event_id).execute()
        else:
            supabase_client.table("events").update({
                "synced_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", event_id).execute()

        _log_sync(
            supabase_client,
            user_id,
            event_id,
            google_event_id,
            action,
            calendar_event,
        )
        logger.info(
            f"Restored calendar event for {event_id} from Selko snapshot ({action})"
        )

    except CalendarsError:
        raise
    except Exception as e:
        raise CalendarsError(f"Failed to restore calendar event: {e}") from e


def delete_calendar_event(
    supabase_client: Client, user_id: str, event_id: str
) -> None:
    """Delete event from Google Calendar and revert local status to pending_review.

    Used by ``/unsync``. History Undo should call ``delete_calendar_event_only``
    instead so it can set the correct review-lane status.
    """
    delete_calendar_event_only(supabase_client, user_id, event_id)
    supabase_client.table("events").update({
        "status": "pending_review",
    }).eq("id", event_id).execute()
    logger.info(f"Unsynced event {event_id}, reverted to pending_review")
