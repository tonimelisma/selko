"""Integration tests for the calendar recovery worker RPCs.

Covers docs/specs/oauth-reconnect-catch-up.md section 3 (Calendar) regression
coverage: only oauth_required/oauth_scope_required blocked events get tagged,
quota/validation/permission/unknown failures are left untouched, and progress
finalizes once every tagged event reaches a terminal state.
"""

import pytest

from selko.services.calendars import (
    refresh_waiting_calendar_recoveries,
    requeue_calendar_recovery_batch,
)
from selko.services.integrations import (
    claim_integration_recovery,
    complete_integration_reauthorization,
)


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


def _make_blocked_event(admin_client, user_id, sync_failure_code="oauth_required"):
    result = (
        admin_client.table("events")
        .insert({
            "user_id": user_id,
            "title": "Recovery worker test event",
            "start_datetime": "2026-05-01T14:00:00Z",
            "status": "approved",
            "sync_failure_code": sync_failure_code,
        })
        .execute()
    )
    return result.data[0]["id"]


def _create_and_claim_recovery(admin_client, user_id):
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
    return claim_integration_recovery(admin_client, "worker-1", lock_seconds=120)


@pytest.mark.integration
@pytest.mark.development
class TestRequeueCalendarRecoveryBatch:
    def test_tags_only_oauth_blocked_approved_events(self, admin_client, test_user_id):
        oauth_event_id = _make_blocked_event(admin_client, test_user_id, "oauth_required")
        scope_event_id = _make_blocked_event(
            admin_client, test_user_id, "oauth_scope_required"
        )
        untouched_event_id = _make_blocked_event(
            admin_client, test_user_id, "permission_denied"
        )
        no_code_event_id = _make_blocked_event(admin_client, test_user_id, None)

        recovery = _create_and_claim_recovery(admin_client, test_user_id)
        tagged = requeue_calendar_recovery_batch(
            admin_client, recovery["id"], "worker-1"
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

    def test_returns_negative_one_when_claim_lost(self, admin_client, test_user_id):
        recovery = _create_and_claim_recovery(admin_client, test_user_id)

        result = requeue_calendar_recovery_batch(
            admin_client, recovery["id"], "a-different-worker"
        )

        assert result == -1

    def test_reclaims_processing_recovery_with_expired_lock(
        self, admin_client, test_user_id
    ):
        """A crashed worker's claim (processing + expired lock) must be reclaimed
        on the next claim instead of waiting for an API restart (#239 was startup
        only; the claim itself must self-heal)."""
        recovery = _create_and_claim_recovery(admin_client, test_user_id)

        admin_client.table("integration_recoveries").update(
            {
                "locked_until": "2020-01-01T00:00:00Z",
            }
        ).eq("id", recovery["id"]).execute()

        reclaimed = claim_integration_recovery(
            admin_client, "worker-2", lock_seconds=120
        )

        assert reclaimed is not None
        assert reclaimed["id"] == recovery["id"]
        assert reclaimed["status"] == "processing"
        assert reclaimed["locked_by"] == "worker-2"
        assert reclaimed["attempts"] == 2

    def test_finalizes_completed_once_tagged_events_synced(
        self, admin_client, test_user_id
    ):
        event_id = _make_blocked_event(admin_client, test_user_id)
        recovery = _create_and_claim_recovery(admin_client, test_user_id)
        requeue_calendar_recovery_batch(admin_client, recovery["id"], "worker-1")

        # Simulate the normal calendar worker syncing the tagged event.
        admin_client.table("events").update({"status": "synced"}).eq(
            "id", event_id
        ).execute()

        refresh_waiting_calendar_recoveries(admin_client)

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

    def test_finalizes_completed_with_errors_when_a_tagged_event_fails(
        self, admin_client, test_user_id
    ):
        event_id = _make_blocked_event(admin_client, test_user_id)
        recovery = _create_and_claim_recovery(admin_client, test_user_id)
        requeue_calendar_recovery_batch(admin_client, recovery["id"], "worker-1")

        # Simulate the normal calendar worker permanently failing the event
        # for a non-OAuth reason after recovery tagged it.
        admin_client.table("events").update(
            {"status": "sync_failed", "sync_failure_code": "invalid_event"}
        ).eq("id", event_id).execute()

        refresh_waiting_calendar_recoveries(admin_client)

        row = (
            admin_client.table("integration_recoveries")
            .select("status")
            .eq("id", recovery["id"])
            .single()
            .execute()
        )
        assert row.data["status"] == "completed_with_errors"

    def test_still_waiting_while_tagged_event_is_unresolved(
        self, admin_client, test_user_id
    ):
        _make_blocked_event(admin_client, test_user_id)
        recovery = _create_and_claim_recovery(admin_client, test_user_id)
        requeue_calendar_recovery_batch(admin_client, recovery["id"], "worker-1")

        row = (
            admin_client.table("integration_recoveries")
            .select("status, remaining_count")
            .eq("id", recovery["id"])
            .single()
            .execute()
        )
        assert row.data["status"] == "waiting"
        assert row.data["remaining_count"] == 1
