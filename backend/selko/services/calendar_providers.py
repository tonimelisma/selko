"""Calendar provider adapters: Google Calendar and Outlook Calendar.

Every calendar consumer in Selko -- the worker-owned writer in
`calendars.py`, the mirror in `calendar_mirror.py`, dedup read-back in
`events.py`, divergence checks for undo -- was written against Google
Calendar's event resource. Rather than fork each of them per provider, both
adapters here speak that one shape: an Outlook event crosses this boundary
already translated into `summary`/`start`/`end`/`iCalUID`/
`extendedProperties`, and a Google-shaped body is translated into Graph's on
the way out. Provider differences live in exactly one file.

Ids are provider-qualified. Google ids stay bare, because every id already
stored is one; Outlook ids carry the `outlook:` prefix, for calendars and
events alike. An id therefore always says which calendar owns it, including
one adopted by dedup from a mirror row and written into
`events.google_calendar_event_id` -- see migration 20261031000001, whose
`calendar_provider_of_id` is the SQL twin of `provider_of_id` below.
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional, Protocol
from urllib.parse import quote

from supabase import Client

logger = logging.getLogger(__name__)

GOOGLE = "google_calendar"
OUTLOOK = "outlook"
PROVIDERS = (GOOGLE, OUTLOOK)

#: Circuit-breaker key per provider. Google keeps its historical key so an
#: open circuit survives the deploy; Outlook gets its own, because a Graph
#: outage must not stop Google writes (or the reverse).
BREAKER_KEYS = {GOOGLE: "google_calendar", OUTLOOK: "outlook_calendar"}

DISPLAY_NAMES = {GOOGLE: "Google Calendar", OUTLOOK: "Outlook Calendar"}

OUTLOOK_PREFIX = "outlook:"

#: Graph's delegated permission for reading and writing the user's calendars.
OUTLOOK_CALENDAR_SCOPE = "Calendars.ReadWrite"

GRAPH = "https://graph.microsoft.com/v1.0"

#: A fixed, Selko-owned property set for the private Selko event id, so an
#: event created by Selko can be found again after an ambiguous insert -- the
#: Graph equivalent of Google's private extendedProperty.
_SELKO_PROPERTY_ID = "String {6f4b1a86-3f0e-4c2a-9d55-5e1c0d7a9b21} Name selko_event_id"


class CalendarEventNotFound(Exception):
    """The provider has no such event (Google 404, Graph 404)."""


class CalendarSyncTokenExpired(Exception):
    """An incremental cursor aged out; the caller must take a full read."""


class CalendarProviderUnavailable(Exception):
    """No usable credentials for this provider.

    Carries the provider so failure classification can name the calendar the
    user has to reconnect.
    """

    def __init__(self, message: str, provider: str) -> None:
        super().__init__(message)
        self.provider = provider


def qualify(provider: str, raw_id: str) -> str:
    """Return the stored form of a provider id."""
    if provider == OUTLOOK and not raw_id.startswith(OUTLOOK_PREFIX):
        return f"{OUTLOOK_PREFIX}{raw_id}"
    return raw_id


def unqualify(qualified_id: str) -> str:
    """Return the id the provider itself understands."""
    if qualified_id.startswith(OUTLOOK_PREFIX):
        return qualified_id[len(OUTLOOK_PREFIX):]
    return qualified_id


def provider_of_id(qualified_id: Optional[str]) -> str:
    """Which provider owns a stored calendar or event id."""
    if qualified_id and qualified_id.startswith(OUTLOOK_PREFIX):
        return OUTLOOK
    return GOOGLE


def outlook_scopes_allow_calendar(scopes: Optional[list[str]]) -> bool:
    """Whether a stored Microsoft grant includes calendar read/write.

    Outlook users who connected before calendar support hold a mail-only
    grant on an active row. SQL twin: `outlook_scopes_allow_calendar`.
    """
    return any(
        str(scope).lower().endswith(OUTLOOK_CALENDAR_SCOPE.lower())
        for scope in (scopes or [])
    )


def writable_providers(integrations: list[dict[str, Any]]) -> list[str]:
    """Providers the user can write events to, Google first.

    SQL twin: `calendar_integration_writable`.
    """
    writable: list[str] = []
    for provider in PROVIDERS:
        for row in integrations:
            if row.get("provider") != provider or row.get("status") != "active":
                continue
            if provider == OUTLOOK and not outlook_scopes_allow_calendar(row.get("scopes")):
                continue
            writable.append(provider)
            break
    return writable


def resolve_target_provider(
    target_calendar_id: Optional[str], integrations: list[dict[str, Any]]
) -> str:
    """Where a new event goes. SQL twin: `calendar_write_provider` rules 2-3."""
    if target_calendar_id:
        return provider_of_id(target_calendar_id)
    writable = writable_providers(integrations)
    return writable[0] if writable else GOOGLE


class CalendarAdapter(Protocol):
    """One calendar provider, speaking Google Calendar's event shape."""

    provider: str

    def list_calendars(self) -> list[dict[str, Any]]: ...

    def list_events(
        self, calendar_id: str, *, time_min: str, time_max: str, time_zone: str,
        max_results: int = 50,
    ) -> list[dict[str, Any]]: ...

    def get_event(self, calendar_id: str, event_id: str) -> dict[str, Any]: ...

    def insert_event(self, calendar_id: str, body: dict[str, Any]) -> dict[str, Any]: ...

    def update_event(
        self, calendar_id: str, event_id: str, body: dict[str, Any]
    ) -> dict[str, Any]: ...

    def delete_event(self, calendar_id: str, event_id: str) -> None: ...

    def find_event_by_selko_id(self, calendar_id: str, selko_event_id: str) -> Optional[str]: ...

    def mirror_page(
        self, calendar_id: str, *, sync_token: Optional[str],
        window: tuple[datetime, datetime], page_token: Optional[str] = None,
    ) -> dict[str, Any]: ...


# --- Google -------------------------------------------------------------------


def _google_status(exc: Exception) -> Optional[int]:
    resp = getattr(exc, "resp", None)
    return getattr(resp, "status", None) if resp is not None else None


class GoogleCalendarAdapter:
    """Thin wrapper over a built Calendar v3 service.

    The service is built by the caller (`calendars.py`), which keeps `build`
    and `get_credentials` patchable where existing callers already patch them.
    """

    provider = GOOGLE

    def __init__(self, service: Any) -> None:
        self.service = service

    def list_calendars(self) -> list[dict[str, Any]]:
        result = self.service.calendarList().list().execute()
        return [
            {
                "id": cal["id"],
                "summary": cal.get("summary") or cal["id"],
                "primary": bool(cal.get("primary", False)),
                "can_write": cal.get("accessRole") in (None, "owner", "writer"),
            }
            for cal in result.get("items", [])
        ]

    def list_events(self, calendar_id, *, time_min, time_max, time_zone, max_results=50):
        result = self.service.events().list(
            calendarId=calendar_id,
            timeMin=time_min,
            timeMax=time_max,
            singleEvents=True,
            maxResults=max_results,
            timeZone=time_zone,
        ).execute()
        return result.get("items", [])

    def get_event(self, calendar_id, event_id):
        try:
            return self.service.events().get(calendarId=calendar_id, eventId=event_id).execute()
        except Exception as exc:
            if _google_status(exc) == 404:
                raise CalendarEventNotFound(event_id) from exc
            raise

    def insert_event(self, calendar_id, body):
        return self.service.events().insert(calendarId=calendar_id, body=body).execute()

    def update_event(self, calendar_id, event_id, body):
        try:
            return self.service.events().update(
                calendarId=calendar_id, eventId=event_id, body=body
            ).execute()
        except Exception as exc:
            if _google_status(exc) == 404:
                raise CalendarEventNotFound(event_id) from exc
            raise

    def delete_event(self, calendar_id, event_id):
        try:
            self.service.events().delete(calendarId=calendar_id, eventId=event_id).execute()
        except Exception as exc:
            if _google_status(exc) in (404, 410):
                raise CalendarEventNotFound(event_id) from exc
            raise

    def find_event_by_selko_id(self, calendar_id, selko_event_id):
        result = self.service.events().list(
            calendarId=calendar_id,
            privateExtendedProperty=f"selko_event_id={selko_event_id}",
            showDeleted=False,
            maxResults=2,
        ).execute()
        items = result.get("items", []) if isinstance(result, dict) else []
        if len(items) > 1:
            logger.warning("Found multiple Google Calendar events for Selko event %s", selko_event_id)
        for item in items:
            if item.get("id"):
                return item["id"]
        return None

    def mirror_page(self, calendar_id, *, sync_token, window, page_token=None):
        # timeMin/timeMax may not be combined with syncToken; Google keeps the
        # window from the request that issued the token.
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
        try:
            return self.service.events().list(**params).execute()
        except Exception as exc:
            if _google_status(exc) == 410:
                raise CalendarSyncTokenExpired() from exc
            raise


# --- Outlook ------------------------------------------------------------------

#: Graph's projection of every event response into one zone. UTC keeps the
#: conversion exact; all-day events are re-anchored to their date below.
_OUTLOOK_READ_PREFER = 'IdType="ImmutableId", outlook.timezone="UTC", outlook.body-content-type="text"'

_RESPONSE_STATUS = {
    "accepted": "accepted",
    "organizer": "accepted",
    "tentativelyaccepted": "tentative",
    "declined": "declined",
    "notresponded": "needsAction",
    "none": "needsAction",
}

_WEEKDAYS = {
    "MO": "monday", "TU": "tuesday", "WE": "wednesday", "TH": "thursday",
    "FR": "friday", "SA": "saturday", "SU": "sunday",
}
_ORDINALS = {1: "first", 2: "second", 3: "third", 4: "fourth", -1: "last"}


def _graph_utc(value: Any) -> Optional[datetime]:
    """Parse a Graph dateTimeTimeZone that was projected into UTC."""
    raw = value.get("dateTime") if isinstance(value, dict) else value
    if not raw:
        return None
    text = str(raw)
    # Graph emits seven fractional digits, which fromisoformat rejects.
    text = re.sub(r"(\.\d{6})\d+", r"\1", text).replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    zone = value.get("timeZone") if isinstance(value, dict) else None
    if parsed.tzinfo is None:
        if zone and zone.upper() not in ("UTC", "COORDINATED UNIVERSAL TIME"):
            # A projection we did not ask for. Keep the clock face rather than
            # guess an offset for a Windows zone name.
            logger.debug("Graph returned a non-UTC projection (%s)", zone)
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _graph_all_day_date(value: Any) -> Optional[str]:
    """The calendar date of an all-day bound read through a UTC projection.

    An all-day event is midnight in its own zone. Read through UTC it can land
    a few hours either side of midnight, so round to the nearest one: a
    Helsinki all-day event on the 12th reads as 22:00 on the 11th.
    """
    parsed = _graph_utc(value)
    if parsed is None:
        return None
    if parsed.hour >= 12:
        parsed = parsed + timedelta(days=1)
    return parsed.date().isoformat()


def graph_event_to_google(event: dict[str, Any]) -> dict[str, Any]:
    """Translate a Graph event (or a delta `@removed` stub) to Google's shape."""
    raw_id = str(event.get("id") or "")
    if "@removed" in event:
        return {"id": qualify(OUTLOOK, raw_id), "status": "cancelled"}

    all_day = bool(event.get("isAllDay"))
    if all_day:
        start = {"date": _graph_all_day_date(event.get("start"))}
        end = {"date": _graph_all_day_date(event.get("end"))}
    else:
        start_dt = _graph_utc(event.get("start"))
        end_dt = _graph_utc(event.get("end"))
        start = {"dateTime": start_dt.isoformat(), "timeZone": "UTC"} if start_dt else {}
        end = {"dateTime": end_dt.isoformat(), "timeZone": "UTC"} if end_dt else {}

    result: dict[str, Any] = {
        "id": qualify(OUTLOOK, raw_id),
        "iCalUID": event.get("iCalUId"),
        "summary": event.get("subject"),
        "location": ((event.get("location") or {}).get("displayName")) or None,
        "description": ((event.get("body") or {}).get("content")) or None,
        "start": start,
        "end": end,
        "status": "cancelled" if event.get("isCancelled") else "confirmed",
        "etag": event.get("changeKey") or event.get("@odata.etag"),
        "updated": event.get("lastModifiedDateTime"),
        "htmlLink": event.get("webLink"),
    }
    if event.get("seriesMasterId"):
        result["recurringEventId"] = qualify(OUTLOOK, str(event["seriesMasterId"]))
    if event.get("originalStart"):
        result["originalStartTime"] = {"dateTime": event["originalStart"]}

    response = str(((event.get("responseStatus") or {}).get("response")) or "").lower()
    if response in _RESPONSE_STATUS:
        result["attendees"] = [{"self": True, "responseStatus": _RESPONSE_STATUS[response]}]

    join_url = ((event.get("onlineMeeting") or {}).get("joinUrl")) or event.get("onlineMeetingUrl")
    if join_url:
        result["hangoutLink"] = join_url

    for prop in event.get("singleValueExtendedProperties") or []:
        if isinstance(prop, dict) and str(prop.get("id", "")).lower() == _SELKO_PROPERTY_ID.lower():
            result["extendedProperties"] = {"private": {"selko_event_id": prop.get("value")}}
    return result


def rrule_to_graph_recurrence(rule: str, start_date: date) -> Optional[dict[str, Any]]:
    """Translate the RRULE subset extraction produces into a patternedRecurrence.

    Returns None for anything outside that subset; the caller then writes a
    single occurrence rather than a series Graph would interpret differently.
    """
    body = rule.strip()
    if body.upper().startswith("RRULE:"):
        body = body[6:]
    parts: dict[str, str] = {}
    for chunk in body.split(";"):
        if "=" in chunk:
            key, value = chunk.split("=", 1)
            parts[key.strip().upper()] = value.strip().upper()

    freq = parts.get("FREQ")
    try:
        interval = int(parts.get("INTERVAL", "1"))
    except ValueError:
        return None
    by_day = [d for d in parts.get("BYDAY", "").split(",") if d]

    pattern: dict[str, Any] = {"interval": interval}
    if freq == "DAILY":
        pattern["type"] = "daily"
    elif freq == "WEEKLY":
        days = [_WEEKDAYS.get(d) for d in by_day] or [
            list(_WEEKDAYS.values())[start_date.weekday()]
        ]
        if None in days:
            return None
        pattern.update(type="weekly", daysOfWeek=days, firstDayOfWeek="sunday")
    elif freq == "MONTHLY":
        if by_day:
            match = re.fullmatch(r"([+-]?\d)?(MO|TU|WE|TH|FR|SA|SU)", by_day[0])
            if not match or len(by_day) != 1:
                return None
            ordinal = int(match.group(1) or parts.get("BYSETPOS", "0") or 0)
            if ordinal not in _ORDINALS:
                return None
            pattern.update(
                type="relativeMonthly",
                daysOfWeek=[_WEEKDAYS[match.group(2)]],
                index=_ORDINALS[ordinal],
            )
        else:
            try:
                day_of_month = int(parts.get("BYMONTHDAY", start_date.day))
            except ValueError:
                return None
            if day_of_month < 1:
                return None
            pattern.update(type="absoluteMonthly", dayOfMonth=day_of_month)
    elif freq == "YEARLY":
        pattern.update(
            type="absoluteYearly",
            dayOfMonth=start_date.day,
            month=int(parts.get("BYMONTH", start_date.month)),
        )
    else:
        return None

    recurrence_range: dict[str, Any] = {"startDate": start_date.isoformat()}
    if "COUNT" in parts:
        try:
            recurrence_range.update(type="numbered", numberOfOccurrences=int(parts["COUNT"]))
        except ValueError:
            return None
    elif "UNTIL" in parts:
        until = re.match(r"(\d{4})(\d{2})(\d{2})", parts["UNTIL"])
        if not until:
            return None
        recurrence_range.update(type="endDate", endDate="-".join(until.groups()))
    else:
        recurrence_range["type"] = "noEnd"
    return {"pattern": pattern, "range": recurrence_range}


def _graph_bound(bound: dict[str, Any], *, all_day: bool, default_zone: str) -> dict[str, str]:
    """Translate a Google start/end block into a Graph dateTimeTimeZone."""
    if all_day:
        return {"dateTime": f"{bound['date']}T00:00:00", "timeZone": default_zone}
    value = str(bound.get("dateTime") or "")
    zone = bound.get("timeZone") or default_zone
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return {"dateTime": value, "timeZone": zone}
    if parsed.tzinfo is not None:
        # Graph wants the wall clock in the named zone, not an offset.
        parsed = parsed.astimezone(timezone.utc)
        return {"dateTime": parsed.replace(tzinfo=None).isoformat(), "timeZone": "UTC"}
    return {"dateTime": parsed.isoformat(), "timeZone": zone}


def google_body_to_graph(
    body: dict[str, Any], *, default_zone: str = "UTC", include_selko_id: bool = True
) -> dict[str, Any]:
    """Translate the Google-shaped body `calendars.py` builds into a Graph event.

    `default_zone` anchors all-day events, whose Google form is a bare date:
    Graph requires an all-day event to run midnight to midnight in a zone.
    """
    start = body.get("start") or {}
    end = body.get("end") or {}
    all_day = "date" in start and "dateTime" not in start
    zone = start.get("timeZone") or end.get("timeZone") or default_zone

    graph: dict[str, Any] = {
        "subject": body.get("summary") or "",
        "body": {"contentType": "text", "content": body.get("description") or ""},
        "location": {"displayName": body.get("location") or ""},
        "isAllDay": all_day,
    }
    if start:
        graph["start"] = _graph_bound(start, all_day=all_day, default_zone=zone)
    if end:
        graph["end"] = _graph_bound(end, all_day=all_day, default_zone=zone)

    for rule in body.get("recurrence") or []:
        try:
            anchor = date.fromisoformat(
                (start.get("date") or str(graph.get("start", {}).get("dateTime", "")))[:10]
            )
        except ValueError:
            break
        recurrence = rrule_to_graph_recurrence(str(rule), anchor)
        if recurrence:
            graph["recurrence"] = recurrence
        else:
            logger.warning("Recurrence rule not representable in Outlook; writing one occurrence")
        break

    if body.get("attendees"):
        graph["attendees"] = [
            {"emailAddress": {"address": attendee["email"]}, "type": "required"}
            for attendee in body["attendees"]
            if attendee.get("email")
        ]

    selko_id = ((body.get("extendedProperties") or {}).get("private") or {}).get("selko_event_id")
    if include_selko_id and selko_id:
        graph["singleValueExtendedProperties"] = [{"id": _SELKO_PROPERTY_ID, "value": str(selko_id)}]
    return graph


def _calendar_path(calendar_id: str) -> str:
    """Graph path of a calendar; `primary` is the user's default calendar."""
    if not calendar_id or calendar_id == "primary":
        return f"{GRAPH}/me/calendar"
    return f"{GRAPH}/me/calendars/{quote(unqualify(calendar_id), safe='')}"


def _event_path(event_id: str) -> str:
    return f"{GRAPH}/me/events/{quote(unqualify(event_id), safe='')}"


def _graph_time(value: str) -> str:
    """Graph wants calendarView bounds as UTC without an offset suffix."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class OutlookCalendarAdapter:
    """Outlook Calendar over Microsoft Graph, translated to Google's shape."""

    provider = OUTLOOK

    def __init__(
        self,
        access_token: str,
        *,
        client: Client | None = None,
        config: Any = None,
        integration_id: str | None = None,
        time_zone: str = "UTC",
    ) -> None:
        self.access_token = access_token
        self.client = client
        self.config = config
        self.integration_id = integration_id
        self.time_zone = time_zone

    def _request(
        self,
        method: str,
        url: str,
        *,
        operation: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
        prefer: str | None = _OUTLOOK_READ_PREFER,
    ) -> dict[str, Any]:
        from selko.services.msgraph import request_json

        return request_json(
            self.access_token,
            url,
            method=method,
            params=params,
            json_body=json_body,
            prefer=prefer,
            client=self.client,
            config=self.config,
            integration_id=self.integration_id,
            operation=operation,
            graph_surface="outlook_calendar",
        )

    def _translate_404(self, exc: Exception, event_id: str) -> None:
        if getattr(exc, "status_code", None) == 404:
            raise CalendarEventNotFound(event_id) from exc

    def list_calendars(self):
        calendars: list[dict[str, Any]] = []
        url: Optional[str] = f"{GRAPH}/me/calendars"
        params: Optional[dict[str, Any]] = {"$top": "100"}
        while url:
            page = self._request(
                "GET", url, params=params, prefer='IdType="ImmutableId"',
                operation="GET /me/calendars",
            )
            params = None
            for cal in page.get("value", []):
                if not cal.get("id"):
                    continue
                calendars.append({
                    "id": qualify(OUTLOOK, str(cal["id"])),
                    "summary": cal.get("name") or cal["id"],
                    "primary": bool(cal.get("isDefaultCalendar")),
                    "can_write": bool(cal.get("canEdit", True)),
                })
            url = page.get("@odata.nextLink")
        return calendars

    def list_events(self, calendar_id, *, time_min, time_max, time_zone, max_results=50):
        del time_zone  # Responses are projected into UTC; see _OUTLOOK_READ_PREFER.
        page = self._request(
            "GET",
            f"{_calendar_path(calendar_id)}/calendarView",
            params={
                "startDateTime": _graph_time(time_min),
                "endDateTime": _graph_time(time_max),
                "$top": str(max_results),
                "$expand": f"singleValueExtendedProperties($filter=id eq '{_SELKO_PROPERTY_ID}')",
            },
            operation="GET /me/calendars/{calendar-id}/calendarView",
        )
        return [graph_event_to_google(event) for event in page.get("value", [])]

    def get_event(self, calendar_id, event_id):
        del calendar_id  # Graph addresses events directly.
        try:
            event = self._request(
                "GET",
                _event_path(event_id),
                params={"$expand": f"singleValueExtendedProperties($filter=id eq '{_SELKO_PROPERTY_ID}')"},
                operation="GET /me/events/{event-id}",
            )
        except Exception as exc:
            self._translate_404(exc, event_id)
            raise
        return graph_event_to_google(event)

    def _write(self, method: str, url: str, body: dict[str, Any], operation: str) -> dict[str, Any]:
        """POST/PATCH an event, falling back to UTC if a zone is refused.

        Graph accepts IANA zone names for event bounds, which keeps recurring
        series on local wall-clock time across DST. If a tenant refuses one,
        the same instant in UTC is always accepted.
        """
        graph = google_body_to_graph(body, default_zone=self.time_zone)
        try:
            return self._request(method, url, json_body=graph, operation=operation)
        except Exception as exc:
            code = str(getattr(exc, "graph_error_code", "") or "")
            if getattr(exc, "status_code", None) != 400 or "TimeZone" not in code:
                raise
            logger.info("Graph refused an event time zone; retrying in UTC")
            for key in ("start", "end"):
                bound = body.get(key) or {}
                if bound.get("dateTime") and graph.get(key):
                    from selko.services.civil_time import ensure_aware

                    aware = ensure_aware(bound["dateTime"], bound.get("timeZone"))
                    if aware is not None:
                        graph[key] = {
                            "dateTime": aware.astimezone(timezone.utc).replace(tzinfo=None).isoformat(),
                            "timeZone": "UTC",
                        }
            return self._request(method, url, json_body=graph, operation=operation)

    def insert_event(self, calendar_id, body):
        created = self._write(
            "POST", f"{_calendar_path(calendar_id)}/events", body,
            "POST /me/calendars/{calendar-id}/events",
        )
        return graph_event_to_google(created)

    def update_event(self, calendar_id, event_id, body):
        del calendar_id
        try:
            updated = self._write("PATCH", _event_path(event_id), body, "PATCH /me/events/{event-id}")
        except Exception as exc:
            self._translate_404(exc, event_id)
            raise
        return graph_event_to_google(updated)

    def delete_event(self, calendar_id, event_id):
        del calendar_id
        try:
            self._request("DELETE", _event_path(event_id), prefer=None, operation="DELETE /me/events/{event-id}")
        except Exception as exc:
            self._translate_404(exc, event_id)
            raise

    def find_event_by_selko_id(self, calendar_id, selko_event_id):
        page = self._request(
            "GET",
            f"{_calendar_path(calendar_id)}/events",
            params={
                "$filter": (
                    f"singleValueExtendedProperties/Any(ep: ep/id eq '{_SELKO_PROPERTY_ID}' "
                    f"and ep/value eq '{str(selko_event_id).replace(chr(39), '')}')"
                ),
                "$select": "id",
                "$top": "2",
            },
            operation="GET /me/calendars/{calendar-id}/events?selko",
        )
        items = page.get("value", [])
        if len(items) > 1:
            logger.warning("Found multiple Outlook events for Selko event %s", selko_event_id)
        for item in items:
            if item.get("id"):
                return qualify(OUTLOOK, str(item["id"]))
        return None

    def mirror_page(self, calendar_id, *, sync_token, window, page_token=None):
        """One page of calendarView delta, in the shape Google's list returns.

        The page token and the sync token are both Graph links; the window is
        sent only on the first request, exactly as with Google.
        """
        if page_token:
            url, params = page_token, None
        elif sync_token:
            url, params = sync_token, None
        else:
            url = f"{_calendar_path(calendar_id)}/calendarView/delta"
            params = {
                "startDateTime": _graph_time(window[0].isoformat()),
                "endDateTime": _graph_time(window[1].isoformat()),
            }
        try:
            page = self._request(
                "GET", url, params=params,
                prefer=f"{_OUTLOOK_READ_PREFER}, odata.maxpagesize=100",
                operation="GET /me/calendars/{calendar-id}/calendarView/delta",
            )
        except Exception as exc:
            if getattr(exc, "status_code", None) == 410:
                raise CalendarSyncTokenExpired() from exc
            raise
        return {
            "items": [graph_event_to_google(event) for event in page.get("value", [])],
            "nextPageToken": page.get("@odata.nextLink"),
            "nextSyncToken": page.get("@odata.deltaLink"),
        }
