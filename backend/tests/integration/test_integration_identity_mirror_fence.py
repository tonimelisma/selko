"""The commit fence must cover mirrored calendar entries (I3).

`commit_email_extraction` re-checks at write time that the rows a decision was
computed against have not changed. Its hint fingerprint covered `events` only.
Once a hint can name a `calendar_entries` row, a concurrent mirror sync can
change the matched entry between the decision and the commit — the race
`parallel-extraction-fenced-commit` closed for events, reopened for calendars.

These run on a real SQLite database (the mirror side: `selko.db.mirror`) because
the fence's inputs are what the database stores, not the shape of a query.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from selko.api.schemas.calendar import CalendarEvent, CalendarEventExtraction
from selko.db import events as db_events
from selko.services.events import ResolutionConflictExhausted, save_extracted_events
from tests.event_pipeline import claimed_email, gateway, lease, providers_offline
from tests.event_pipeline import spy_commit  # noqa: F401  (fixture)

from selko.db import errors
from selko.db import mirror as db_mirror
from selko.db.codec import new_id


pytestmark = [pytest.mark.integration]


@pytest.fixture
def user_id(factory):
    return factory.user()


@pytest.fixture
def calendar_integration(factory, user_id):
    return factory.integration(
        user_id,
        provider="google_calendar",
        access_token="fence-probe",
        scopes=["https://www.googleapis.com/auth/calendar"],
    )


def _entry(db, user_id, integration_id, **extra):
    row = {
        "user_id": user_id,
        "integration_id": integration_id,
        "calendar_id": "primary",
        "provider_event_id": f"probe-{uuid.uuid4().hex[:8]}",
        "ical_uid": f"probe-{uuid.uuid4().hex[:8]}@example.com",
        "title": "Mirrored probe",
        "start_at": "2026-10-01T10:00:00Z",
    }
    row.update(extra)
    return row, db_mirror.upsert_entries(db, user_id, [row])[0]


class TestFenceCoversCalendarEntries:
    def test_a_calendar_entry_hint_participates_in_the_fingerprint(
        self, db, user_id, calendar_integration
    ):
        """Changing a mirrored entry must change what the fingerprint reads.

        If it does not, a mirror sync landing between match and commit is
        invisible to the fence and the decision is written against rows that
        have since moved. The fence reads `calendar_entries.updated_at`
        through the hint, so a mirror write must move it every time.
        """
        row, stored = _entry(db, user_id, calendar_integration)
        db_mirror.upsert_entry_hints(db, user_id, [{
            "user_id": user_id,
            "event_id": None,
            "calendar_entry_id": stored["id"],
            "kind": "ical_uid",
            "value_hash": uuid.uuid4().hex,
            "recurrence_id": "",
            "strength": "authoritative",
        }])

        hint = db.query_one(
            "SELECT h.calendar_entry_id, h.event_id, e.updated_at FROM event_identity_hints h "
            "JOIN calendar_entries e ON e.id = h.calendar_entry_id WHERE h.user_id = ?",
            (user_id,),
        )
        # The hint row exists and names the entry, not an event.
        assert hint["calendar_entry_id"] == stored["id"]
        assert hint["event_id"] is None
        before = hint["updated_at"]

        # A mirror pass rewriting the same entry (same provider key) moves it.
        db_mirror.upsert_entries(db, user_id, [{**row, "title": "Moved probe"}])
        after = db.query_one(
            "SELECT id, updated_at FROM calendar_entries WHERE id = ?", (stored["id"],))
        assert after["id"] == stored["id"]
        assert after["updated_at"] > before

    def test_a_hint_must_name_exactly_one_entity(self, db, factory, user_id, calendar_integration):
        """Both set, or neither, would leave the lookup guessing which was meant."""
        _, stored = _entry(db, user_id, calendar_integration, ical_uid=None)
        event_id = factory.event(
            user_id, title="Both", start_datetime="2026-10-01T10:00:00.000000Z",
            review_status="active",
        )

        def insert(event, entry):
            with db.write() as tx:
                tx.execute(
                    "INSERT INTO event_identity_hints (id, user_id, event_id, calendar_entry_id, "
                    "kind, value_hash, recurrence_id, strength, created_at) "
                    "VALUES (?, ?, ?, ?, 'ical_uid', ?, '', 'authoritative', ?)",
                    (new_id(), user_id, event, entry, uuid.uuid4().hex, tx.now_text),
                )

        with pytest.raises(errors.DbError):
            insert(event_id, stored["id"])
        with pytest.raises(errors.DbError):
            insert(None, None)
        assert db.query("SELECT id FROM event_identity_hints WHERE user_id = ?", (user_id,)) == []

        # The mirror's writer refuses an event hint outright.
        with pytest.raises(errors.InvalidArgument):
            db_mirror.upsert_entry_hints(db, user_id, [{
                "user_id": user_id, "event_id": event_id, "calendar_entry_id": stored["id"],
                "kind": "ical_uid", "value_hash": uuid.uuid4().hex,
                "recurrence_id": "", "strength": "authoritative",
            }])


# --- the event side: producer and commit compute one fingerprint -----------------
#
# `services/events._load_identity_candidates` used to fingerprint its candidate
# map, in which a mirrored entry carries no `updated_at`, while the commit
# fingerprinted the entry row itself. Any hint naming a calendar entry therefore
# conflicted on every attempt and the email ended in ResolutionConflictExhausted.
# Both sides now call `db.events.hint_fingerprint`.

UID = "c" * 64


def _invite_with_uid_on_the_calendar(db, factory):
    """An email whose invite UID names an entry already mirrored (another day)."""
    user = factory.user()
    factory._insert("user_calendar_settings", {"user_id": user, "timezone": "UTC"})
    integration = factory.integration(user, provider="google_calendar")
    entry = factory._insert("calendar_entries", {
        "id": new_id(), "user_id": user, "integration_id": integration, "calendar_id": "primary",
        "provider_event_id": "uid-entry", "title": "Quarterly review",
        "start_at": "2030-01-01T09:00:00.000000Z"})
    factory._insert("event_identity_hints", {
        "id": new_id(), "user_id": user, "calendar_entry_id": entry, "kind": "ical_uid",
        "value_hash": UID, "recurrence_id": "", "strength": "authoritative"})
    email = claimed_email(factory, user)
    factory._insert("email_calendar_components", {
        "id": new_id(), "email_id": email, "user_id": user, "component_index": 0,
        "method": "REQUEST", "uid_hash": UID, "recurrence_id": ""})
    start = (datetime.now(timezone.utc) + timedelta(days=20)).replace(
        hour=15, minute=0, second=0, microsecond=0, tzinfo=None)
    extraction = CalendarEventExtraction(
        email_message_id="invite", sender_email="organizer@example.com", events_found=True,
        events=[CalendarEvent(title="Quarterly review", start_datetime=start,
                              end_datetime=start + timedelta(hours=1), description="Agenda")],
    )
    return user, entry, email, extraction


def test_a_hint_naming_a_calendar_entry_no_longer_always_conflicts(db, factory, spy_commit):
    user, _, email, extraction = _invite_with_uid_on_the_calendar(db, factory)
    fence_before = db_events.hint_fingerprint(db, user, [f"ical_uid|{UID}|"])

    with providers_offline(), \
         patch("selko.services.events.event_processing.compare_events", return_value=None):
        save_extracted_events(db, gateway(), user, email, extraction, **lease(db, email))

    assert len(spy_commit.calls) == 1, "one attempt: nothing to retry"
    decision = spy_commit.decisions[0]
    assert decision["hint_keys"] == [f"ical_uid|{UID}|"]
    assert decision["expected_hint_fingerprint"] == fence_before
    assert spy_commit.results[0].get("conflict") is False
    # The new event carries the UID too, next to the entry it matched.
    assert db.query_one("SELECT count(*) FROM event_identity_hints WHERE value_hash = ?", (UID,))[0] == 2


def test_a_mirror_sync_between_decision_and_commit_is_still_fenced(db, factory, monkeypatch):
    """The fix must not blind the fence: an entry that moves after the read conflicts."""
    user, entry, email, extraction = _invite_with_uid_on_the_calendar(db, factory)
    real = db_events.commit_email_extraction

    def mirror_sync_first(database, *args):
        with database.write() as tx:
            tx.execute("UPDATE calendar_entries SET updated_at = ? WHERE id = ?", (tx.now_text, entry))
        return real(database, *args)

    monkeypatch.setattr("selko.services.events.db_events.commit_email_extraction", mirror_sync_first)
    with providers_offline(), \
         patch("selko.services.events.event_processing.compare_events", return_value=None), \
         pytest.raises(ResolutionConflictExhausted):
        save_extracted_events(db, gateway(), user, email, extraction, **lease(db, email))

    assert db.query("SELECT 1 FROM events WHERE user_id = ?", (user,)) == []
