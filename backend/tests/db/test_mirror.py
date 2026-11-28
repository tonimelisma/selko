"""selko.db.mirror against a real SQLite database.

Ports the database half of test_calendar_mirror.py: the rows the mirror
writes (built by the real `entry_row`), read back for indexing even though
nothing is echoed, the repair pass over entries that have no hint, and the
sync-state upsert. Every user-scoped read is checked against a second user.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from selko.db import mirror
from selko.db.errors import InvalidArgument, NotOwned
from selko.services.calendar_mirror import entry_row
from selko.services.event_identity import hints_from_calendar_event


def _google(event_id: str, **extra):
    base = {
        "id": event_id,
        "iCalUID": f"{event_id}@example.com",
        "summary": "Dentist",
        "start": {"dateTime": "2026-12-01T10:00:00-08:00", "timeZone": "America/Los_Angeles"},
        "end": {"dateTime": "2026-12-01T11:00:00-08:00"},
        "updated": "2026-11-20T08:00:00.000Z",
        "status": "confirmed",
    }
    base.update(extra)
    return base


def _rows(user, integration, *events, calendar_id="primary"):
    return [entry_row(e, user_id=user, integration_id=integration, calendar_id=calendar_id) for e in events]


def _hint_rows(user, stored):
    out = []
    for row in stored:
        for hint in hints_from_calendar_event({"iCalUID": row["ical_uid"], "hangoutLink": row.get("join_url")}):
            out.append({"user_id": user, "event_id": None, "calendar_entry_id": row["id"], **hint.as_payload()})
    return out


@pytest.fixture
def owner(factory):
    user = factory.user()
    return user, factory.integration(user, "google_calendar")


# --- calendar_entries ---------------------------------------------------------


def test_upsert_stores_the_entry_and_returns_what_indexing_needs(db, owner):
    user, integration = owner
    stored = mirror.upsert_entries(db, user, _rows(user, integration, _google("evt-1", hangoutLink="https://meet.google.com/abc-defg-hij")))
    assert len(stored) == 1
    assert set(stored[0]) == {"id", "ical_uid", "original_start", "deleted_at", "join_url"}
    assert stored[0]["ical_uid"] == "evt-1@example.com"
    row = db.schema.decode("calendar_entries", db.query_one("SELECT * FROM calendar_entries WHERE id = ?", (stored[0]["id"],)))
    assert row["start_at"] == "2026-12-01T18:00:00.000000Z", "provider times are stored in UTC"
    assert row["provider_updated_at"] == "2026-11-20T08:00:00.000000Z"
    assert row["all_day"] is False
    assert row["origin"] == "external"
    assert row["join_url"] == "https://meet.google.com/abc-defg-hij"
    assert row["user_id"] == user


# Validates: SEL-372
def test_upsert_updates_in_place_on_the_provider_key(db, owner):
    user, integration = owner
    first = mirror.upsert_entries(db, user, _rows(user, integration, _google("evt-1")))[0]
    before = db.query_one("SELECT created_at, updated_at FROM calendar_entries WHERE id = ?", (first["id"],))
    again = mirror.upsert_entries(db, user, _rows(user, integration, _google("evt-1", summary="Dentist (moved)")))[0]
    assert again["id"] == first["id"], "the row is updated, not duplicated"
    after = db.query_one("SELECT title, created_at, updated_at FROM calendar_entries WHERE id = ?", (first["id"],))
    assert after["title"] == "Dentist (moved)"
    assert after["created_at"] == before["created_at"]
    assert after["updated_at"] > before["updated_at"], "the fingerprint fence sees every mirror write"
    assert db.query_one("SELECT count(*) FROM calendar_entries")[0] == 1


# Validates: SEL-372
def test_same_provider_id_in_another_calendar_is_another_entry(db, owner):
    user, integration = owner
    mirror.upsert_entries(db, user, _rows(user, integration, _google("evt-1")))
    mirror.upsert_entries(db, user, _rows(user, integration, _google("evt-1"), calendar_id="family"))
    assert db.query_one("SELECT count(*) FROM calendar_entries")[0] == 2


# Validates: SEL-372
def test_cancelled_entries_are_tombstoned(db, owner):
    user, integration = owner
    stored = mirror.upsert_entries(db, user, _rows(user, integration, _google("evt-1", status="cancelled")))[0]
    assert stored["deleted_at"] is not None
    assert stored["deleted_at"].endswith("Z") and len(stored["deleted_at"]) == 27


def test_all_day_entries_store_midnight_utc(db, owner):
    user, integration = owner
    event = _google("evt-1", start={"date": "2026-12-24"}, end={"date": "2026-12-25"})
    stored = mirror.upsert_entries(db, user, _rows(user, integration, event))[0]
    row = db.query_one("SELECT start_at, all_day FROM calendar_entries WHERE id = ?", (stored["id"],))
    assert tuple(row) == ("2026-12-24T00:00:00.000000Z", 1)


# Validates: SEL-375
def test_upsert_refuses_another_users_integration(db, factory, owner):
    user, integration = owner
    other = factory.user()
    with pytest.raises(NotOwned):
        mirror.upsert_entries(db, other, _rows(other, integration, _google("evt-1")))
    with pytest.raises(NotOwned):
        mirror.upsert_entries(db, other, _rows(user, integration, _google("evt-1")))
    assert db.query_one("SELECT count(*) FROM calendar_entries")[0] == 0


def test_upsert_refuses_unknown_columns(db, owner):
    user, integration = owner
    row = _rows(user, integration, _google("evt-1"))[0] | {"colour": "red"}
    with pytest.raises(InvalidArgument):
        mirror.upsert_entries(db, user, [row])






# --- identity hints -----------------------------------------------------------


# Validates: SEL-374
def test_mirrored_entries_are_indexed_by_uid_and_join_url(db, owner):
    user, integration = owner
    stored = mirror.upsert_entries(db, user, _rows(user, integration, _google("evt-1", hangoutLink="https://meet.google.com/abc-defg-hij")))
    hints = _hint_rows(user, stored)
    assert {h["kind"] for h in hints} == {"ical_uid", "join_url"}
    assert mirror.upsert_entry_hints(db, user, hints) == 2
    rows = db.query("SELECT kind, event_id, calendar_entry_id, user_id FROM event_identity_hints ORDER BY kind")
    assert [tuple(r) for r in rows] == [
        ("ical_uid", None, stored[0]["id"], user),
        ("join_url", None, stored[0]["id"], user),
    ]


def test_hint_upsert_is_idempotent(db, owner):
    user, integration = owner
    stored = mirror.upsert_entries(db, user, _rows(user, integration, _google("evt-1")))
    hints = _hint_rows(user, stored)
    mirror.upsert_entry_hints(db, user, hints)
    first = db.query_one("SELECT id, created_at FROM event_identity_hints")
    mirror.upsert_entry_hints(db, user, hints)
    assert db.query_one("SELECT count(*) FROM event_identity_hints")[0] == 1
    assert tuple(db.query_one("SELECT id, created_at FROM event_identity_hints")) == tuple(first)


def test_hints_refuse_another_users_entry_and_event_hints(db, factory, owner):
    user, integration = owner
    stored = mirror.upsert_entries(db, user, _rows(user, integration, _google("evt-1")))
    other = factory.user()
    with pytest.raises(NotOwned):
        mirror.upsert_entry_hints(db, other, _hint_rows(other, stored))
    event = factory.event(user)
    with pytest.raises(InvalidArgument):
        mirror.upsert_entry_hints(db, user, [{**_hint_rows(user, stored)[0], "event_id": event}])
    assert db.query_one("SELECT count(*) FROM event_identity_hints")[0] == 0


def test_entries_without_a_hint_are_found_for_repair(db, factory, owner):
    """`_index_unhinted_entries`: list indexable entries, subtract the hinted ones."""
    user, integration = owner
    stored = mirror.upsert_entries(db, user, _rows(
        user, integration, _google("evt-1"), _google("evt-2"),
        _google("evt-3", status="cancelled"), _google("evt-4", iCalUID=None),
    ))
    mirror.upsert_entry_hints(db, user, _hint_rows(user, stored[:1]))

    indexable = mirror.indexable_entries(db, user)
    assert [e["ical_uid"] for e in indexable] == ["evt-1@example.com", "evt-2@example.com"], (
        "tombstoned entries and entries with no UID are not indexable"
    )
    assert set(indexable[0]) == {"id", "ical_uid", "original_start"}
    hinted = mirror.hinted_entry_ids(db, user)
    assert hinted == {stored[0]["id"]}
    assert [e["id"] for e in indexable if e["id"] not in hinted] == [stored[1]["id"]]


def test_repair_reads_are_per_user_and_bounded(db, factory, owner):
    user, integration = owner
    stored = mirror.upsert_entries(db, user, _rows(user, integration, _google("evt-1"), _google("evt-2")))
    mirror.upsert_entry_hints(db, user, _hint_rows(user, stored))
    other = factory.user()
    assert mirror.indexable_entries(db, other) == []
    assert mirror.hinted_entry_ids(db, other) == set()
    assert len(mirror.indexable_entries(db, user, limit=1)) == 1


def test_event_hints_are_not_counted_as_entry_hints(db, factory, owner):
    user, _ = owner
    event = factory.event(user)
    with db.write() as tx:
        tx.execute(
            "INSERT INTO event_identity_hints (id, user_id, event_id, kind, value_hash, strength) "
            "VALUES ('00000000-0000-4000-8000-000000000001', ?, ?, 'ical_uid', 'h', 'authoritative')",
            (user, event),
        )
    assert mirror.hinted_entry_ids(db, user) == set()


# --- calendar_mirror_state ----------------------------------------------------


def test_state_is_none_before_the_first_pass(db, owner):
    user, integration = owner
    assert mirror.get_state(db, user, integration, "primary") is None


def test_save_state_then_read_the_token(db, factory, owner):
    user, integration = owner
    start = datetime(2026, 8, 27, tzinfo=UTC)
    end = datetime(2027, 11, 25, tzinfo=UTC)
    mirror.save_state(db, user, integration, "primary", sync_token="tok-1",
                      window_start=start, window_end=end, full_resync=True)
    assert mirror.get_state(db, user, integration, "primary") == {"sync_token": "tok-1"}
    row = db.query_one("SELECT * FROM calendar_mirror_state")
    assert row["window_start"] == "2026-08-27T00:00:00.000000Z"
    assert row["last_full_resync_at"] == row["last_success_at"] is not None
    assert row["consecutive_failures"] == 0
    assert mirror.get_state(db, factory.user(), integration, "primary") is None, "per user"


def test_an_incremental_pass_updates_and_clears_the_full_resync_time(db, owner):
    user, integration = owner
    start, end = "2026-08-27T00:00:00+00:00", "2027-11-25T00:00:00+00:00"
    mirror.save_state(db, user, integration, "primary", sync_token="tok-1",
                      window_start=start, window_end=end, full_resync=True)
    with db.write() as tx:
        tx.execute("UPDATE calendar_mirror_state SET consecutive_failures = 4, last_error_code = 'boom', "
                   "lease_owner = 'w1'")
    mirror.save_state(db, user, integration, "primary", sync_token="tok-2",
                      window_start=start, window_end=end, full_resync=False)
    rows = db.query("SELECT * FROM calendar_mirror_state")
    assert len(rows) == 1
    row = rows[0]
    assert row["sync_token"] == "tok-2"
    assert row["consecutive_failures"] == 0 and row["last_error_code"] is None
    assert row["last_full_resync_at"] is None, "the service's upsert always sent the column"
    assert row["lease_owner"] == "w1", "columns the service did not send are kept"


# Validates: SEL-375
def test_save_state_refuses_another_users_integration(db, factory, owner):
    _, integration = owner
    with pytest.raises(NotOwned):
        mirror.save_state(db, factory.user(), integration, "primary", sync_token=None,
                          window_start="2026-01-01T00:00:00Z", window_end="2027-01-01T00:00:00Z",
                          full_resync=True)
