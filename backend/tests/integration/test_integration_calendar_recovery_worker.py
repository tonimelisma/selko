"""Integration tests for the calendar recovery worker RPCs.

Covers docs/specs/oauth-reconnect-catch-up.md section 3 (Calendar) regression
coverage: only oauth_required/oauth_scope_required blocked events get tagged,
quota/validation/permission/unknown failures are left untouched, and progress
finalizes once every tagged event reaches a terminal state.
"""

import asyncio
import pytest

from selko.services.calendars import (
    refresh_waiting_calendar_recoveries,
    requeue_calendar_recovery_batch,
)
from selko.services.integrations import (
    claim_integration_recovery,
    complete_integration_reauthorization,
)


@pytest.fixture
def test_user_id(isolated_user):
    """Use a throwaway user for recovery claim/lease tests."""
    return isolated_user["id"]


@pytest.fixture(autouse=True)
def _cleanup(admin_client, test_user_id):
    def _clear():
        # Remove every event for the test user: other suites (e.g. the
        # calendar sync tests, which have no cleanup of their own) can leave
        # approved + oauth_required rows behind, and requeue_calendar_
        # recovery_batch would tag them and skew this suite's counts.
        admin_client.table("events").delete().eq("user_id", test_user_id).execute()
        admin_client.table("integration_recoveries").delete().eq(
            "user_id", test_user_id
        ).execute()
        admin_client.table("integrations").delete().eq(
            "user_id", test_user_id
        ).eq("provider", "google_calendar").execute()

    _clear()
    yield
    _clear()


def _make_blocked_event(admin_client, user_id, failure_code="oauth_required"):
    result = (
        admin_client.table("events")
        .insert({
            "user_id": user_id,
            "title": "Recovery worker test event",
            "start_datetime": "2026-05-01T14:00:00Z",
            "review_status": "active",
        })
        .execute()
    )
    event_id = result.data[0]["id"]
    admin_client.rpc("enqueue_calendar_work", {
        "p_event_id": event_id,
        "p_user_id": user_id,
        "p_action": "upsert",
        "p_desired_event": {"title": "Recovery worker test event"},
    }).execute()
    if failure_code is not None:
        admin_client.table("calendar_work_items").update({
            "failure_code": failure_code,
            "status": "failed",
        }).eq("event_id", event_id).execute()
    return event_id


async def _create_and_claim_recovery(admin_client, user_id, pg_pool):
    complete_integration_reauthorization(
        admin_client,
        user_id=user_id,
        provider="google_calendar",
        access_token="access-1",
        refresh_token="refresh-1",
        token_expiry=None,
        scopes=["calendar"],
        provider_email=None,
    )
    return await claim_integration_recovery(pg_pool, "worker-1", lock_seconds=120)


@pytest.mark.integration
@pytest.mark.development
class TestRequeueCalendarRecoveryBatch:
    async def test_tags_only_oauth_blocked_approved_events(self, admin_client, test_user_id, pg_pool):
        oauth_event_id = _make_blocked_event(admin_client, test_user_id, "oauth_required")
        scope_event_id = _make_blocked_event(admin_client, test_user_id, "oauth_scope_required")
        untouched_event_id = _make_blocked_event(admin_client, test_user_id, "permission_denied")
        no_code_event_id = _make_blocked_event(admin_client, test_user_id, None)

        recovery = await _create_and_claim_recovery(admin_client, test_user_id, pg_pool)
        tagged = await requeue_calendar_recovery_batch(
            pg_pool, recovery["id"], "worker-1"
        )
        assert tagged == 2

        tagged_ids = {
            row["id"]
            for row in admin_client.table("events")
            .select("id")
            .eq("recovery_id", recovery["id"])
            .execute()
            .data
        }
        assert tagged_ids == {oauth_event_id, scope_event_id}
        assert untouched_event_id not in tagged_ids
        assert no_code_event_id not in tagged_ids

        for stray_id in (untouched_event_id, no_code_event_id):
            admin_client.table("events").delete().eq("id", stray_id).execute()

    async def test_returns_negative_one_when_claim_lost(self, admin_client, test_user_id, pg_pool):
        recovery = await _create_and_claim_recovery(admin_client, test_user_id, pg_pool)

        result = await requeue_calendar_recovery_batch(
            pg_pool, recovery["id"], "a-different-worker"
        )

        assert result == -1

    async def test_reclaims_processing_recovery_with_expired_lock(
        self, admin_client, test_user_id, pg_pool
    ):
        """A crashed worker's claim (processing + expired lock) must be reclaimed
        on the next claim instead of waiting for an API restart (#239 was startup
        only; the claim itself must self-heal)."""
        recovery = await _create_and_claim_recovery(admin_client, test_user_id, pg_pool)

        admin_client.table("integration_recoveries").update(
            {
                "locked_until": "2020-01-01T00:00:00Z",
            }
        ).eq("id", recovery["id"]).execute()

        reclaimed = await claim_integration_recovery(
            pg_pool, "worker-2", lock_seconds=120
        )

        assert reclaimed is not None
        assert str(reclaimed["id"]) == str(recovery["id"])
        assert reclaimed["status"] == "processing"
        assert reclaimed["locked_by"] == "worker-2"
        assert reclaimed["attempts"] == 2

    async def test_finalizes_completed_once_tagged_events_synced(
        self, admin_client, test_user_id, pg_pool
    ):
        event_id = _make_blocked_event(admin_client, test_user_id)
        recovery = await _create_and_claim_recovery(admin_client, test_user_id, pg_pool)
        await requeue_calendar_recovery_batch(pg_pool, recovery["id"], "worker-1")

        # Simulate the normal calendar worker syncing the tagged event.
        admin_client.table("calendar_work_items").update({
            "status": "succeeded",
            "provider_event_id": "recovered-google-event",
        }).eq("event_id", event_id).execute()

        await refresh_waiting_calendar_recoveries(pg_pool)

        row = (
            admin_client.table("integration_recoveries")
            .select("status, completed_count, remaining_count")
            .eq("id", recovery["id"])
            .single()
            .execute()
        )
        assert row.data["status"] == "completed"
        assert row.data["completed_count"] == 1
        assert row.data["remaining_count"] == 0

    async def test_finalizes_completed_with_errors_when_a_tagged_event_fails(
        self, admin_client, test_user_id, pg_pool
    ):
        event_id = _make_blocked_event(admin_client, test_user_id)
        recovery = await _create_and_claim_recovery(admin_client, test_user_id, pg_pool)
        await requeue_calendar_recovery_batch(pg_pool, recovery["id"], "worker-1")

        # Simulate the normal calendar worker permanently failing the event
        # for a non-OAuth reason after recovery tagged it.
        admin_client.table("calendar_work_items").update(
            {"failure_code": "invalid_event", "status": "failed"}
        ).eq("event_id", event_id).execute()

        await refresh_waiting_calendar_recoveries(pg_pool)

        row = (
            admin_client.table("integration_recoveries")
            .select("status")
            .eq("id", recovery["id"])
            .single()
            .execute()
        )
        assert row.data["status"] == "completed_with_errors"

    async def test_still_waiting_while_tagged_event_is_unresolved(
        self, admin_client, test_user_id, pg_pool
    ):
        _make_blocked_event(admin_client, test_user_id)
        recovery = await _create_and_claim_recovery(admin_client, test_user_id, pg_pool)
        await requeue_calendar_recovery_batch(pg_pool, recovery["id"], "worker-1")

        row = (
            admin_client.table("integration_recoveries")
            .select("status, remaining_count")
            .eq("id", recovery["id"])
            .single()
            .execute()
        )
        assert row.data["status"] == "waiting"
        assert row.data["remaining_count"] == 1
