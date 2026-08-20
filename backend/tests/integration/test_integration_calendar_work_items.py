"""Real-Postgres contracts for the S2 calendar work-item owner."""

from datetime import datetime, timedelta, timezone

import pytest

from selko.services.events import (
    claim_approved_event_for_sync,
    complete_event_cancellation,
    complete_event_sync,
)


pytestmark = [pytest.mark.integration, pytest.mark.development]


def _desired(title: str = "S2 event") -> dict:
    return {
        "title": title,
        "start_datetime": "2026-09-01T14:00:00Z",
        "end_datetime": "2026-09-01T15:00:00Z",
        "all_day": False,
        "location": "Test room",
        "description": "S2 integration probe",
        "importance": "action_required",
        "source_attribution": None,
    }


@pytest.mark.asyncio
async def test_enqueue_claim_complete_is_item_fenced(
    admin_client, temp_user, pg_pool
):
    user_id = temp_user[0]
    admin_client.table("integrations").upsert(
        {
            "user_id": user_id,
            "provider": "google_calendar",
            "status": "active",
            "access_token": "s2-test-token",
        },
        on_conflict="user_id,provider",
    ).execute()
    event_id = admin_client.table("events").insert(
        {
            "user_id": user_id,
            "title": "S2 event",
            "start_datetime": "2026-09-01T14:00:00Z",
            "end_datetime": "2026-09-01T15:00:00Z",
            "status": "pending_review",
        }
    ).execute().data[0]["id"]

    queued = admin_client.rpc("enqueue_calendar_work", {
        "p_event_id": event_id,
        "p_user_id": user_id,
        "p_action": "upsert",
        "p_desired_event": _desired(),
        "p_expected_provider_revision": None,
        "p_force_overwrite": False,
    }).execute().data
    item_id = queued["id"] if isinstance(queued, dict) else queued[0]["id"]

    claimed = await claim_approved_event_for_sync(pg_pool, "s2-worker")
    assert claimed is not None
    assert str(claimed["id"]) == event_id
    assert claimed["calendar_work_item_id"] == str(item_id)
    assert claimed["status"] == "syncing"

    assert await complete_event_sync(
        pg_pool, item_id, "google-s2-event", "s2-worker",
        int(claimed["calendar_work_generation"]),
    ) is True
    final = admin_client.table("events").select(
        "status,review_status,google_calendar_event_id"
    ).eq("id", event_id).single().execute().data
    assert final == {
        "status": "synced",
        "review_status": "active",
        "google_calendar_event_id": "google-s2-event",
    }


@pytest.mark.asyncio
async def test_new_enqueue_supersedes_old_and_stale_completion_is_fenced(
    admin_client, temp_user, pg_pool
):
    user_id = temp_user[0]
    admin_client.table("integrations").upsert(
        {
            "user_id": user_id,
            "provider": "google_calendar",
            "status": "active",
            "access_token": "s2-test-token",
        },
        on_conflict="user_id,provider",
    ).execute()
    event_id = admin_client.table("events").insert(
        {"user_id": user_id, "title": "Race", "status": "pending_review"}
    ).execute().data[0]["id"]
    first = admin_client.rpc("enqueue_calendar_work", {
        "p_event_id": event_id, "p_user_id": user_id, "p_action": "upsert",
        "p_desired_event": _desired("first"), "p_expected_provider_revision": None,
        "p_force_overwrite": False,
    }).execute().data
    first_id = first["id"] if isinstance(first, dict) else first[0]["id"]
    claimed = await claim_approved_event_for_sync(pg_pool, "old-worker")
    assert claimed is not None
    generation = int(claimed["calendar_work_generation"])

    second = admin_client.rpc("enqueue_calendar_work", {
        "p_event_id": event_id, "p_user_id": user_id, "p_action": "cancel",
        "p_desired_event": None, "p_expected_provider_revision": None,
        "p_force_overwrite": False,
    }).execute().data
    second_id = second["id"] if isinstance(second, dict) else second[0]["id"]
    assert str(first_id) != str(second_id)
    assert await complete_event_sync(
        pg_pool, first_id, "stale-google-event", "old-worker", generation
    ) is False
    row = admin_client.table("events").select(
        "status,calendar_sync_action"
    ).eq("id", event_id).single().execute().data
    assert row == {"status": "cancel_queued", "calendar_sync_action": "cancel"}


@pytest.mark.asyncio
async def test_expired_processing_item_is_reclaimable(
    admin_client, temp_user, pg_pool
):
    user_id = temp_user[0]
    admin_client.table("integrations").upsert(
        {
            "user_id": user_id,
            "provider": "google_calendar",
            "status": "active",
            "access_token": "s2-test-token",
        },
        on_conflict="user_id,provider",
    ).execute()
    event_id = admin_client.table("events").insert(
        {"user_id": user_id, "title": "Expired", "status": "pending_review"}
    ).execute().data[0]["id"]
    queued = admin_client.rpc("enqueue_calendar_work", {
        "p_event_id": event_id, "p_user_id": user_id, "p_action": "upsert",
        "p_desired_event": _desired("expired"), "p_expected_provider_revision": None,
        "p_force_overwrite": False,
    }).execute().data
    item_id = queued["id"] if isinstance(queued, dict) else queued[0]["id"]
    claimed = await claim_approved_event_for_sync(pg_pool, "crashed-worker", 1)
    assert claimed is not None
    admin_client.table("calendar_work_items").update({
        "locked_until": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
    }).eq("id", item_id).execute()
    reclaimed = await claim_approved_event_for_sync(pg_pool, "reclaimer", 60)
    assert reclaimed is not None
    assert reclaimed["calendar_work_item_id"] == str(item_id)
    assert reclaimed["locked_by"] == "reclaimer"


@pytest.mark.asyncio
async def test_unsync_is_worker_owned_and_clears_remote_identity_on_completion(
    admin_client, temp_user, pg_pool
):
    user_id = temp_user[0]
    admin_client.table("integrations").upsert(
        {
            "user_id": user_id,
            "provider": "google_calendar",
            "status": "active",
            "access_token": "s2-test-token",
        },
        on_conflict="user_id,provider",
    ).execute()
    event_id = admin_client.table("events").insert(
        {
            "user_id": user_id,
            "title": "Unsync me",
            "status": "synced",
            "google_calendar_event_id": "google-delete-me",
        }
    ).execute().data[0]["id"]

    queued = admin_client.rpc("unsync_event_and_enqueue_calendar_work", {
        "p_event_id": event_id,
        "p_user_id": user_id,
        "p_expected_provider_revision": None,
        "p_force_overwrite": False,
    }).execute().data
    assert queued["status"] == "pending_review"

    claimed = await claim_approved_event_for_sync(pg_pool, "unsync-worker")
    assert claimed is not None
    assert claimed["calendar_sync_action"] == "cancel"
    assert claimed["calendar_work_desired_event"] == {"delete_remote": True}

    assert await complete_event_cancellation(
        pg_pool,
        event_id,
        "unsync-worker",
        int(claimed["calendar_work_generation"]),
    ) is True
    final = admin_client.table("events").select(
        "status,review_status,google_calendar_event_id,synced_at"
    ).eq("id", event_id).single().execute().data
    assert final["status"] == "pending_review"
    assert final["review_status"] == "pending_review"
    assert final["google_calendar_event_id"] is None
    assert final["synced_at"] is None
