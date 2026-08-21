"""Real-Postgres acceptance tests for the C3 cancellation state machine."""

import pytest

from selko.services.events import (
    claim_approved_event_for_sync,
    complete_event_cancellation,
    complete_event_sync,
)


@pytest.mark.integration
@pytest.mark.development
class TestAutomaticCancellation:
    @pytest.fixture(autouse=True)
    def active_calendar_integration(self, admin_client, temp_user):
        test_user_id = temp_user[0]
        admin_client.table("integrations").upsert(
            {
                "user_id": test_user_id,
                "provider": "google_calendar",
                "status": "active",
                "access_token": "c3-test-token",
            },
            on_conflict="user_id,provider",
        ).execute()
        yield
        admin_client.table("integrations").delete().eq(
            "user_id", test_user_id
        ).eq("provider", "google_calendar").execute()

    async def test_cancel_claim_and_completion_are_worker_owned(
        self, admin_client, temp_user, pg_pool
    ):
        test_user_id = temp_user[0]
        event = admin_client.table("events").insert(
            {
                "user_id": test_user_id,
                "title": "Original title",
                "start_datetime": "2026-09-01T14:00:00Z",
                "end_datetime": "2026-09-01T15:00:00Z",
                "status": "approved",
                "google_calendar_event_id": "google-c3-event",
            }
        ).execute().data[0]
        event_id = event["id"]

        queued = admin_client.rpc("queue_event_cancellation", {
            "p_event_id": event_id,
            "p_user_id": test_user_id,
        }).execute().data
        assert queued["status"] == "cancel_queued"
        work_item = admin_client.table("calendar_work_items").select(
            "status,action,generation"
        ).eq("id", queued["work_item_id"]).single().execute().data
        assert work_item == {"status": "pending", "action": "cancel", "generation": 1}

        claimed = await claim_approved_event_for_sync(pg_pool, "c3-worker")
        assert claimed is not None
        assert str(claimed["id"]) == event_id
        assert claimed["status"] == "syncing"
        assert claimed["calendar_work_item_action"] == "cancel"
        lease = claimed["calendar_work_lease"]

        completed = await complete_event_cancellation(
            pg_pool, lease
        )
        assert completed is True
        final = admin_client.table("events").select(
            "status,title,google_calendar_event_id"
        ).eq("id", event_id).single().execute().data
        assert final == {
            "status": "cancelled",
            "title": "Original title",
            "google_calendar_event_id": None,
        }

    async def test_stale_upsert_completion_cannot_reset_cancellation(
        self, admin_client, temp_user, pg_pool
    ):
        test_user_id = temp_user[0]
        event_id = admin_client.table("events").insert(
            {
                "user_id": test_user_id,
                "title": "Race event",
                "start_datetime": "2026-09-02T14:00:00Z",
                "status": "approved",
                "google_calendar_event_id": "google-race-event",
            }
        ).execute().data[0]["id"]
        admin_client.rpc("enqueue_calendar_work", {
            "p_event_id": event_id,
            "p_user_id": test_user_id,
            "p_action": "upsert",
            "p_desired_event": {"title": "Race event"},
        }).execute()
        claimed = await claim_approved_event_for_sync(pg_pool, "upsert-worker")
        assert claimed is not None
        old_lease = claimed["calendar_work_lease"]

        # Superseding an actively leased item is the authoritative race
        # transition; the user-facing cancellation RPC intentionally rejects
        # a syncing projection rather than mutating it underneath its worker.
        admin_client.rpc("enqueue_calendar_work", {
            "p_event_id": event_id,
            "p_user_id": test_user_id,
            "p_action": "cancel",
            "p_desired_event": None,
        }).execute()

        completed = await complete_event_sync(
            pg_pool, old_lease, "google-race-event"
        )
        assert completed is False
        row = admin_client.table("events").select("status").eq(
            "id", event_id
        ).single().execute().data
        assert row["status"] == "cancel_queued"
