"""Late calendar matches against real Postgres.

The unit tests prove the decision; these prove the writes. The retirement is a
conditional PostgREST update on `events` and a relabel of `emails`, both of
which pass through triggers and CHECK constraints a mock cannot see.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from selko.services import events


pytestmark = [pytest.mark.integration, pytest.mark.development]


@pytest.fixture
def pending_supercuts(admin_client, test_user_id):
    email_id = admin_client.table("emails").insert({
        "user_id": test_user_id,
        "provider_message_id": f"late-match-{uuid4().hex[:8]}",
        "subject": "You're checked in at Supercuts!",
        "from_email": "noreply@supercuts.example",
        "date_sent": "2026-10-31T23:02:39Z",
        "provider_labels": ["CATEGORY_UPDATES"],
        "processing_status": "processed",
        "processing_outcome": "event_created",
        "processing_result": {"num_new": 1, "num_events": 1, "num_updated": 0},
    }).execute().data[0]["id"]
    event_id = admin_client.table("events").insert({
        "user_id": test_user_id,
        "title": "Supercuts Appointment",
        "start_datetime": "2026-11-01T17:40:00+00:00",
        "end_datetime": "2026-11-01T18:40:00+00:00",
        "review_status": "pending_review",
    }).execute().data[0]["id"]
    admin_client.table("event_sources").insert({
        "event_id": event_id,
        "email_id": email_id,
        "source_origin": "email",
        "source_type": "new_invitation",
        "extracted_data": {"title": "Supercuts Appointment"},
    }).execute()
    try:
        yield event_id, email_id
    finally:
        admin_client.table("events").delete().eq("id", event_id).execute()
        admin_client.table("emails").delete().eq("id", email_id).execute()


ARRIVED = [{
    "provider_event_id": "imported-supercuts",
    "title": "Supercuts",
    "start_at": "2026-11-01T17:40:00+00:00",
    "end_at": "2026-11-01T18:00:00+00:00",
    "origin": "external",
    "status": "confirmed",
    "deleted_at": None,
}]


def _retire(admin_client, user_id):
    with patch.object(events.event_processing, "compare_events", return_value="gcal:imported-supercuts"):
        return events.retire_pending_already_on_calendar(admin_client, user_id, ARRIVED, MagicMock)


def test_the_duplicate_leaves_new_and_history_says_why(admin_client, test_user_id, pending_supercuts):
    event_id, email_id = pending_supercuts

    assert _retire(admin_client, test_user_id) == 1

    event = admin_client.table("events").select("review_status").eq("id", event_id).single().execute().data
    assert event["review_status"] == "rejected"
    email = admin_client.table("emails").select(
        "processing_outcome,processing_explanation"
    ).eq("id", email_id).single().execute().data
    assert email["processing_outcome"] == "event_matched"
    assert "Supercuts" in email["processing_explanation"]


def test_an_approved_event_is_not_reverted(admin_client, test_user_id, pending_supercuts):
    event_id, email_id = pending_supercuts
    admin_client.table("events").update({"review_status": "active"}).eq("id", event_id).execute()

    assert _retire(admin_client, test_user_id) == 0

    event = admin_client.table("events").select("review_status").eq("id", event_id).single().execute().data
    assert event["review_status"] == "active"
    email = admin_client.table("emails").select("processing_outcome").eq("id", email_id).single().execute().data
    assert email["processing_outcome"] == "event_created"
