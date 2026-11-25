"""Outlook Calendar as a second calendar provider.

Covers the adapter translation in both directions, provider routing in the
worker-owned writer, Graph failure classification, the Outlook OAuth scope
upgrade, and the wiring that makes each provider's circuit independent.
"""

from datetime import date, datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from selko.services import calendar_providers as providers
from selko.services.calendar_providers import (
    CalendarEventNotFound,
    CalendarSyncTokenExpired,
    OutlookCalendarAdapter,
    google_body_to_graph,
    graph_event_to_google,
    rrule_to_graph_recurrence,
)
from selko.services.msgraph import GraphRequestError


# --- ids and writability -------------------------------------------------------


def test_outlook_ids_are_qualified_and_google_ids_stay_bare():
    assert providers.qualify("outlook", "AAMk=") == "outlook:AAMk="
    assert providers.qualify("outlook", "outlook:AAMk=") == "outlook:AAMk="
    assert providers.qualify("google_calendar", "abc123") == "abc123"
    assert providers.unqualify("outlook:AAMk=") == "AAMk="
    assert providers.provider_of_id("outlook:AAMk=") == "outlook"
    # Every id stored before this change is a bare Google id.
    assert providers.provider_of_id("abc123") == "google_calendar"
    assert providers.provider_of_id("me@group.calendar.google.com") == "google_calendar"
    assert providers.provider_of_id(None) == "google_calendar"


@pytest.mark.parametrize("scopes,expected", [
    (["Mail.Read", "User.Read"], False),
    (["Mail.Read", "Calendars.ReadWrite"], True),
    (["https://graph.microsoft.com/Calendars.ReadWrite"], True),
    (["calendars.readwrite"], True),
    (["Calendars.Read"], False),
    (None, False),
])
def test_only_a_calendar_grant_makes_outlook_writable(scopes, expected):
    assert providers.outlook_scopes_allow_calendar(scopes) is expected


def test_a_mail_only_outlook_row_is_not_a_writable_calendar():
    rows = [{"provider": "outlook", "status": "active", "scopes": ["Mail.Read"]}]
    assert providers.writable_providers(rows) == []


def test_google_is_preferred_when_no_target_is_chosen():
    rows = [
        {"provider": "outlook", "status": "active", "scopes": ["Calendars.ReadWrite"]},
        {"provider": "google_calendar", "status": "active", "scopes": []},
    ]
    assert providers.writable_providers(rows) == ["google_calendar", "outlook"]
    assert providers.resolve_target_provider(None, rows) == "google_calendar"
    assert providers.resolve_target_provider("outlook:cal", rows) == "outlook"
    assert providers.resolve_target_provider(None, rows[:1]) == "outlook"


# --- Graph -> Google shape -----------------------------------------------------


def test_a_timed_graph_event_reads_as_a_google_event():
    event = graph_event_to_google({
        "id": "AAMk1",
        "iCalUId": "uid-1",
        "subject": "Dentist",
        "location": {"displayName": "Main St"},
        "body": {"contentType": "text", "content": "Bring card"},
        "start": {"dateTime": "2026-11-03T15:00:00.0000000", "timeZone": "UTC"},
        "end": {"dateTime": "2026-11-03T16:00:00.0000000", "timeZone": "UTC"},
        "changeKey": "ck-1",
        "lastModifiedDateTime": "2026-11-01T00:00:00Z",
        "webLink": "https://outlook.office.com/x",
        "responseStatus": {"response": "tentativelyAccepted"},
        "onlineMeeting": {"joinUrl": "https://teams.microsoft.com/l/meet"},
        "singleValueExtendedProperties": [
            {"id": providers._SELKO_PROPERTY_ID, "value": "selko-1"},
        ],
    })
    assert event["id"] == "outlook:AAMk1"
    assert event["iCalUID"] == "uid-1"
    assert event["summary"] == "Dentist"
    assert event["location"] == "Main St"
    assert event["description"] == "Bring card"
    assert event["start"] == {"dateTime": "2026-11-03T15:00:00+00:00", "timeZone": "UTC"}
    assert event["etag"] == "ck-1"
    assert event["attendees"] == [{"self": True, "responseStatus": "tentative"}]
    assert event["hangoutLink"] == "https://teams.microsoft.com/l/meet"
    assert event["extendedProperties"]["private"]["selko_event_id"] == "selko-1"


def test_an_all_day_event_east_of_utc_keeps_its_date():
    """Read through UTC, Helsinki's midnight on the 12th is 22:00 on the 11th."""
    event = graph_event_to_google({
        "id": "x",
        "isAllDay": True,
        "start": {"dateTime": "2026-11-11T22:00:00.0000000", "timeZone": "UTC"},
        "end": {"dateTime": "2026-11-12T22:00:00.0000000", "timeZone": "UTC"},
    })
    assert event["start"] == {"date": "2026-11-12"}
    assert event["end"] == {"date": "2026-11-13"}


def test_an_all_day_event_west_of_utc_keeps_its_date():
    event = graph_event_to_google({
        "id": "x",
        "isAllDay": True,
        "start": {"dateTime": "2026-11-12T08:00:00", "timeZone": "UTC"},
        "end": {"dateTime": "2026-11-13T08:00:00", "timeZone": "UTC"},
    })
    assert event["start"] == {"date": "2026-11-12"}


def test_a_removed_delta_item_is_a_cancelled_tombstone():
    event = graph_event_to_google({"id": "gone", "@removed": {"reason": "deleted"}})
    assert event == {"id": "outlook:gone", "status": "cancelled"}


def test_a_cancelled_occurrence_reads_as_cancelled():
    event = graph_event_to_google({"id": "x", "isCancelled": True, "seriesMasterId": "m"})
    assert event["status"] == "cancelled"
    assert event["recurringEventId"] == "outlook:m"


# --- Google shape -> Graph -----------------------------------------------------


def test_a_timed_body_keeps_its_wall_clock_and_zone():
    graph = google_body_to_graph({
        "summary": "Standup",
        "description": "Daily",
        "location": "Room 1",
        "start": {"dateTime": "2026-11-03T09:00:00", "timeZone": "Europe/Helsinki"},
        "end": {"dateTime": "2026-11-03T09:15:00", "timeZone": "Europe/Helsinki"},
        "attendees": [{"email": "spouse@example.com"}],
        "extendedProperties": {"private": {"selko_event_id": "e-1"}},
    })
    assert graph["subject"] == "Standup"
    assert graph["isAllDay"] is False
    assert graph["start"] == {"dateTime": "2026-11-03T09:00:00", "timeZone": "Europe/Helsinki"}
    assert graph["attendees"] == [
        {"emailAddress": {"address": "spouse@example.com"}, "type": "required"}
    ]
    assert graph["singleValueExtendedProperties"] == [
        {"id": providers._SELKO_PROPERTY_ID, "value": "e-1"}
    ]


def test_an_all_day_body_runs_midnight_to_midnight_in_the_users_zone():
    graph = google_body_to_graph(
        {"summary": "Holiday", "start": {"date": "2026-12-24"}, "end": {"date": "2026-12-26"}},
        default_zone="America/New_York",
    )
    assert graph["isAllDay"] is True
    assert graph["start"] == {"dateTime": "2026-12-24T00:00:00", "timeZone": "America/New_York"}
    assert graph["end"] == {"dateTime": "2026-12-26T00:00:00", "timeZone": "America/New_York"}


def test_an_offset_datetime_is_sent_as_utc_rather_than_misread():
    graph = google_body_to_graph({
        "start": {"dateTime": "2026-11-03T09:00:00+02:00"},
        "end": {"dateTime": "2026-11-03T10:00:00+02:00"},
    })
    assert graph["start"] == {"dateTime": "2026-11-03T07:00:00", "timeZone": "UTC"}


@pytest.mark.parametrize("rule,expected", [
    ("RRULE:FREQ=WEEKLY;BYDAY=MO,WE", {
        "pattern": {"interval": 1, "type": "weekly", "daysOfWeek": ["monday", "wednesday"], "firstDayOfWeek": "sunday"},
        "range": {"startDate": "2026-11-02", "type": "noEnd"},
    }),
    ("RRULE:FREQ=DAILY;INTERVAL=2;COUNT=5", {
        "pattern": {"interval": 2, "type": "daily"},
        "range": {"startDate": "2026-11-02", "type": "numbered", "numberOfOccurrences": 5},
    }),
    ("RRULE:FREQ=MONTHLY;BYDAY=2TU;UNTIL=20270101T000000Z", {
        "pattern": {"interval": 1, "type": "relativeMonthly", "daysOfWeek": ["tuesday"], "index": "second"},
        "range": {"startDate": "2026-11-02", "type": "endDate", "endDate": "2027-01-01"},
    }),
    ("RRULE:FREQ=YEARLY", {
        "pattern": {"interval": 1, "type": "absoluteYearly", "dayOfMonth": 2, "month": 11},
        "range": {"startDate": "2026-11-02", "type": "noEnd"},
    }),
])
def test_extracted_recurrence_rules_become_patterned_recurrence(rule, expected):
    assert rrule_to_graph_recurrence(rule, date(2026, 11, 2)) == expected


def test_an_unrepresentable_rule_is_refused_rather_than_approximated():
    assert rrule_to_graph_recurrence("RRULE:FREQ=HOURLY", date(2026, 11, 2)) is None
    graph = google_body_to_graph({
        "start": {"date": "2026-11-02"}, "end": {"date": "2026-11-03"},
        "recurrence": ["RRULE:FREQ=MINUTELY"],
    })
    assert "recurrence" not in graph


# --- adapter over Graph --------------------------------------------------------


def _adapter_with(responses):
    calls = []

    def fake_request(token, url, **kwargs):
        calls.append({"url": url, **kwargs})
        result = responses.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    patcher = patch("selko.services.msgraph.request_json", side_effect=fake_request)
    return OutlookCalendarAdapter("token", time_zone="America/New_York"), calls, patcher


def test_insert_posts_to_the_target_calendar_and_returns_a_qualified_id():
    adapter, calls, patcher = _adapter_with([{"id": "NEW1", "subject": "x"}])
    with patcher:
        created = adapter.insert_event("outlook:CAL1", {
            "summary": "x", "start": {"date": "2026-11-02"}, "end": {"date": "2026-11-03"},
        })
    assert created["id"] == "outlook:NEW1"
    assert calls[0]["method"] == "POST"
    assert calls[0]["url"].endswith("/me/calendars/CAL1/events")
    assert calls[0]["graph_surface"] == "outlook_calendar"
    assert calls[0]["json_body"]["start"]["timeZone"] == "America/New_York"


def test_primary_means_the_default_outlook_calendar():
    adapter, calls, patcher = _adapter_with([{"id": "N"}])
    with patcher:
        adapter.insert_event("primary", {"summary": "x"})
    assert calls[0]["url"].endswith("/me/calendar/events")


def test_a_missing_outlook_event_is_not_found():
    adapter, _, patcher = _adapter_with([GraphRequestError(404, "gone")])
    with patcher, pytest.raises(CalendarEventNotFound):
        adapter.get_event("primary", "outlook:E1")


def test_a_refused_time_zone_is_retried_in_utc():
    refused = GraphRequestError(400, "bad zone", graph_error_code="TimeZoneNotSupportedException")
    adapter, calls, patcher = _adapter_with([refused, {"id": "N"}])
    with patcher:
        adapter.insert_event("primary", {
            "summary": "x",
            "start": {"dateTime": "2026-11-03T09:00:00", "timeZone": "Europe/Helsinki"},
            "end": {"dateTime": "2026-11-03T10:00:00", "timeZone": "Europe/Helsinki"},
        })
    assert calls[1]["json_body"]["start"] == {"dateTime": "2026-11-03T07:00:00", "timeZone": "UTC"}


def test_an_expired_delta_link_asks_for_a_full_resync():
    adapter, _, patcher = _adapter_with([GraphRequestError(410, "SyncStateNotFound")])
    window = (datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2027, 1, 1, tzinfo=timezone.utc))
    with patcher, pytest.raises(CalendarSyncTokenExpired):
        adapter.mirror_page("outlook:CAL", sync_token="https://graph/delta?token", window=window)


def test_a_delta_page_reads_like_a_google_incremental_page():
    adapter, calls, patcher = _adapter_with([{
        "value": [{"id": "E1", "subject": "x"}, {"id": "E2", "@removed": {}}],
        "@odata.deltaLink": "https://graph/delta?$deltatoken=t",
    }])
    window = (datetime(2026, 1, 1, tzinfo=timezone.utc), datetime(2027, 1, 1, tzinfo=timezone.utc))
    with patcher:
        page = adapter.mirror_page("outlook:CAL", sync_token=None, window=window)
    assert [item["id"] for item in page["items"]] == ["outlook:E1", "outlook:E2"]
    assert page["items"][1]["status"] == "cancelled"
    assert page["nextSyncToken"] == "https://graph/delta?$deltatoken=t"
    assert page["nextPageToken"] is None
    assert calls[0]["url"].endswith("/me/calendars/CAL/calendarView/delta")
    assert calls[0]["params"]["startDateTime"] == "2026-01-01T00:00:00Z"


def test_outlook_calendars_are_listed_with_qualified_ids():
    adapter, _, patcher = _adapter_with([{
        "value": [
            {"id": "C1", "name": "Calendar", "isDefaultCalendar": True, "canEdit": True},
            {"id": "C2", "name": "Holidays", "canEdit": False},
        ],
    }])
    with patcher:
        calendars = adapter.list_calendars()
    assert calendars == [
        {"id": "outlook:C1", "summary": "Calendar", "primary": True, "can_write": True},
        {"id": "outlook:C2", "summary": "Holidays", "primary": False, "can_write": False},
    ]


# --- the writer routes by provider ---------------------------------------------
#
# The event, settings and integration rows are real (SQLite `db`/`factory`);
# only the provider adapter (Google/Graph HTTP) is mocked.


def _writer_user(factory, *, target=None, google=True, outlook_scopes=("Mail.Read", "Calendars.ReadWrite")):
    from selko.db import integrations as db_integrations

    user_id = factory.user()
    if google:
        factory.integration(user_id, provider="google_calendar", scopes=["calendar"])
    if outlook_scopes is not None:
        factory.integration(user_id, provider="outlook", scopes=list(outlook_scopes))
    if target is not None:
        db_integrations.upsert_calendar_settings(
            factory.db, user_id, {"target_calendar_id": target, "timezone": "America/New_York"}
        )
    return user_id


def _writer_event(factory, user_id, **extra):
    values = {"title": "x", "review_status": "active"}
    values.update(extra)
    return factory.event(user_id, **values)


def test_a_new_event_is_written_to_the_outlook_target_calendar(db, factory):
    from selko.services import calendars

    user_id = _writer_user(factory, target="outlook:CAL")
    event_id = _writer_event(factory, user_id)
    adapter = MagicMock()
    adapter.find_event_by_selko_id.return_value = None
    adapter.insert_event.return_value = {"id": "outlook:NEW"}

    with patch.object(calendars, "calendar_adapter", return_value=adapter) as build_adapter:
        provider_id = calendars.sync_event_to_calendar(db, user_id, event_id)

    assert provider_id == "outlook:NEW"
    assert build_adapter.call_args.args[2] == "outlook"
    adapter.insert_event.assert_called_once()
    assert adapter.insert_event.call_args.args[0] == "outlook:CAL"


def test_an_event_already_in_google_stays_there_after_switching_to_outlook(db, factory):
    """Updating it in Outlook would orphan the Google copy and duplicate it."""
    from selko.services import calendars

    user_id = _writer_user(factory, target="outlook:CAL")
    event_id = _writer_event(factory, user_id, google_calendar_event_id="g-1")
    adapter = MagicMock()
    adapter.get_event.return_value = {"id": "g-1", "summary": "old"}

    with patch.object(calendars, "calendar_adapter", return_value=adapter) as build_adapter:
        provider_id = calendars.sync_event_to_calendar(
            db, user_id, event_id, provider="outlook"
        )

    assert provider_id == "g-1"
    assert build_adapter.call_args.args[2] == "google_calendar"
    # Google's calendar id is not the Outlook target; it falls back to primary.
    assert adapter.update_event.call_args.args[:2] == ("primary", "g-1")


def test_the_claimed_provider_decides_when_no_target_is_chosen(db, factory):
    from selko.services import calendars

    user_id = _writer_user(factory)
    event_id = _writer_event(factory, user_id)
    adapter = MagicMock()
    adapter.find_event_by_selko_id.return_value = "outlook:FOUND"
    adapter.get_event.return_value = {"id": "outlook:FOUND"}

    with patch.object(calendars, "calendar_adapter", return_value=adapter) as build_adapter:
        provider_id = calendars.sync_event_to_calendar(db, user_id, event_id, provider="outlook")

    # An ambiguous earlier insert is reconciled rather than duplicated.
    assert provider_id == "outlook:FOUND"
    assert build_adapter.call_args.args[2] == "outlook"
    adapter.insert_event.assert_not_called()


def test_with_no_target_and_no_stamp_a_writable_google_wins(db, factory):
    from selko.services import calendars

    user_id = _writer_user(factory)
    event_id = _writer_event(factory, user_id)
    adapter = MagicMock()
    adapter.find_event_by_selko_id.return_value = None
    adapter.insert_event.return_value = {"id": "g-new"}

    with patch.object(calendars, "calendar_adapter", return_value=adapter) as build_adapter:
        calendars.sync_event_to_calendar(db, user_id, event_id)

    assert build_adapter.call_args.args[2] == "google_calendar"


def test_with_no_target_an_outlook_only_user_writes_to_outlook(db, factory):
    from selko.services import calendars

    user_id = _writer_user(factory, google=False)
    event_id = _writer_event(factory, user_id)
    adapter = MagicMock()
    adapter.find_event_by_selko_id.return_value = None
    adapter.insert_event.return_value = {"id": "outlook:N"}

    with patch.object(calendars, "calendar_adapter", return_value=adapter) as build_adapter:
        calendars.sync_event_to_calendar(db, user_id, event_id)

    assert build_adapter.call_args.args[2] == "outlook"


def test_an_outlook_auth_failure_never_expires_the_mail_integration(db, factory):
    """The Outlook row also carries mail; expiring it would stop ingestion."""
    from selko.services import calendars

    user_id = _writer_user(factory, target="outlook:CAL")
    event_id = _writer_event(factory, user_id)
    with (
        patch.object(
            calendars, "calendar_adapter",
            side_effect=calendars.CalendarAuthRequiredError("no grant", provider="outlook"),
        ),
        patch.object(calendars, "update_integration_status") as update_status,
        pytest.raises(calendars.CalendarsError) as raised,
    ):
        calendars.sync_event_to_calendar(db, user_id, event_id)

    update_status.assert_not_called()
    assert raised.value.classification.code == "oauth_required"
    assert "Outlook Calendar" in raised.value.classification.user_message
    statuses = {r["provider"]: r["status"] for r in db.query(
        "SELECT provider, status FROM integrations WHERE user_id = ?", (user_id,))}
    assert statuses["outlook"] == "active"


def test_cancellation_goes_to_the_calendar_the_event_lives_in(db, factory):
    from selko.services import calendars

    user_id = _writer_user(factory, target="g-cal")
    event_id = _writer_event(factory, user_id, title="Party", google_calendar_event_id="outlook:E")
    adapter = MagicMock()
    adapter.get_event.return_value = {"id": "outlook:E", "summary": "Party"}
    with patch.object(calendars, "calendar_adapter", return_value=adapter) as build_adapter:
        calendars.cancel_event_to_calendar(db, user_id, event_id, delete_remote=True)

    assert build_adapter.call_args.args[2] == "outlook"
    adapter.delete_event.assert_called_once_with("primary", "outlook:E")


def test_an_outlook_adapter_requires_a_calendar_grant(db, factory):
    from selko.services import calendars

    user_id = _writer_user(factory, outlook_scopes=("Mail.Read",))
    with (
        patch(
            "selko.services.integrations.get_provider_integration",
            return_value={"id": "i", "status": "active", "scopes": ["Mail.Read"]},
        ),
        patch("selko.config.load_config", return_value=MagicMock()),
        pytest.raises(calendars.CalendarAuthRequiredError) as raised,
    ):
        calendars.calendar_adapter(db, user_id, "outlook")
    assert raised.value.provider == "outlook"


def test_calendars_from_both_providers_are_listed_together(db, factory):
    from selko.services import calendars

    user_id = _writer_user(factory, target="outlook:C1", outlook_scopes=("Calendars.ReadWrite",))
    listed = {
        "google_calendar": [{"id": "me@gmail.com", "summary": "Me", "primary": True, "can_write": True},
                            {"id": "holidays", "summary": "Holidays", "primary": False, "can_write": False}],
        "outlook": [{"id": "outlook:C1", "summary": "Calendar", "primary": True, "can_write": True}],
    }
    with patch.object(calendars, "list_provider_calendars", side_effect=lambda c, u, p: listed[p]):
        result = calendars.list_calendars(db, user_id)

    assert [(c["id"], c["provider"], c["is_selected"]) for c in result] == [
        ("me@gmail.com", "google_calendar", False),
        ("outlook:C1", "outlook", True),
    ]


def test_a_mail_only_outlook_grant_is_not_listed(db, factory):
    from selko.services import calendars

    user_id = _writer_user(factory, outlook_scopes=("Mail.Read",))
    seen: list[str] = []

    def fake_list(client, uid, provider):
        seen.append(provider)
        return []

    with patch.object(calendars, "list_provider_calendars", side_effect=fake_list):
        calendars.list_calendars(db, user_id)

    assert seen == ["google_calendar"]


# --- failure classification ----------------------------------------------------


@pytest.mark.parametrize("status,code,retryable,circuit", [
    (401, "oauth_required", False, False),
    (403, "oauth_scope_required", False, False),
    (429, "rate_limited", True, True),
    (503, "provider_transient", True, True),
    (400, "invalid_event", True, False),
])
def test_graph_failures_are_classified(status, code, retryable, circuit):
    from selko.services.calendars import classify_calendar_error

    result = classify_calendar_error(GraphRequestError(status, "x"))
    assert (result.code, result.retryable, result.counts_toward_circuit_breaker) == (
        code, retryable, circuit,
    )
    assert "Outlook" in result.user_message


# --- OAuth ---------------------------------------------------------------------


def test_new_outlook_consent_requests_calendar_permission():
    from selko.services import outlook

    assert "Calendars.ReadWrite" in outlook.SCOPES
    with patch.object(outlook, "_msal_app") as msal_app:
        outlook.build_auth_url(MagicMock(), "state", "https://x/cb")
    assert "Calendars.ReadWrite" in msal_app.return_value.get_authorization_request_url.call_args.kwargs["scopes"]


def test_a_mail_only_grant_is_refreshed_without_asking_for_calendar():
    """Asking a mail-only grant for more fails the refresh and expires mail."""
    from selko.services import outlook

    assert outlook.refresh_scopes(["Mail.Read", "User.Read"]) == outlook.MAIL_SCOPES
    assert outlook.refresh_scopes(["Mail.Read", "Calendars.ReadWrite"]) == outlook.SCOPES


def test_refresh_uses_the_stored_grant():
    from selko.services import outlook

    row = {
        "status": "active", "access_token": "a", "refresh_token": "r",
        "token_expiry": "2000-01-01T00:00:00Z", "scopes": ["Mail.Read", "User.Read"],
    }
    with (
        patch.object(outlook, "get_provider_integration", return_value=row),
        patch.object(outlook, "_msal_app") as msal_app,
        patch.object(outlook, "update_provider_tokens"),
    ):
        msal_app.return_value.acquire_token_by_refresh_token.return_value = {
            "access_token": "new", "expires_in": 3600,
        }
        outlook.get_access_token(MagicMock(), MagicMock(), "u-1")
    assert msal_app.return_value.acquire_token_by_refresh_token.call_args.kwargs["scopes"] == outlook.MAIL_SCOPES


# --- transport -----------------------------------------------------------------


def test_a_post_is_not_retried_after_an_ambiguous_server_error():
    """A 5xx leaves it unknown whether Graph created the event."""
    from selko.services import msgraph

    response = MagicMock(status_code=503, headers={}, content=b"{}")
    response.json.return_value = {"error": {"code": "ServiceUnavailable"}}
    with (
        patch.object(msgraph.requests, "request", return_value=response) as send,
        pytest.raises(GraphRequestError),
    ):
        msgraph.request_json("t", "https://graph/me/events", method="POST", json_body={}, operation="POST x", sleep=lambda _s: None)
    assert send.call_count == 1


def test_a_delete_answering_204_is_a_success():
    from selko.services import msgraph

    response = MagicMock(status_code=204, headers={}, content=b"")
    with patch.object(msgraph.requests, "request", return_value=response):
        assert msgraph.request_json("t", "https://graph/me/events/x", method="DELETE", operation="DELETE x") == {}


def test_calendar_failures_are_ledgered_under_their_own_surface(db, factory):
    from selko.services import msgraph

    integration_id = factory.integration(factory.user(), provider="outlook")
    msgraph.record_graph_failure(
        db, None, integration_id=integration_id, operation="PATCH /me/events/{event-id}",
        url="https://graph.microsoft.com/v1.0/me/events/SECRET-ID", error=GraphRequestError(400, "x"),
        http_method="PATCH", graph_surface="outlook_calendar",
    )
    [payload] = db.query("SELECT graph_surface, http_method, safe_url_template FROM graph_api_failures")
    assert payload["graph_surface"] == "outlook_calendar"
    assert payload["http_method"] == "PATCH"
    assert "SECRET-ID" not in payload["safe_url_template"]


# --- wiring --------------------------------------------------------------------


async def test_an_open_outlook_circuit_does_not_stop_google_claims():
    """Each provider has its own circuit; the claim receives only closed ones."""
    from selko.services.circuit_breaker import circuit_breaker
    from selko.workers import pool as pool_module

    worker_pool = pool_module.WorkerPool.__new__(pool_module.WorkerPool)
    worker_pool.config = MagicMock(llm_claim_lease_seconds=60, recovery_refresh_interval_seconds=0)
    worker_pool.pg_pool = MagicMock()
    worker_pool._client = MagicMock()
    import asyncio

    worker_pool._calendar_semaphore = asyncio.Semaphore(1)
    worker_pool._llm_semaphore = asyncio.Semaphore(0)
    worker_pool._process_integration_recovery = MagicMock(return_value=asyncio.sleep(0, result=False))

    with (
        patch.object(circuit_breaker, "is_available", side_effect=lambda key: key != "outlook_calendar"),
        patch.object(pool_module, "claim_approved_event_for_sync", return_value=None) as claim,
    ):
        await worker_pool._process_any_work("w-1")

    assert claim.call_args.kwargs["providers"] == ["google_calendar"]


async def test_the_worker_hands_the_stamped_provider_to_the_writer(db):
    from selko.workers import calendar_sync

    with patch.object(calendar_sync, "sync_event_to_calendar", return_value="outlook:N") as sync:
        result = await calendar_sync.sync_event(
            db, MagicMock(),
            {"id": "e", "user_id": "u", "calendar_work_item_provider": "outlook"},
        )
    assert result == "outlook:N"
    assert sync.call_args.args[0] is db
    assert sync.call_args.kwargs["provider"] == "outlook"


async def test_the_claim_passes_providers_to_the_rpc(db, factory):
    """The worker's open circuits reach the claim: only an allowed provider's item is taken."""
    from selko.db import calendar_work as db_calendar_work
    from selko.services.events import claim_approved_event_for_sync

    google_user, outlook_user = factory.user(), factory.user()
    factory.integration(google_user, provider="google_calendar", scopes=["calendar"])
    factory.integration(outlook_user, provider="outlook",
                        scopes=["Mail.Read", "User.Read", "Calendars.ReadWrite"])
    google_event = factory.event(google_user, review_status="active", google_calendar_event_id="g-1")
    outlook_event = factory.event(outlook_user, review_status="active",
                                  google_calendar_event_id="outlook:E1")
    for user, event in ((google_user, google_event), (outlook_user, outlook_event)):
        db_calendar_work.enqueue_calendar_work(db, user, event, "upsert", {"title": "Event"})

    claimed = await claim_approved_event_for_sync(db, "w", 60, providers=["outlook"])

    assert claimed["id"] == outlook_event
    assert claimed["calendar_work_item_provider"] == "outlook"
    assert claimed["calendar_work_lease"].worker_id == "w"
    assert await claim_approved_event_for_sync(db, "w", 60, providers=["outlook"]) is None, (
        "the Google item stays queued while its circuit is open"
    )


def test_the_mirror_loop_includes_calendar_capable_outlook_rows():
    import inspect

    from selko.workers.ingestion_runtime import IngestionRuntime

    loop = inspect.getsource(IngestionRuntime._calendar_mirror_floor)
    # The row set (google_calendar + outlook, active) is selko.db.email_sync's
    # active_calendar_integrations, tested in tests/db/test_email_sync.py.
    assert "active_calendar_integrations" in loop and "outlook_scopes_allow_calendar" in loop
    assert 'row.get("provider")' in loop
