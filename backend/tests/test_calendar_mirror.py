"""Contracts for the calendar mirror (I2 of event-identity-reach).

Database reads and writes run on a real SQLite database (`db`/`factory`);
only the calendar provider is faked.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from selko.services.calendar_mirror import WINDOW_AHEAD, WINDOW_BEHIND, entry_row, rolling_window


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


# Validates: SEL-373
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






# Validates: SEL-371
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


class _FakeAdapter:
    """A provider adapter that serves fixed mirror pages (Google's API stays mocked)."""

    def __init__(self, pages, *, expire_first=False):
        self.pages = list(pages)
        self.calls: list[dict] = []
        self.expire_first = expire_first

    def mirror_page(self, calendar_id, *, sync_token, window, page_token=None):
        from selko.services.calendar_providers import CalendarSyncTokenExpired

        self.calls.append({"calendar_id": calendar_id, "sync_token": sync_token, "page_token": page_token})
        if self.expire_first:
            self.expire_first = False
            raise CalendarSyncTokenExpired("gone")
        return self.pages.pop(0) if self.pages else {"items": [], "nextSyncToken": "tok-final"}


def _mirror_user(factory):
    user_id = factory.user()
    integration_id = factory.integration(user_id, provider="google_calendar", scopes=["calendar"])
    return user_id, integration_id


def _hints(db, user_id):
    return [dict(r) for r in db.query(
        "SELECT calendar_entry_id, event_id, kind FROM event_identity_hints WHERE user_id = ? "
        "ORDER BY rowid", (user_id,))]


def _sync(db, user_id, integration_id, adapter, calendar_id="me@example.com"):
    from unittest.mock import patch

    from selko.services import calendar_mirror

    with patch.object(calendar_mirror, "_mirror_adapter", return_value=adapter):
        return calendar_mirror.sync_calendar(db, user_id, integration_id, calendar_id)


def test_entries_are_indexed_from_what_the_database_stores(db, factory):
    """The mirror must index what it stores, not what the write echoes back.

    Production mirrored 1595 calendar entries carrying 1595 iCalUIDs and wrote
    zero identity hints, because the code indexed `upsert(...).execute().data`
    and PostgREST returned no representation. This runs the whole pass on a
    real database: the entry ids the hints carry are the stored rows' ids.
    """
    user_id, integration_id = _mirror_user(factory)
    adapter = _FakeAdapter([{"items": [_entry()], "nextSyncToken": "tok-1"}])

    summary = _sync(db, user_id, integration_id, adapter)

    assert summary["entries"] == 1 and summary["full_resync"] is True
    entry = db.query_one("SELECT id, ical_uid FROM calendar_entries WHERE user_id = ?", (user_id,))
    assert entry["ical_uid"] == "uid-1@example.com"
    hints = _hints(db, user_id)
    assert hints, "a mirrored entry with an iCalUID must produce a hint"
    assert {h["calendar_entry_id"] for h in hints} == {entry["id"]}
    assert hints[0]["kind"] == "ical_uid"
    assert hints[0]["event_id"] is None


# Validates: SEL-371
def test_the_sync_token_is_saved_and_used_next_pass(db, factory):
    from selko.db import mirror as db_mirror

    user_id, integration_id = _mirror_user(factory)
    _sync(db, user_id, integration_id,
          _FakeAdapter([{"items": [_entry()], "nextSyncToken": "tok-1"}]))
    assert db_mirror.get_state(db, user_id, integration_id, "me@example.com") == {"sync_token": "tok-1"}

    adapter = _FakeAdapter([{"items": [], "nextSyncToken": "tok-2"}])
    summary = _sync(db, user_id, integration_id, adapter)

    assert adapter.calls[0]["sync_token"] == "tok-1"
    assert summary == {"entries": 0, "full_resync": False, "has_sync_token": True, "arrived": []}
    state = db.query_one(
        "SELECT sync_token, last_full_resync_at, consecutive_failures FROM calendar_mirror_state "
        "WHERE integration_id = ?", (integration_id,))
    assert state["sync_token"] == "tok-2"
    assert state["last_full_resync_at"] is None
    assert state["consecutive_failures"] == 0


# Validates: SEL-371
def test_an_expired_sync_token_triggers_one_full_resync(db, factory):
    user_id, integration_id = _mirror_user(factory)
    _sync(db, user_id, integration_id,
          _FakeAdapter([{"items": [], "nextSyncToken": "tok-1"}]))

    adapter = _FakeAdapter([{"items": [_entry()], "nextSyncToken": "tok-new"}], expire_first=True)
    summary = _sync(db, user_id, integration_id, adapter)

    assert [c["sync_token"] for c in adapter.calls] == ["tok-1", None]
    assert summary["full_resync"] is True
    assert summary["entries"] == 1


# Validates: SEL-372
def test_a_second_pass_updates_the_entry_in_place(db, factory):
    user_id, integration_id = _mirror_user(factory)
    _sync(db, user_id, integration_id, _FakeAdapter([{"items": [_entry()], "nextSyncToken": "t"}]))
    _sync(db, user_id, integration_id, _FakeAdapter([{"items": [
        _entry(summary="Renamed standup", status="cancelled"),
    ], "nextSyncToken": "t2"}]))

    rows = db.query("SELECT title, status, deleted_at FROM calendar_entries WHERE user_id = ?", (user_id,))
    assert len(rows) == 1
    assert rows[0]["title"] == "Renamed standup"
    assert rows[0]["deleted_at"] is not None


def _stored_entry(db, user_id, integration_id, provider_event_id, uid):
    from selko.db import mirror as db_mirror

    row = entry_row(
        _entry(id=provider_event_id, iCalUID=uid),
        user_id=user_id, integration_id=integration_id, calendar_id="me@example.com",
    )
    return db_mirror.upsert_entries(db, user_id, [row])[0]


# Validates: SEL-374
def test_entries_mirrored_before_indexing_worked_are_repaired(db, factory):
    """Indexing must be a repair, not a side effect of writing.

    Once a sync token exists an unchanged calendar returns no rows, so nothing
    is upserted and nothing is indexed. Production sat at 1595 mirrored entries
    and 0 hints because indexing only ran for rows a pass happened to write --
    every entry mirrored before the fix was unreachable for good.
    """
    from selko.services.calendar_mirror import _index_unhinted_entries, _write_entry_hints

    user_id, integration_id = _mirror_user(factory)
    first = _stored_entry(db, user_id, integration_id, "evt-1", "uid-1@example.com")
    second = _stored_entry(db, user_id, integration_id, "evt-2", "uid-2@example.com")
    _write_entry_hints(db, user_id, [first])

    indexed = _index_unhinted_entries(db, user_id)

    assert indexed == 1, "only the entry lacking a hint should be indexed"
    assert {h["calendar_entry_id"] for h in _hints(db, user_id)} == {first["id"], second["id"]}


def test_indexing_is_a_no_op_when_everything_is_already_indexed(db, factory):
    """The repair must not rewrite hints on every sync."""
    from selko.services.calendar_mirror import _index_unhinted_entries, _write_entry_hints

    user_id, integration_id = _mirror_user(factory)
    first = _stored_entry(db, user_id, integration_id, "evt-1", "uid-1@example.com")
    _write_entry_hints(db, user_id, [first])
    before = _hints(db, user_id)

    assert _index_unhinted_entries(db, user_id) == 0
    assert _hints(db, user_id) == before


def test_indexing_never_reads_another_users_entries(db, factory):
    from selko.services.calendar_mirror import _index_unhinted_entries

    user_id, integration_id = _mirror_user(factory)
    other, other_integration = _mirror_user(factory)
    _stored_entry(db, other, other_integration, "evt-9", "uid-9@example.com")

    assert _index_unhinted_entries(db, user_id) == 0
    assert _hints(db, user_id) == []




# Validates: SEL-370
def test_every_calendar_is_mirrored_not_only_the_write_target(db):
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

    original_list = calendar_mirror.list_provider_calendars
    original_sync = calendar_mirror.sync_calendar
    calendar_mirror.list_provider_calendars = lambda client, user_id, provider: [
        {"id": "me@example.com"}, {"id": "work@example.com"}, {"id": "shared@example.com"},
    ]
    calendar_mirror.sync_calendar = fake_sync
    try:
        totals = calendar_mirror.sync_all_calendars(db, "u1", "i1")
    finally:
        calendar_mirror.list_provider_calendars = original_list
        calendar_mirror.sync_calendar = original_sync

    assert seen == ["me@example.com", "work@example.com", "shared@example.com"]
    assert totals == {"calendars": 3, "entries": 3, "failed": 0, "arrived": []}


# Validates: SEL-370
def test_one_failing_calendar_does_not_stop_the_others(db):
    """A permission error on one subscription must not blind the rest."""
    from selko.services import calendar_mirror

    def fake_sync(client, user_id, integration_id, calendar_id, **kwargs):
        if calendar_id == "broken@example.com":
            raise RuntimeError("permission denied")
        return {"entries": 2, "full_resync": False, "has_sync_token": True}

    original_list = calendar_mirror.list_provider_calendars
    original_sync = calendar_mirror.sync_calendar
    calendar_mirror.list_provider_calendars = lambda client, user_id, provider: [
        {"id": "me@example.com"}, {"id": "broken@example.com"}, {"id": "work@example.com"},
    ]
    calendar_mirror.sync_calendar = fake_sync
    try:
        totals = calendar_mirror.sync_all_calendars(db, "u1", "i1")
    finally:
        calendar_mirror.list_provider_calendars = original_list
        calendar_mirror.sync_calendar = original_sync

    assert totals == {"calendars": 2, "entries": 4, "failed": 1, "arrived": []}


# Validates: SEL-370
def test_the_primary_alias_is_never_mirrored_alongside_its_real_id(db):
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

    original_list = calendar_mirror.list_provider_calendars
    original_sync = calendar_mirror.sync_calendar
    calendar_mirror.list_provider_calendars = lambda client, user_id, provider: [
        {"id": "primary"},
        {"id": "me@example.com"},
        {"id": "work@example.com"},
    ]
    calendar_mirror.sync_calendar = fake_sync
    try:
        totals = calendar_mirror.sync_all_calendars(db, "u1", "i1")
    finally:
        calendar_mirror.list_provider_calendars = original_list
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

    def test_the_stored_join_url_becomes_a_join_hint(self, db, factory):
        """The regression that matters: the hint writer must not drop it."""
        from selko.services import calendar_mirror

        user_id, integration_id = _mirror_user(factory)
        stored = _stored_entry(db, user_id, integration_id, "evt-1", None)

        calendar_mirror._write_entry_hints(db, user_id, [
            {"id": stored["id"], "ical_uid": None, "join_url": "https://snowflake.zoom.us/j/123"},
        ])

        kinds = {h["kind"] for h in _hints(db, user_id)}
        assert "join_url" in kinds


class TestJoinUrlFromLocation:
    """ICS-imported entries carry the join link in `location`, not conferenceData.

    Every Snowflake interview on the user's imported calendar looked like this,
    so adding the join_url column alone still left them unindexed.
    """

    def _row(self, entry):
        from selko.services.calendar_mirror import entry_row
        return entry_row(entry, user_id="u1", integration_id="i1", calendar_id="c1")

    def test_a_url_location_becomes_the_join_url(self):
        row = self._row({
            "id": "e1",
            "location": "https://snowflake.zoom.us/j/86723994247?pwd=fg82dzeav24uSFhw",
        })
        assert row["join_url"] == "https://snowflake.zoom.us/j/86723994247?pwd=fg82dzeav24uSFhw"

    def test_a_street_address_never_becomes_an_identity_signal(self):
        row = self._row({"id": "e1", "location": "1600 Amphitheatre Parkway, Mountain View"})
        assert row["join_url"] is None

    def test_structured_conferencing_still_wins_over_location(self):
        row = self._row({
            "id": "e1",
            "hangoutLink": "https://meet.google.com/abc-defg-hij",
            "location": "https://example.com/somewhere-else",
        })
        assert row["join_url"] == "https://meet.google.com/abc-defg-hij"
