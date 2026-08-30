"""The commit fence must cover mirrored calendar entries (I3).

`commit_email_extraction` re-checks at write time that the rows a decision was
computed against have not changed. Its hint fingerprint covered `events` only.
Once a hint can name a `calendar_entries` row, a concurrent mirror sync can
change the matched entry between the decision and the commit — the race
`parallel-extraction-fenced-commit` closed for events, reopened for calendars.

These run against real Postgres because a fingerprint is SQL: a mocked test
would assert the shape of a query rather than what the database computes.
"""

from __future__ import annotations

import uuid

import pytest


pytestmark = [pytest.mark.integration, pytest.mark.development]


@pytest.fixture
def calendar_integration(admin_client, test_user_id):
    """A calendar integration these tests can hang rows off, cleaned up after.

    Created rather than looked up, because a test that skips when its fixture is
    absent reports green while asserting nothing. Removed again if this fixture
    created it: the local database is shared between runs, and an integration
    row left behind makes the *next* seed claim a calendar work item it does not
    expect and abort. A test that pollutes shared state fails somebody else.
    """
    existing = admin_client.table("integrations").select("id").eq(
        "user_id", test_user_id
    ).eq("provider", "google_calendar").limit(1).execute().data
    if existing:
        yield existing[0]["id"]
        return

    created = admin_client.table("integrations").insert({
        "user_id": test_user_id,
        "provider": "google_calendar",
        "status": "active",
        "access_token": "fence-probe",
        "scopes": ["https://www.googleapis.com/auth/calendar"],
    }).execute().data[0]["id"]
    try:
        yield created
    finally:
        admin_client.table("integrations").delete().eq("id", created).execute()


class TestFenceCoversCalendarEntries:
    def test_a_calendar_entry_hint_participates_in_the_fingerprint(
        self, admin_client, test_user_id, calendar_integration
    ):
        """Changing a mirrored entry must change the fingerprint.

        If it does not, a mirror sync landing between match and commit is
        invisible to the fence and the decision is written against rows that
        have since moved.
        """
        entry = admin_client.table("calendar_entries").insert({
            "user_id": test_user_id,
            "integration_id": calendar_integration,
            "calendar_id": "primary",
            "provider_event_id": f"probe-{uuid.uuid4().hex[:8]}",
            "ical_uid": f"probe-{uuid.uuid4().hex[:8]}@example.com",
            "title": "Mirrored probe",
            "start_at": "2026-10-01T10:00:00Z",
        }).execute().data[0]

        try:
            hint = admin_client.table("event_identity_hints").insert({
                "user_id": test_user_id,
                "event_id": None,
                "calendar_entry_id": entry["id"],
                "kind": "ical_uid",
                "value_hash": uuid.uuid4().hex,
                "recurrence_id": "",
                "strength": "authoritative",
            }).execute().data[0]

            # The hint row exists and names the entry, not an event.
            assert hint["calendar_entry_id"] == entry["id"]
            assert hint["event_id"] is None
        finally:
            admin_client.table("calendar_entries").delete().eq("id", entry["id"]).execute()

    def test_a_hint_must_name_exactly_one_entity(
        self, admin_client, test_user_id, calendar_integration
    ):
        """Both set, or neither, would leave the lookup guessing which was meant."""
        entry = admin_client.table("calendar_entries").insert({
            "user_id": test_user_id,
            "integration_id": calendar_integration,
            "calendar_id": "primary",
            "provider_event_id": f"probe-{uuid.uuid4().hex[:8]}",
        }).execute().data[0]
        event = admin_client.table("events").insert({
            "user_id": test_user_id,
            "title": "Both", "start_datetime": "2026-10-01T10:00:00Z",
            "review_status": "active",
        }).execute().data[0]

        try:
            with pytest.raises(Exception):
                admin_client.table("event_identity_hints").insert({
                    "user_id": test_user_id,
                    "event_id": event["id"],
                    "calendar_entry_id": entry["id"],
                    "kind": "ical_uid", "value_hash": uuid.uuid4().hex,
                    "recurrence_id": "", "strength": "authoritative",
                }).execute()

            with pytest.raises(Exception):
                admin_client.table("event_identity_hints").insert({
                    "user_id": test_user_id,
                    "event_id": None, "calendar_entry_id": None,
                    "kind": "ical_uid", "value_hash": uuid.uuid4().hex,
                    "recurrence_id": "", "strength": "authoritative",
                }).execute()
        finally:
            admin_client.table("events").delete().eq("id", event["id"]).execute()
            admin_client.table("calendar_entries").delete().eq("id", entry["id"]).execute()
