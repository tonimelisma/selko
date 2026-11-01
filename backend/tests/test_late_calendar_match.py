"""A calendar entry that arrives after its email must still retire the duplicate.

Production, 2026-10-31: a "You're checked in at Supercuts!" email was extracted
at 23:05Z into a pending "Supercuts Appointment" at 17:40Z the next day. The
user's own "Supercuts" entry at 17:40Z sat on an imported calendar that Google
refreshed later; it reached the mirror at 00:30Z. Dedup had already run, and
nothing ran again, so both stayed visible.
"""

from __future__ import annotations

import inspect
from typing import Any
from unittest.mock import MagicMock, patch

from selko.services import events


class _Query:
    def __init__(self, client: "_FakeClient", table: str):
        self.client = client
        self.table = table
        self.op = "select"
        self.payload: Any = None
        self.filters: list[tuple] = []

    def select(self, *_args, **_kwargs):
        return self

    def update(self, payload):
        self.op = "update"
        self.payload = payload
        return self

    def eq(self, column, value):
        self.filters.append(("eq", column, value))
        return self

    def gte(self, column, value):
        self.filters.append(("gte", column, value))
        return self

    def lte(self, column, value):
        self.filters.append(("lte", column, value))
        return self

    @property
    def not_(self):
        return self

    def is_(self, column, value):
        self.filters.append(("not_is", column, value))
        return self

    def maybe_single(self):
        self.op = "maybe_single"
        return self

    def execute(self):
        self.client.calls.append(self)
        return MagicMock(data=self.client.respond(self))


class _FakeClient:
    """Answers the handful of queries the retirement path makes."""

    def __init__(self, pending, *, update_wins=True, email=None):
        self.pending = pending
        self.update_wins = update_wins
        self.email = email
        self.calls: list[_Query] = []

    def table(self, name):
        return _Query(self, name)

    def respond(self, query: _Query):
        if query.table == "events" and query.op == "select":
            return self.pending
        if query.table == "events" and query.op == "update":
            return [{"id": dict((c, v) for _, c, v in query.filters)["id"]}] if self.update_wins else []
        if query.table == "event_sources":
            return [{"email_id": "email-1"}] if self.email else []
        if query.table == "emails" and query.op == "maybe_single":
            return self.email
        return []

    def updates(self, table):
        return [q for q in self.calls if q.table == table and q.op == "update"]


SUPERCUTS_EVENT = {
    "id": "evt-supercuts",
    "title": "Supercuts Appointment",
    "start_datetime": "2026-11-01T17:40:00+00:00",
    "end_datetime": "2026-11-01T18:40:00+00:00",
    "location": "3000 DANVILLE BLVD STE C, ALAMO, California 94507",
    "description": "Haircut appointment at Supercuts.",
}

SUPERCUTS_ENTRY = {
    "provider_event_id": "imported-supercuts",
    "title": "Supercuts",
    "start_at": "2026-11-01T17:40:00+00:00",
    "end_at": "2026-11-01T18:00:00+00:00",
    "location": "3000 DANVILLE BLVD STE C, ALAMO, CA 94507",
    "origin": "external",
    "status": "confirmed",
    "deleted_at": None,
}

CHECK_IN_EMAIL = {
    "id": "email-1",
    "processing_outcome": "event_created",
    "processing_result": {"num_new": 1, "num_events": 1, "num_updated": 0},
}


def _retire(client, arrived, matched_id):
    gateway_factory = MagicMock()
    with patch.object(events.event_processing, "compare_events", return_value=matched_id) as compare, \
            patch.object(events, "get_user_timezone", return_value="America/Los_Angeles"):
        retired = events.retire_pending_already_on_calendar(client, "user-1", arrived, gateway_factory)
    return retired, compare, gateway_factory


def test_the_supercuts_duplicate_leaves_new_when_its_calendar_entry_arrives():
    client = _FakeClient([SUPERCUTS_EVENT], email=CHECK_IN_EMAIL)

    retired, compare, _ = _retire(client, [SUPERCUTS_ENTRY], "gcal:imported-supercuts")

    assert retired == 1
    # The end times differ (the model guessed an hour; the entry is 20 min), so
    # an exact start/end match would have missed it. Start is the gate, the
    # comparison decides.
    compare.assert_called_once()
    (update,) = client.updates("events")
    assert update.payload["review_status"] == "rejected"
    assert ("eq", "review_status", "pending_review") in update.filters, (
        "the update must be conditional, or an event approved meanwhile is undone"
    )
    (relabel,) = client.updates("emails")
    assert relabel.payload["processing_outcome"] == "event_matched"
    assert "Supercuts" in relabel.payload["processing_explanation"]


def test_a_different_start_minute_costs_no_llm_call():
    client = _FakeClient([SUPERCUTS_EVENT])
    elsewhere = {**SUPERCUTS_ENTRY, "start_at": "2026-11-01T17:45:00+00:00"}

    retired, compare, gateway_factory = _retire(client, [elsewhere], "gcal:imported-supercuts")

    assert retired == 0
    compare.assert_not_called()
    gateway_factory.assert_not_called()
    assert not client.updates("events")


def test_a_different_event_at_the_same_minute_stays_in_new():
    client = _FakeClient([SUPERCUTS_EVENT])
    dentist = {**SUPERCUTS_ENTRY, "provider_event_id": "dentist", "title": "Dentist"}

    retired, compare, _ = _retire(client, [dentist], None)

    assert retired == 0
    compare.assert_called_once()
    assert not client.updates("events")


def test_selko_s_own_and_removed_entries_are_not_evidence():
    client = _FakeClient([SUPERCUTS_EVENT])
    arrived = [
        {**SUPERCUTS_ENTRY, "origin": "selko_created"},
        {**SUPERCUTS_ENTRY, "deleted_at": "2026-11-01T00:00:00+00:00", "status": "cancelled"},
    ]

    retired, compare, _ = _retire(client, arrived, "gcal:imported-supercuts")

    assert retired == 0
    compare.assert_not_called()
    assert client.calls == [], "nothing qualified, so nothing should be queried"


def test_an_event_the_user_approved_meanwhile_is_left_alone():
    client = _FakeClient([SUPERCUTS_EVENT], update_wins=False, email=CHECK_IN_EMAIL)

    retired, _, _ = _retire(client, [SUPERCUTS_ENTRY], "gcal:imported-supercuts")

    assert retired == 0
    assert not client.updates("emails"), "History must not claim a match that did not apply"


def test_an_email_that_also_created_other_events_keeps_its_outcome():
    email = {**CHECK_IN_EMAIL, "processing_result": {"num_new": 2, "num_events": 2, "num_updated": 0}}
    client = _FakeClient([SUPERCUTS_EVENT], email=email)

    retired, _, _ = _retire(client, [SUPERCUTS_ENTRY], "gcal:imported-supercuts")

    assert retired == 1
    assert not client.updates("emails")


def test_a_failed_comparison_retires_nothing():
    client = _FakeClient([SUPERCUTS_EVENT])
    with patch.object(events.event_processing, "compare_events", side_effect=RuntimeError("down")), \
            patch.object(events, "get_user_timezone", return_value="America/Los_Angeles"):
        retired = events.retire_pending_already_on_calendar(
            client, "user-1", [SUPERCUTS_ENTRY], MagicMock()
        )

    assert retired == 0
    assert not client.updates("events")


def test_the_mirror_hands_back_what_each_pass_wrote():
    from selko.services import calendar_mirror

    def fake_sync(client, user_id, integration_id, calendar_id, **kwargs):
        return {"entries": 1, "full_resync": False, "has_sync_token": True,
                "arrived": [{"provider_event_id": calendar_id}]}

    with patch.object(calendar_mirror, "list_calendars",
                      return_value=[{"id": "me@example.com"}, {"id": "imported@example.com"}]), \
            patch.object(calendar_mirror, "sync_calendar", side_effect=fake_sync):
        totals = calendar_mirror.sync_all_calendars(MagicMock(), "u1", "i1")

    assert [e["provider_event_id"] for e in totals["arrived"]] == [
        "me@example.com", "imported@example.com",
    ]


def test_the_runtime_retires_duplicates_after_every_mirror_sync():
    """A function nobody calls has not shipped (CLAUDE.md, call-site rule)."""
    from selko.workers.ingestion_runtime import IngestionRuntime

    loop = inspect.getsource(IngestionRuntime._calendar_mirror_floor)
    assert "retire_pending_already_on_calendar" in loop
    assert loop.index("sync_all_calendars") < loop.index("retire_pending_already_on_calendar")
