"""The calendar-entry hint upsert must actually work, on a real SQLite database.

The index is partial (`WHERE calendar_entry_id IS NOT NULL`). Postgres could
not infer a partial unique index from an ON CONFLICT target unless the
statement repeated the predicate (PostgREST could not), so every mirrored entry
once failed to index with SQLSTATE 42P10 while mocked unit tests passed. SQLite
has the same rule, so the real upsert is executed here.
"""

from __future__ import annotations

import uuid

from selko.db import mirror as db_mirror
from selko.db.codec import new_id


def _entry(factory, user):
    integration = factory.integration(user, provider="google_calendar", access_token="hint-upsert-probe")
    return factory._insert("calendar_entries", {
        "id": new_id(), "user_id": user, "integration_id": integration, "calendar_id": "primary",
        "provider_event_id": f"hint-probe-{uuid.uuid4().hex[:8]}",
        "ical_uid": f"hint-probe-{uuid.uuid4().hex[:8]}@example.com",
    })


def test_hint_upsert_can_infer_its_conflict_target(db, factory):
    """The upsert the mirror performs must succeed, and be idempotent."""
    user = factory.user()
    entry = _entry(factory, user)
    payload = {
        "user_id": user, "event_id": None, "calendar_entry_id": entry, "kind": "ical_uid",
        "value_hash": uuid.uuid4().hex, "recurrence_id": "", "strength": "authoritative",
    }

    db_mirror.upsert_entry_hints(db, user, [payload])
    # Running the same sync again must not raise and must not duplicate.
    db_mirror.upsert_entry_hints(db, user, [payload])

    rows = db.query("SELECT id FROM event_identity_hints WHERE calendar_entry_id = ?", (entry,))
    assert len(rows) == 1, f"expected one hint, got {len(rows)}"


def test_event_hints_are_unconstrained_by_the_calendar_index(db, factory):
    """The partial index must not collide event hints on their NULL entry column."""
    user = factory.user()
    event = factory.event(user, title="Hint probe", review_status="active")
    for _ in range(2):
        factory._insert("event_identity_hints", {
            "id": new_id(), "user_id": user, "event_id": event, "calendar_entry_id": None,
            "kind": "join_url", "value_hash": uuid.uuid4().hex, "recurrence_id": "",
            "strength": "supporting",
        })

    rows = db.query("SELECT id FROM event_identity_hints WHERE event_id = ?", (event,))
    assert len(rows) == 2, "distinct event hints must coexist despite NULL entry ids"
