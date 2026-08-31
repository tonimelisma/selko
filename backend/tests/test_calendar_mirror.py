"""Contracts for the calendar mirror (I2 of event-identity-reach)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

from selko.services.calendar_mirror import (
    WINDOW_AHEAD,
    WINDOW_BEHIND,
    entry_row,
    fetch_page,
    rolling_window,
)


def _entry(**overrides):
    base = {
        "id": "evt-1",
        "iCalUID": "uid-1@example.com",
        "summary": "Standup",
        "status": "confirmed",
        "etag": '"123"',
        "updated": "2026-08-30T10:00:00Z",
        "start": {"dateTime": "2026-09-01T09:00:00Z", "timeZone": "America/Los_Angeles"},
        "end": {"dateTime": "2026-09-01T09:30:00Z"},
    }
    base.update(overrides)
    return base


def test_entry_row_captures_identity_and_shape():
    row = entry_row(_entry(), user_id="u1", integration_id="i1", calendar_id="primary")
    assert row["ical_uid"] == "uid-1@example.com"
    assert row["provider_event_id"] == "evt-1"
    assert row["start_at"] == "2026-09-01T09:00:00Z"
    assert row["all_day"] is False
    assert row["deleted_at"] is None


def test_all_day_entries_keep_a_usable_timestamp():
    """A date-only bound must still land in a timestamptz column."""
    row = entry_row(
        _entry(start={"date": "2026-09-01"}, end={"date": "2026-09-02"}),
        user_id="u1", integration_id="i1", calendar_id="primary",
    )
    assert row["all_day"] is True
    assert row["start_at"].startswith("2026-09-01T00:00:00")


def test_cancelled_entries_are_tombstoned_not_dropped():
    """A vanished entry is the signal that the user removed something.

    Deleting the row would discard that, and undo still needs the history.
    """
    row = entry_row(
        _entry(status="cancelled"), user_id="u1", integration_id="i1", calendar_id="primary"
    )
    assert row["deleted_at"] is not None
    assert row["status"] == "cancelled"


def test_selko_created_entries_are_distinguished_from_the_user_s_own():
    ours = entry_row(
        _entry(extendedProperties={"private": {"selko_event_id": "abc"}}),
        user_id="u1", integration_id="i1", calendar_id="primary",
    )
    theirs = entry_row(_entry(), user_id="u1", integration_id="i1", calendar_id="primary")
    assert ours["origin"] == "selko_created"
    assert theirs["origin"] == "external"


def test_recurring_occurrence_records_its_original_start():
    row = entry_row(
        _entry(
            recurringEventId="series-1",
            originalStartTime={"dateTime": "2026-09-01T09:00:00Z"},
        ),
        user_id="u1", integration_id="i1", calendar_id="primary",
    )
    assert row["recurring_event_id"] == "series-1"
    assert row["original_start"] == "2026-09-01T09:00:00Z"


def test_self_response_is_extracted_from_attendees():
    row = entry_row(
        _entry(attendees=[
            {"email": "other@example.com", "responseStatus": "accepted"},
            {"email": "me@example.com", "self": True, "responseStatus": "declined"},
        ]),
        user_id="u1", integration_id="i1", calendar_id="primary",
    )
    assert row["self_response"] == "declined"


def test_a_sync_token_replaces_the_time_window():
    """timeMin/timeMax may not be combined with syncToken.

    Google keeps the window from the request that issued the token; sending both
    is an error, and sending the window every time would defeat the incremental
    read that keeps this inside the egress rule.
    """
    service = MagicMock()
    window = rolling_window()

    fetch_page(service, "primary", sync_token="tok", window=window)
    params = service.events().list.call_args.kwargs
    assert params["syncToken"] == "tok"
    assert "timeMin" not in params and "timeMax" not in params

    service.reset_mock()
    fetch_page(service, "primary", sync_token=None, window=window)
    params = service.events().list.call_args.kwargs
    assert "syncToken" not in params
    assert params["timeMin"] and params["timeMax"]


def test_deleted_entries_are_requested_so_removals_are_visible():
    service = MagicMock()
    fetch_page(service, "primary", sync_token="tok", window=rolling_window())
    assert service.events().list.call_args.kwargs["showDeleted"] is True


def test_the_window_is_bounded():
    """The rolling window is what bounds cost; assert it actually bounds."""
    start, end = rolling_window(datetime(2026, 8, 30, tzinfo=timezone.utc))
    assert end - start == WINDOW_BEHIND + WINDOW_AHEAD
    assert end - start < timedelta(days=500)


def test_the_runtime_actually_runs_the_mirror():
    """A module nobody calls has not shipped.

    Direct-pg increments 3-5 and workers/event_resolution.py all merged with no
    call sites and a green suite. The reachability test catches an unimported
    module; this asserts the loop is registered as a runtime task, which is what
    makes the mirror actually run in production.
    """
    import inspect

    from selko.workers.ingestion_runtime import IngestionRuntime

    source = inspect.getsource(IngestionRuntime.start)
    assert "calendar-mirror" in source, "mirror loop is not registered as a task"

    loop = inspect.getsource(IngestionRuntime._calendar_mirror_floor)
    assert "sync_all_calendars" in loop, (
        "the loop must mirror every calendar, not only the write target: "
        "invitations arrive on whichever calendar their address belongs to"
    )
    assert "google_calendar" in loop and "active" in loop, (
        "the loop must only mirror active google_calendar integrations"
    )


def test_entries_are_indexed_even_though_upsert_returns_nothing():
    """The mirror must index what it stores, not what the upsert echoes back.

    Production mirrored 1595 calendar entries carrying 1595 iCalUIDs and wrote
    zero identity hints, because the code indexed `upsert(...).execute().data`
    and PostgREST returned no representation. The mirror existed and the index
    it exists to populate stayed empty.

    Every other test passed: they cover the row mapping and the runtime wiring,
    and neither can see what the database hands back.
    """
    from selko.services.calendar_mirror import _reload_stored, _write_entry_hints

    client = MagicMock()
    upserted: list[dict] = []

    def table(name):
        handle = MagicMock()
        if name == "calendar_entries":
            # The shape that caused the bug: an upsert that echoes nothing.
            handle.upsert.return_value.execute.return_value.data = None
            handle.select.return_value.eq.return_value.in_.return_value.execute.return_value.data = [
                {"id": "entry-1", "ical_uid": "uid-1@example.com", "original_start": "", "deleted_at": None},
            ]
        elif name == "event_identity_hints":
            handle.upsert.side_effect = lambda payload, **kw: (
                upserted.extend(payload), MagicMock()
            )[1]
        return handle

    client.table.side_effect = table

    stored = _reload_stored(client, "user-1", [{"provider_event_id": "evt-1"}])
    assert stored, "entries must be read back when the upsert returns nothing"

    _write_entry_hints(client, "user-1", stored)
    assert upserted, "a mirrored entry with an iCalUID must produce a hint"
    assert upserted[0]["calendar_entry_id"] == "entry-1"
    assert upserted[0]["kind"] == "ical_uid"
    assert upserted[0]["event_id"] is None


def test_entries_mirrored_before_indexing_worked_are_repaired():
    """Indexing must be a repair, not a side effect of writing.

    Once a sync token exists an unchanged calendar returns no rows, so nothing
    is upserted and nothing is indexed. Production sat at 1595 mirrored entries
    and 0 hints because indexing only ran for rows a pass happened to write --
    every entry mirrored before the fix was unreachable for good.
    """
    from selko.services.calendar_mirror import _index_unhinted_entries

    client = MagicMock()
    written: list[dict] = []

    def table(name):
        handle = MagicMock()
        if name == "calendar_entries":
            chain = handle.select.return_value.eq.return_value.not_.is_.return_value.is_.return_value.limit.return_value
            chain.execute.return_value.data = [
                {"id": "entry-1", "ical_uid": "uid-1@example.com", "original_start": ""},
                {"id": "entry-2", "ical_uid": "uid-2@example.com", "original_start": ""},
            ]
        elif name == "event_identity_hints":
            handle.select.return_value.eq.return_value.not_.is_.return_value.execute.return_value.data = [
                {"calendar_entry_id": "entry-1"},
            ]
            handle.upsert.side_effect = lambda payload, **kw: (
                written.extend(payload), MagicMock()
            )[1]
        return handle

    client.table.side_effect = table

    indexed = _index_unhinted_entries(client, "user-1")
    assert indexed == 1, "only the entry lacking a hint should be indexed"
    assert [row["calendar_entry_id"] for row in written] == ["entry-2"]


def test_indexing_is_a_no_op_when_everything_is_already_indexed():
    """The repair must not rewrite hints on every sync."""
    from selko.services.calendar_mirror import _index_unhinted_entries

    client = MagicMock()
    written: list[dict] = []

    def table(name):
        handle = MagicMock()
        if name == "calendar_entries":
            chain = handle.select.return_value.eq.return_value.not_.is_.return_value.is_.return_value.limit.return_value
            chain.execute.return_value.data = [
                {"id": "entry-1", "ical_uid": "uid-1@example.com", "original_start": ""},
            ]
        elif name == "event_identity_hints":
            handle.select.return_value.eq.return_value.not_.is_.return_value.execute.return_value.data = [
                {"calendar_entry_id": "entry-1"},
            ]
            handle.upsert.side_effect = lambda payload, **kw: (
                written.extend(payload), MagicMock()
            )[1]
        return handle

    client.table.side_effect = table
    assert _index_unhinted_entries(client, "user-1") == 0
    assert written == []


def test_every_calendar_is_mirrored_not_only_the_write_target():
    """target_calendar_id is where Selko writes, not where invites arrive.

    This account carries three calendars, and the interview invitations Selko
    kept proposing as new were on one it never read. Mirroring only the write
    target made "the user already has this" unanswerable for every calendar but
    one.
    """
    from selko.services import calendar_mirror

    seen: list[str] = []

    def fake_sync(client, user_id, integration_id, calendar_id, **kwargs):
        seen.append(calendar_id)
        return {"entries": 1, "full_resync": False, "has_sync_token": True}

    original_list = calendar_mirror.list_calendars
    original_sync = calendar_mirror.sync_calendar
    calendar_mirror.list_calendars = lambda client, user_id: [
        {"id": "me@example.com"}, {"id": "work@example.com"}, {"id": "shared@example.com"},
    ]
    calendar_mirror.sync_calendar = fake_sync
    try:
        totals = calendar_mirror.sync_all_calendars(MagicMock(), "u1", "i1")
    finally:
        calendar_mirror.list_calendars = original_list
        calendar_mirror.sync_calendar = original_sync

    assert seen == ["me@example.com", "work@example.com", "shared@example.com"]
    assert totals == {"calendars": 3, "entries": 3, "failed": 0}


def test_one_failing_calendar_does_not_stop_the_others():
    """A permission error on one subscription must not blind the rest."""
    from selko.services import calendar_mirror

    def fake_sync(client, user_id, integration_id, calendar_id, **kwargs):
        if calendar_id == "broken@example.com":
            raise RuntimeError("permission denied")
        return {"entries": 2, "full_resync": False, "has_sync_token": True}

    original_list = calendar_mirror.list_calendars
    original_sync = calendar_mirror.sync_calendar
    calendar_mirror.list_calendars = lambda client, user_id: [
        {"id": "me@example.com"}, {"id": "broken@example.com"}, {"id": "work@example.com"},
    ]
    calendar_mirror.sync_calendar = fake_sync
    try:
        totals = calendar_mirror.sync_all_calendars(MagicMock(), "u1", "i1")
    finally:
        calendar_mirror.list_calendars = original_list
        calendar_mirror.sync_calendar = original_sync

    assert totals == {"calendars": 2, "entries": 4, "failed": 1}


def test_the_primary_alias_is_never_mirrored_alongside_its_real_id():
    """"primary" is an alias, and list_calendars also returns the real id.

    Mirroring both stores every event twice under two calendar ids, and one
    iCalUID naming two entries makes the hint ambiguous -- which identity
    matching treats as no match, silently undoing the mirror's whole purpose.
    241 UIDs were duplicated this way in production before it was caught.
    """
    from selko.services import calendar_mirror

    seen: list[str] = []

    def fake_sync(client, user_id, integration_id, calendar_id, **kwargs):
        seen.append(calendar_id)
        return {"entries": 1, "full_resync": False, "has_sync_token": True}

    original_list = calendar_mirror.list_calendars
    original_sync = calendar_mirror.sync_calendar
    calendar_mirror.list_calendars = lambda client, user_id: [
        {"id": "primary"},
        {"id": "me@example.com"},
        {"id": "work@example.com"},
    ]
    calendar_mirror.sync_calendar = fake_sync
    try:
        totals = calendar_mirror.sync_all_calendars(MagicMock(), "u1", "i1")
    finally:
        calendar_mirror.list_calendars = original_list
        calendar_mirror.sync_calendar = original_sync

    assert "primary" not in seen
    assert seen == ["me@example.com", "work@example.com"]
    assert totals["calendars"] == 2


class TestJoinUrlsReachTheHints:
    """A mirrored entry must be indexed by the same signal an email carries.

    Emails carry Zoom/Meet links and no iCalUID; calendar entries carry a UID
    the email never mentions. Indexing entries by UID alone left the two hint
    sets disjoint, so four Snowflake interviews sat in the New lane while the
    identical entries -- same Zoom links -- sat on an imported calendar.
    """

    def test_hangout_link_is_kept_on_the_row(self):
        from selko.services.calendar_mirror import entry_row

        row = entry_row(
            {"id": "e1", "hangoutLink": "https://meet.google.com/abc-defg-hij"},
            user_id="u1", integration_id="i1", calendar_id="c1",
        )
        assert row["join_url"] == "https://meet.google.com/abc-defg-hij"

    def test_conference_entry_point_is_kept_when_there_is_no_hangout_link(self):
        from selko.services.calendar_mirror import entry_row

        row = entry_row(
            {
                "id": "e1",
                "conferenceData": {"entryPoints": [
                    {"entryPointType": "phone"},
                    {"entryPointType": "video", "uri": "https://snowflake.zoom.us/j/123"},
                ]},
            },
            user_id="u1", integration_id="i1", calendar_id="c1",
        )
        assert row["join_url"] == "https://snowflake.zoom.us/j/123"

    def test_an_entry_without_conferencing_stores_no_join_url(self):
        from selko.services.calendar_mirror import entry_row

        row = entry_row(
            {"id": "e1"}, user_id="u1", integration_id="i1", calendar_id="c1"
        )
        assert row["join_url"] is None

    def test_the_stored_join_url_becomes_a_join_hint(self):
        """The regression that matters: the hint writer must not drop it."""
        from selko.services import calendar_mirror

        client = MagicMock()
        captured: dict = {}

        def capture(payload, on_conflict=None):
            captured["payload"] = payload
            return MagicMock()

        client.table.return_value.upsert.side_effect = capture

        calendar_mirror._write_entry_hints(client, "u1", [
            {"id": "entry-1", "ical_uid": None, "join_url": "https://snowflake.zoom.us/j/123"},
        ])

        kinds = {h["kind"] for h in captured["payload"]}
        assert "join_url" in kinds
