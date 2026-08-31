"""The calendar-entry hint upsert must actually work against real Postgres.

The index was created partial (`WHERE calendar_entry_id IS NOT NULL`), and
PostgreSQL cannot infer a partial unique index from an ON CONFLICT target unless
the statement repeats the predicate -- which PostgREST cannot express. Every
mirrored entry failed to index with SQLSTATE 42P10 while the unit tests, which
mock the client, passed.

Only a real database can see this: the failure is in what Postgres will accept,
not in what the code intends.
"""

from __future__ import annotations

import uuid

import pytest


pytestmark = [pytest.mark.integration, pytest.mark.development]


@pytest.fixture
def calendar_entry(admin_client, test_user_id):
    integration = admin_client.table("integrations").select("id").eq(
        "user_id", test_user_id
    ).eq("provider", "google_calendar").limit(1).execute().data
    created_integration = None
    if integration:
        integration_id = integration[0]["id"]
    else:
        created_integration = admin_client.table("integrations").insert({
            "user_id": test_user_id, "provider": "google_calendar", "status": "active",
            "access_token": "hint-upsert-probe",
            "scopes": ["https://www.googleapis.com/auth/calendar"],
        }).execute().data[0]["id"]
        integration_id = created_integration

    entry = admin_client.table("calendar_entries").insert({
        "user_id": test_user_id,
        "integration_id": integration_id,
        "calendar_id": "primary",
        "provider_event_id": f"hint-probe-{uuid.uuid4().hex[:8]}",
        "ical_uid": f"hint-probe-{uuid.uuid4().hex[:8]}@example.com",
    }).execute().data[0]
    try:
        yield entry
    finally:
        admin_client.table("calendar_entries").delete().eq("id", entry["id"]).execute()
        if created_integration:
            admin_client.table("integrations").delete().eq("id", created_integration).execute()


def test_hint_upsert_can_infer_its_conflict_target(admin_client, test_user_id, calendar_entry):
    """The upsert the mirror performs must succeed, and be idempotent."""
    payload = {
        "user_id": test_user_id,
        "event_id": None,
        "calendar_entry_id": calendar_entry["id"],
        "kind": "ical_uid",
        "value_hash": uuid.uuid4().hex,
        "recurrence_id": "",
        "strength": "authoritative",
    }

    admin_client.table("event_identity_hints").upsert(
        [payload], on_conflict="calendar_entry_id,kind,value_hash,recurrence_id"
    ).execute()

    # Running the same sync again must not raise and must not duplicate.
    admin_client.table("event_identity_hints").upsert(
        [payload], on_conflict="calendar_entry_id,kind,value_hash,recurrence_id"
    ).execute()

    rows = admin_client.table("event_identity_hints").select("id").eq(
        "calendar_entry_id", calendar_entry["id"]
    ).execute().data
    assert len(rows) == 1, f"expected one hint, got {len(rows)}"


def test_event_hints_are_unconstrained_by_the_calendar_index(admin_client, test_user_id):
    """A non-partial index must not collide event hints on their NULL column.

    NULL is distinct from NULL in a unique index, which is why the predicate was
    unnecessary -- but that only holds if it is actually true here.
    """
    event = admin_client.table("events").insert({
        "user_id": test_user_id, "title": "Hint probe",
        "start_datetime": "2026-10-01T10:00:00Z", "review_status": "active",
    }).execute().data[0]
    try:
        for _ in range(2):
            admin_client.table("event_identity_hints").insert({
                "user_id": test_user_id,
                "event_id": event["id"],
                "calendar_entry_id": None,
                "kind": "join_url",
                "value_hash": uuid.uuid4().hex,
                "recurrence_id": "",
                "strength": "supporting",
            }).execute()
        rows = admin_client.table("event_identity_hints").select("id").eq(
            "event_id", event["id"]
        ).execute().data
        assert len(rows) == 2, "distinct event hints must coexist despite NULL entry ids"
    finally:
        admin_client.table("events").delete().eq("id", event["id"]).execute()
