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
from selko.services.calendars import CalendarsError, list_calendars
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


def _join_url(entry: dict[str, Any]) -> str | None:
    """The entry's conferencing link, if it has one.

    Kept on the row so `_write_entry_hints` can hand it back to
    `hints_from_calendar_event`, which already knows how to hash a join URL.
    Without it the mirror indexes entries by iCalUID only, and an event
    extracted from an email -- which carries a join URL and no UID -- shares no
    hint with the calendar entry describing the very same meeting.
    """
    if entry.get("hangoutLink"):
        return str(entry["hangoutLink"])
    conference = entry.get("conferenceData")
    if isinstance(conference, dict):
        for point in conference.get("entryPoints") or []:
            if isinstance(point, dict) and point.get("uri"):
                return str(point["uri"])
    return None


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
        "join_url": _join_url(entry),
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
    calendar_id: str = "primary",
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Bring `calendar_entries` up to date for one calendar.

    Returns a content-free summary: counts and whether a full resync happened.
    """
    credentials = get_credentials(supabase_client, user_id, "google_calendar")
    if not credentials:
        raise CalendarsError("No Google Calendar credentials found")

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
        supabase_client.table("calendar_entries").upsert(
            rows, on_conflict="integration_id,calendar_id,provider_event_id"
        ).execute()
        # Read the rows back rather than trusting the upsert's response. It
        # returned nothing, so `stored` was empty and no hint was ever written:
        # production mirrored 1595 entries carrying 1595 iCalUIDs and indexed
        # none of them, which is the whole point of the mirror. The tests
        # covered the row mapping and the wiring, and neither could see this,
        # because the gap is in what the database hands back.
        _write_entry_hints(
            supabase_client,
            user_id,
            _reload_stored(supabase_client, user_id, rows),
        )

    # Index anything still missing a hint, whether or not this pass changed it.
    #
    # Indexing only what a pass upserts leaves every entry mirrored before the
    # indexing worked unreachable for good: once a sync token exists, an
    # unchanged calendar returns no rows, so nothing is upserted and nothing is
    # indexed. Production sat at 1595 mirrored entries and 0 hints for exactly
    # that reason. Making this a repair rather than a side effect of writing
    # means the index converges on its own.
    _index_unhinted_entries(supabase_client, user_id)

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
                # The join URL is the only hint an email-extracted event and a
                # calendar entry realistically share: emails carry Zoom links
                # and no UID, calendar entries carry a UID the email never
                # mentions. Omitting it left the two hint sets disjoint.
                "hangoutLink": row.get("join_url"),
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


def _reload_stored(
    supabase_client: Client, user_id: str, rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Fetch the ids of entries just written, in batches.

    Upsert does not return representations here, and hint rows need the entry
    id. Batched because `in_` on a few thousand provider ids is a URL, not a
    query, and a mirror of a busy calendar will exceed what one request can
    carry.
    """
    provider_ids = [row["provider_event_id"] for row in rows if row.get("provider_event_id")]
    stored: list[dict[str, Any]] = []
    batch = 200
    for start in range(0, len(provider_ids), batch):
        chunk = provider_ids[start : start + batch]
        try:
            result = (
                supabase_client.table("calendar_entries")
                .select("id,ical_uid,original_start,deleted_at,join_url")
                .eq("user_id", user_id)
                .in_("provider_event_id", chunk)
                .execute()
            )
            stored.extend(row for row in (result.data or []) if isinstance(row, dict))
        except Exception:
            logger.exception("Could not reload mirrored entries for indexing")
    return stored


def _index_unhinted_entries(
    supabase_client: Client, user_id: str, limit: int = 500
) -> int:
    """Write hints for mirrored entries that have none. Returns how many.

    Bounded per pass so a large calendar converges over several syncs instead of
    issuing one unbounded query, and so a failure costs one batch rather than
    the whole sync.
    """
    try:
        entries = (
            supabase_client.table("calendar_entries")
            .select("id,ical_uid,original_start")
            .eq("user_id", user_id)
            .not_.is_("ical_uid", "null")
            .is_("deleted_at", "null")
            .limit(limit)
            .execute()
            .data
            or []
        )
    except Exception:
        logger.exception("Could not list calendar entries for indexing")
        return 0
    if not entries:
        return 0

    try:
        hinted = {
            row["calendar_entry_id"]
            for row in (
                supabase_client.table("event_identity_hints")
                .select("calendar_entry_id")
                .eq("user_id", user_id)
                .not_.is_("calendar_entry_id", "null")
                .execute()
                .data
                or []
            )
            if row.get("calendar_entry_id")
        }
    except Exception:
        logger.exception("Could not list existing calendar hints")
        return 0

    missing = [entry for entry in entries if entry.get("id") not in hinted]
    if not missing:
        return 0
    _write_entry_hints(supabase_client, user_id, missing)
    logger.info("Indexed %d previously unindexed calendar entries", len(missing))
    return len(missing)


def sync_all_calendars(
    supabase_client: Client, user_id: str, integration_id: str
) -> dict[str, Any]:
    """Mirror every calendar the account can see, not only the write target.

    `target_calendar_id or "primary"` is where Selko *writes*. It is not where
    invitations *arrive*. A Google account routinely carries several calendars,
    and an invite lands on whichever one its address belongs to: this account
    has three, and the interview invitations that Selko kept proposing as new
    were on one it never read. Mirroring only the write target made "the user
    already has this" unanswerable for every calendar but one.

    One calendar failing -- a permission, a deleted subscription -- must not
    stop the rest, so each is attempted independently.
    """
    try:
        calendars = list_calendars(supabase_client, user_id)
    except Exception as exc:
        raise CalendarsError(f"Could not list calendars: {exc}") from exc

    totals = {"calendars": 0, "entries": 0, "failed": 0}
    for calendar in calendars:
        calendar_id = calendar.get("id")
        if not calendar_id:
            continue
        # Never mirror the literal alias. "primary" resolves to the account's
        # own calendar, which list_calendars also returns under its real id, so
        # accepting both stores every event twice under two calendar ids. That
        # is not merely wasteful: one iCalUID then names two mirrored entries,
        # and identity matching treats an ambiguous hint as no match at all --
        # the alias would silently undo the thing this mirror exists for. 241
        # UIDs were duplicated this way before it was caught.
        if calendar_id == "primary":
            continue
        try:
            summary = sync_calendar(
                supabase_client, user_id, integration_id, calendar_id
            )
            totals["calendars"] += 1
            totals["entries"] += summary["entries"]
        except Exception:
            totals["failed"] += 1
            logger.exception("Calendar mirror sync failed for one calendar")
    return totals
