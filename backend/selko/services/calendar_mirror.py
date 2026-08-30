"""Incremental projection of the user's calendar into `calendar_entries`.

Matching could only see a calendar entry when an email happened to fall on the
same local day, through a read capped at 50 results that retained nothing. An
invite the user had already accepted therefore had no row anywhere Selko could
look, and "do we already know this?" degraded into an LLM text comparison.

This module keeps a durable, incrementally-synced projection instead. It is
read-only with respect to the provider: nothing here writes to Google Calendar,
which remains owned by `calendar_work_items`.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from supabase import Client

from selko.services.integrations import get_credentials
from selko.services.calendars import CalendarsError, get_calendar_settings
from selko.services.event_identity import hints_from_calendar_event

logger = logging.getLogger(__name__)

#: How much calendar is worth mirroring. Matching only ever asks about events
#: near an extracted date, so all history is unbounded and pointless.
WINDOW_BEHIND = timedelta(days=90)
WINDOW_AHEAD = timedelta(days=365)

#: Google returns 410 when a sync token has expired and a full resync is needed.
_SYNC_TOKEN_EXPIRED = 410


def rolling_window(now: datetime | None = None) -> tuple[datetime, datetime]:
    reference = now or datetime.now(timezone.utc)
    return reference - WINDOW_BEHIND, reference + WINDOW_AHEAD


def _self_response(entry: dict[str, Any]) -> str | None:
    for attendee in entry.get("attendees") or []:
        if isinstance(attendee, dict) and attendee.get("self"):
            return attendee.get("responseStatus")
    return None


def _origin(entry: dict[str, Any]) -> str:
    private = ((entry.get("extendedProperties") or {}).get("private")) or {}
    return "selko_created" if private.get("selko_event_id") else "external"


def _bound(value: Any) -> tuple[str | None, bool]:
    """Return (timestamp, all_day) for a Google start/end block."""
    if not isinstance(value, dict):
        return None, False
    if value.get("dateTime"):
        return value["dateTime"], False
    if value.get("date"):
        # An all-day event has a date and no time; store it as midnight so the
        # column stays a timestamptz and range queries keep working.
        return f"{value['date']}T00:00:00+00:00", True
    return None, False


def entry_row(
    entry: dict[str, Any], *, user_id: str, integration_id: str, calendar_id: str
) -> dict[str, Any]:
    """Map a Google Calendar event resource onto a `calendar_entries` row."""
    start_at, start_all_day = _bound(entry.get("start"))
    end_at, _ = _bound(entry.get("end"))
    original = entry.get("originalStartTime")
    original_start = ""
    if isinstance(original, dict):
        original_start = str(original.get("dateTime") or original.get("date") or "")

    return {
        "user_id": user_id,
        "integration_id": integration_id,
        "calendar_id": calendar_id,
        "provider_event_id": entry.get("id"),
        "ical_uid": entry.get("iCalUID"),
        "recurring_event_id": entry.get("recurringEventId"),
        "original_start": original_start,
        "title": entry.get("summary"),
        "location": entry.get("location"),
        "start_at": start_at,
        "end_at": end_at,
        "all_day": start_all_day,
        "timezone": (entry.get("start") or {}).get("timeZone"),
        "status": entry.get("status") or "confirmed",
        "self_response": _self_response(entry),
        "etag": entry.get("etag"),
        "sequence": entry.get("sequence"),
        "provider_updated_at": entry.get("updated"),
        "origin": _origin(entry),
        # Google reports a removed event as status=cancelled in an incremental
        # page. Tombstone it rather than deleting the row: the disappearance is
        # itself the signal that the user removed something.
        "deleted_at": (
            datetime.now(timezone.utc).isoformat()
            if entry.get("status") == "cancelled"
            else None
        ),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }


def fetch_page(
    service: Any,
    calendar_id: str,
    *,
    sync_token: str | None,
    window: tuple[datetime, datetime],
    page_token: str | None = None,
) -> dict[str, Any]:
    """One page of events, incremental when a sync token is available.

    `timeMin`/`timeMax` may not be combined with `syncToken`; Google keeps the
    window from the request that issued the token.
    """
    params: dict[str, Any] = {
        "calendarId": calendar_id,
        "singleEvents": True,
        "maxResults": 250,
        "showDeleted": True,
    }
    if page_token:
        params["pageToken"] = page_token
    if sync_token:
        params["syncToken"] = sync_token
    else:
        params["timeMin"] = window[0].isoformat()
        params["timeMax"] = window[1].isoformat()
    return service.events().list(**params).execute()


def sync_calendar(
    supabase_client: Client,
    user_id: str,
    integration_id: str,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Bring `calendar_entries` up to date for one calendar.

    Returns a content-free summary: counts and whether a full resync happened.
    """
    credentials = get_credentials(supabase_client, user_id, "google_calendar")
    if not credentials:
        raise CalendarsError("No Google Calendar credentials found")

    settings = get_calendar_settings(supabase_client, user_id)
    calendar_id = settings.get("target_calendar_id") or "primary"
    window = rolling_window(now)

    state = (
        supabase_client.table("calendar_mirror_state")
        .select("sync_token")
        .eq("integration_id", integration_id)
        .eq("calendar_id", calendar_id)
        .maybe_single()
        .execute()
    )
    sync_token = (getattr(state, "data", None) or {}).get("sync_token")

    service = build("calendar", "v3", credentials=credentials)
    full_resync = sync_token is None
    rows: list[dict[str, Any]] = []
    page_token: str | None = None
    next_sync_token: str | None = None

    while True:
        try:
            page = fetch_page(
                service,
                calendar_id,
                sync_token=sync_token,
                window=window,
                page_token=page_token,
            )
        except HttpError as exc:
            if getattr(exc, "resp", None) is not None and exc.resp.status == _SYNC_TOKEN_EXPIRED:
                # The cursor aged out. Drop it and take one full window read.
                logger.info("Calendar sync token expired; performing a full resync")
                sync_token = None
                page_token = None
                full_resync = True
                rows = []
                continue
            raise CalendarsError(f"Calendar mirror sync failed: {exc}") from exc

        for entry in page.get("items", []):
            if not entry.get("id"):
                continue
            rows.append(
                entry_row(
                    entry,
                    user_id=user_id,
                    integration_id=integration_id,
                    calendar_id=calendar_id,
                )
            )
        page_token = page.get("nextPageToken")
        next_sync_token = page.get("nextSyncToken") or next_sync_token
        if not page_token:
            break

    if rows:
        stored = (
            supabase_client.table("calendar_entries")
            .upsert(rows, on_conflict="integration_id,calendar_id,provider_event_id")
            .execute()
            .data
            or []
        )
        _write_entry_hints(supabase_client, user_id, stored)

    supabase_client.table("calendar_mirror_state").upsert(
        {
            "integration_id": integration_id,
            "calendar_id": calendar_id,
            "user_id": user_id,
            "sync_token": next_sync_token,
            "window_start": window[0].isoformat(),
            "window_end": window[1].isoformat(),
            "last_success_at": datetime.now(timezone.utc).isoformat(),
            "last_full_resync_at": (
                datetime.now(timezone.utc).isoformat() if full_resync else None
            ),
            "consecutive_failures": 0,
            "last_error_code": None,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="integration_id,calendar_id",
    ).execute()

    return {
        "entries": len(rows),
        "full_resync": full_resync,
        "has_sync_token": next_sync_token is not None,
    }


def _write_entry_hints(
    supabase_client: Client, user_id: str, stored: list[dict[str, Any]]
) -> None:
    """Index mirrored entries by identity so matching can find them.

    Without this the mirror is only a table: `find_matching_event` resolves by
    hint lookup, so an entry with no hint row is invisible to every rung above
    the LLM text comparison.
    """
    payload: list[dict[str, Any]] = []
    for row in stored:
        entry_id = row.get("id")
        if not entry_id or row.get("deleted_at"):
            continue
        for hint in hints_from_calendar_event(
            {
                "iCalUID": row.get("ical_uid"),
                "originalStartTime": (
                    {"dateTime": row["original_start"]} if row.get("original_start") else None
                ),
            }
        ):
            payload.append(
                {
                    "user_id": user_id,
                    "event_id": None,
                    "calendar_entry_id": entry_id,
                    **hint.as_payload(),
                }
            )
    if not payload:
        return
    try:
        supabase_client.table("event_identity_hints").upsert(
            payload,
            on_conflict="calendar_entry_id,kind,value_hash,recurrence_id",
        ).execute()
    except Exception:
        # A hint that fails to store costs a match, never a wrong one.
        logger.exception("Could not index calendar entry identity hints")
