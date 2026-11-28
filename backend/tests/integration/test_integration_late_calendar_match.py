"""Late calendar matches: the writes, on a real SQLite database.

The retirement is a compare-and-set on `events` and a relabel of `emails`; both
pass through the schema's CHECK constraints and triggers, which a mock cannot
see. The same file ran against local Supabase before the SQLite move.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from selko.services import events

ARRIVED = [{
    "provider_event_id": "imported-supercuts",
    "title": "Supercuts",
    "start_at": "2026-11-01T17:40:00+00:00",
    "end_at": "2026-11-01T18:00:00+00:00",
    "origin": "external",
    "status": "confirmed",
    "deleted_at": None,
}]


@pytest.fixture
def pending_supercuts(factory):
    user = factory.user()
    email = factory.email(
        user, subject="You're checked in at Supercuts!", from_email="noreply@supercuts.example",
        date_sent="2026-10-31T23:02:39.000000Z", provider_labels=["CATEGORY_UPDATES"],
        processing_status="processed", processing_outcome="event_created",
        processing_result={"num_new": 1, "num_events": 1, "num_updated": 0},
    )
    event = factory.event(
        user, title="Supercuts Appointment",
        start_datetime="2026-11-01T17:40:00.000000Z", end_datetime="2026-11-01T18:40:00.000000Z",
    )
    factory.event_source(event, email, source_type="new_invitation",
                         extracted_data={"title": "Supercuts Appointment"})
    return user, event, email


def _retire(db, user_id):
    with patch.object(events.event_processing, "compare_events", return_value="gcal:imported-supercuts"):
        return events.retire_pending_already_on_calendar(db, user_id, ARRIVED, MagicMock)


# Validates: SEL-158
def test_the_duplicate_leaves_new_and_history_says_why(db, factory, pending_supercuts):
    user, event, email = pending_supercuts

    assert _retire(db, user) == 1

    assert factory.row("events", event)["review_status"] == "rejected"
    row = factory.row("emails", email)
    assert row["processing_outcome"] == "event_matched"
    assert "Supercuts" in row["processing_explanation"]


def test_an_approved_event_is_not_reverted(db, factory, pending_supercuts):
    user, event, email = pending_supercuts
    with db.write() as tx:
        tx.execute("UPDATE events SET review_status = 'active', updated_at = ? WHERE id = ?",
                   (tx.now_text, event))

    assert _retire(db, user) == 0

    assert factory.row("events", event)["review_status"] == "active"
    assert factory.row("emails", email)["processing_outcome"] == "event_created"
