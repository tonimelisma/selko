"""Real-Postgres coverage for the durable email and sync state machines."""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest


def _iso(delta_seconds: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)).isoformat()


def _email(admin_client, user_id: str, **overrides) -> dict:
    payload = {
        "user_id": user_id,
        "provider_message_id": f"state-machine-{uuid4().hex}",
        "email_provider": "gmail",
        "subject": "state machine test",
        "from_email": "state-machine@example.test",
        "date_sent": "1900-01-01T00:00:00Z",
        "provider_labels": ["INBOX"],
        "processing_status": "pending",
    }
    payload.update(overrides)
    return admin_client.table("emails").insert(payload).execute().data[0]


def _claim_for_email(admin_client, email_id: str, worker_id: str) -> dict:
    for _ in range(30):
        rows = admin_client.rpc("claim_unprocessed_email", {
            "p_worker_id": worker_id,
            "p_lock_duration_seconds": 300,
        }).execute().data or []
        for row in rows:
            if str(row["id"]) == str(email_id):
                return row
            admin_client.rpc("commit_email_extraction", {
                "p_email_id": row["id"],
                "p_worker_id": worker_id,
                "p_generation": row.get("lock_generation", 0),
                "p_decisions": [],
                "p_terminal": "processed",
            }).execute()
    pytest.fail(f"email {email_id} was not claimable")


def _health_row(admin_client) -> dict:
    data = admin_client.rpc("health_work_state", {
        "p_warning_seconds": 60,
    }).execute().data
    assert data, "health_work_state must return one row"
    return data[0] if isinstance(data, list) else data


@pytest.mark.integration
@pytest.mark.development
class TestDurableEmailStateMachine:
    def test_expired_processing_email_is_reclaimed_without_restart(self, admin_client, temp_user):
        email = _email(
            admin_client,
            temp_user[0],
            processing_status="processing",
            attempts=1,
            locked_by="dead-worker",
            locked_until=_iso(-1),
        )

        claimed = _claim_for_email(admin_client, email["id"], "new-worker")

        assert claimed["processing_status"] == "processing"
        assert claimed["locked_by"] == "new-worker"
        assert claimed["lock_generation"] > email.get("lock_generation", 0)

    def test_expired_processing_email_at_attempt_limit_becomes_failed(self, admin_client, temp_user):
        email = _email(
            admin_client,
            temp_user[0],
            processing_status="processing",
            attempts=3,
            max_attempts=3,
            locked_by="dead-worker",
            locked_until=_iso(-1),
        )

        rows = admin_client.rpc("claim_unprocessed_email", {
            "p_worker_id": "new-worker",
            "p_lock_duration_seconds": 300,
        }).execute().data or []

        assert not any(str(row["id"]) == str(email["id"]) for row in rows)
        result = admin_client.table("emails").select(
            "processing_status,dead_letter_reason,locked_by,locked_until"
        ).eq("id", email["id"]).single().execute().data
        assert result["processing_status"] == "failed"
        assert result["dead_letter_reason"] == "lease_expired_at_limit"
        assert result["locked_by"] is None
        assert result["locked_until"] is None

    def test_unlock_expired_email_locks_retries_and_terminates_correctly(self, admin_client, temp_user):
        retryable = _email(
            admin_client,
            temp_user[0],
            processing_status="processing",
            attempts=1,
            max_attempts=3,
            locked_by="dead-worker-a",
            locked_until=_iso(-1),
        )
        exhausted = _email(
            admin_client,
            temp_user[0],
            processing_status="processing",
            attempts=3,
            max_attempts=3,
            locked_by="dead-worker-b",
            locked_until=_iso(-1),
        )

        count = admin_client.rpc("unlock_expired_email_locks", {}).execute().data
        assert count >= 1

        rows = {
            row["id"]: row
            for row in admin_client.table("emails").select(
                "id,processing_status,dead_letter_reason,locked_by,locked_until"
            ).in_("id", [retryable["id"], exhausted["id"]]).execute().data
        }
        assert rows[retryable["id"]]["processing_status"] == "pending"
        assert rows[retryable["id"]]["locked_by"] is None
        assert rows[exhausted["id"]]["processing_status"] == "failed"
        assert rows[exhausted["id"]]["dead_letter_reason"] == "lease_expired_at_limit"
        assert rows[exhausted["id"]]["locked_by"] is None

    def test_pending_email_cannot_equal_max_attempts(self, admin_client, temp_user):
        with pytest.raises(Exception):
            _email(
                admin_client,
                temp_user[0],
                attempts=3,
                max_attempts=3,
            )

    def test_stale_email_worker_cannot_fail_new_generation(self, admin_client, temp_user):
        email = _email(admin_client, temp_user[0])
        first = _claim_for_email(admin_client, email["id"], "worker-a")
        admin_client.table("emails").update({"locked_until": _iso(-1)}).eq("id", email["id"]).execute()
        second = _claim_for_email(admin_client, email["id"], "worker-b")

        result = admin_client.rpc("fail_email_processing", {
            "p_email_id": email["id"],
            "p_worker_id": "worker-a",
            "p_generation": first["lock_generation"],
            "p_error_code": "stale-worker",
            "p_error_detail": "stale worker must be fenced",
            "p_retry_base_seconds": 1,
            "p_retry_max_seconds": 2,
        }).execute().data

        assert result["fenced"] is True
        current = admin_client.table("emails").select(
            "processing_status,locked_by,lock_generation"
        ).eq("id", email["id"]).single().execute().data
        assert current["locked_by"] == "worker-b"
        assert current["lock_generation"] == second["lock_generation"]

    def test_failure_transition_is_atomic(self, admin_client, temp_user):
        email = _email(admin_client, temp_user[0], max_attempts=3)
        claimed = _claim_for_email(admin_client, email["id"], "worker-a")

        result = admin_client.rpc("fail_email_processing", {
            "p_email_id": email["id"],
            "p_worker_id": "worker-a",
            "p_generation": claimed["lock_generation"],
            "p_error_code": "provider-transient",
            "p_error_detail": "bounded detail",
            "p_retry_base_seconds": 1,
            "p_retry_max_seconds": 2,
        }).execute().data

        assert result["fenced"] is False
        assert result["status"] == "pending"
        current = admin_client.table("emails").select(
            "processing_status,locked_by,locked_until,next_retry_at,processing_error"
        ).eq("id", email["id"]).single().execute().data
        assert current["processing_status"] == "pending"
        assert current["locked_by"] is None
        assert current["locked_until"] is None
        assert current["next_retry_at"] is not None
        assert current["processing_error"] == "provider-transient"

    def test_failure_backoff_grows_and_stays_capped(self, admin_client, temp_user):
        email = _email(admin_client, temp_user[0], max_attempts=10)
        deltas = []
        for _ in range(4):
            claimed = _claim_for_email(admin_client, email["id"], "worker-a")
            result = admin_client.rpc("fail_email_processing", {
                "p_email_id": email["id"],
                "p_worker_id": "worker-a",
                "p_generation": claimed["lock_generation"],
                "p_error_code": "provider-transient",
                "p_error_detail": "bounded detail",
                "p_retry_base_seconds": 60,
                "p_retry_max_seconds": 300,
            }).execute().data
            assert result["status"] == "pending"
            next_retry_at = datetime.fromisoformat(
                result["next_retry_at"].replace("Z", "+00:00")
            )
            deltas.append((next_retry_at - datetime.now(timezone.utc)).total_seconds())
            # Clear next_retry_at so the row is immediately reclaimable for
            # the next iteration; this only affects claimability, not the
            # delay already recorded above.
            admin_client.table("emails").update(
                {"next_retry_at": _iso(-1)}
            ).eq("id", email["id"]).execute()

        assert deltas[1] > deltas[0]
        assert all(delta <= 300 for delta in deltas)

    def test_reprocess_resets_any_unleased_terminal_or_legacy_pending_row(self, admin_client, temp_user):
        exhausted = _email(
            admin_client,
            temp_user[0],
            processing_status="failed",
            attempts=3,
            max_attempts=3,
            dead_letter_reason="legacy_attempts_exhausted",
        )
        # A still-pending row is itself "legacy" in the sense that reprocess
        # must accept it too, not only terminal rows — the invariant CHECK
        # added alongside this RPC forbids a *stored* pending+exhausted row,
        # so this fixture stays below max_attempts to remain insertable.
        legacy_pending = _email(
            admin_client,
            temp_user[0],
            processing_status="pending",
            attempts=1,
            max_attempts=3,
        )

        for row in (exhausted, legacy_pending):
            result = admin_client.rpc("reprocess_email", {
                "p_user_id": temp_user[0],
                "p_email_id": row["id"],
            }).execute().data
            assert result and result[0]["id"] == row["id"]

        rows = admin_client.table("emails").select(
            "processing_status,attempts,locked_by,locked_until,next_retry_at"
        ).in_("id", [exhausted["id"], legacy_pending["id"]]).execute().data
        assert all(row["processing_status"] == "pending" for row in rows)
        assert all(row["attempts"] == 0 for row in rows)
        assert all(row["locked_by"] is None and row["locked_until"] is None for row in rows)

    def test_reprocess_refuses_an_actively_leased_row(self, admin_client, temp_user):
        email = _email(admin_client, temp_user[0])
        _claim_for_email(admin_client, email["id"], "live-worker")

        with pytest.raises(Exception):
            admin_client.rpc("reprocess_email", {
                "p_user_id": temp_user[0],
                "p_email_id": email["id"],
            }).execute()

    def test_health_degrades_on_unclaimable_or_stale_work(self, admin_client, temp_user):
        _email(
            admin_client,
            temp_user[0],
            processing_status="processing",
            attempts=1,
            locked_by="dead-worker",
            locked_until=_iso(-3600),
        )

        result = _health_row(admin_client)

        assert result["stale_processing_emails"] >= 1
        assert result["status"] == "degraded"

    def test_health_counts_use_worker_claim_predicates(self, admin_client, temp_user):
        _email(admin_client, temp_user[0], processing_status="pending", attempts=0, max_attempts=3)
        _email(admin_client, temp_user[0], processing_status="failed", attempts=3, max_attempts=3)
        _email(
            admin_client,
            temp_user[0],
            processing_status="processing",
            attempts=1,
            locked_by="worker",
            locked_until=_iso(3600),
        )

        result = _health_row(admin_client)

        assert result["ready_emails"] >= 1
        assert result["unclaimable_emails"] >= 1
        assert result["processing_emails"] >= 1
        assert result["stale_processing_emails"] == 0

    def test_health_ignores_expired_integration_poll_age(self, admin_client, synced_integration):
        """Expired integrations are not eligible work and cannot degrade health."""
        before = _health_row(admin_client)

        admin_client.table("integrations").update({"status": "expired"}).eq(
            "id", synced_integration
        ).execute()
        admin_client.table("email_sync_state").update({
            "next_poll_at": "2000-01-01T00:00:00+00:00",
        }).eq("integration_id", synced_integration).execute()

        after = _health_row(admin_client)

        assert after["status"] == before["status"]
        # The expired integration's 26-year-old cursor must not be reported.
        # The screenshot gate may leave another active integration with an
        # upcoming poll, which the health contract represents as zero age.
        assert after["oldest_next_poll_seconds"] in (None, 0)


@pytest.mark.integration
@pytest.mark.development
class TestDurableSyncRunGeneration:
    def test_next_sync_claim_abandons_previous_expired_run(self, admin_client, synced_integration):
        admin_client.table("email_sync_state").update({
            "next_poll_at": _iso(-60),
            "lease_owner": "dead-worker",
            "lease_expires_at": _iso(-1),
        }).eq("integration_id", synced_integration).execute()
        first = admin_client.rpc("claim_due_email_sync", {
            "p_worker_id": "new-worker-a",
            "p_lease_seconds": 300,
        }).execute().data
        first = next(row for row in first if row["integration_id"] == synced_integration)

        admin_client.table("email_sync_state").update({
            "next_poll_at": _iso(-60),
            "lease_expires_at": _iso(-1),
        }).eq("integration_id", synced_integration).execute()
        second = admin_client.rpc("claim_due_email_sync", {
            "p_worker_id": "new-worker-b",
            "p_lease_seconds": 300,
        }).execute().data
        second = next(row for row in second if row["integration_id"] == synced_integration)

        assert second["lease_generation"] > first["lease_generation"]
        run = admin_client.table("email_sync_runs").select("status").eq("id", first["run_id"]).single().execute().data
        assert run["status"] == "abandoned"

    def test_stale_sync_generation_cannot_complete_new_run(self, admin_client, synced_integration):
        first = admin_client.rpc("claim_due_email_sync", {
            "p_worker_id": "worker-a",
            "p_lease_seconds": 1,
        }).execute().data
        first = next(row for row in first if row["integration_id"] == synced_integration)
        admin_client.table("email_sync_state").update({
            "lease_expires_at": _iso(-1),
            "next_poll_at": _iso(-60),
        }).eq("integration_id", synced_integration).execute()
        second = admin_client.rpc("claim_due_email_sync", {
            "p_worker_id": "worker-b",
            "p_lease_seconds": 300,
        }).execute().data
        second = next(row for row in second if row["integration_id"] == synced_integration)

        assert admin_client.rpc("complete_email_sync", {
            "p_integration_id": synced_integration,
            "p_run_id": first["run_id"],
            "p_worker_id": "worker-a",
            "p_generation": first["lease_generation"],
            "p_poll_interval_seconds": 60,
            "p_reconciled": False,
        }).execute().data is False
        assert second["lease_generation"] > first["lease_generation"]

    def test_one_running_run_per_integration_is_a_database_invariant(
        self, admin_client, synced_integration
    ):
        """The partial unique index, not just the abandon-then-insert claim
        logic, is what makes 'at most one running run' true."""
        admin_client.table("email_sync_runs").insert({
            "integration_id": synced_integration,
            "user_id": admin_client.table("integrations").select("user_id").eq(
                "id", synced_integration
            ).single().execute().data["user_id"],
            "provider": "gmail",
            "run_kind": "manual_repair",
            "status": "running",
        }).execute()

        with pytest.raises(Exception):
            admin_client.table("email_sync_runs").insert({
                "integration_id": synced_integration,
                "user_id": admin_client.table("integrations").select("user_id").eq(
                    "id", synced_integration
                ).single().execute().data["user_id"],
                "provider": "gmail",
                "run_kind": "manual_repair",
                "status": "running",
            }).execute()


@pytest.fixture
def synced_integration(admin_client, temp_user):
    integration_id = str(uuid4())
    admin_client.table("integrations").insert({
        "id": integration_id,
        "user_id": temp_user[0],
        "provider": "gmail",
        "status": "active",
        "access_token": "test-token",
    }).execute()
    admin_client.table("email_sync_state").update({
        "next_poll_at": _iso(-60),
    }).eq("integration_id", integration_id).execute()
    yield integration_id
    admin_client.table("integrations").delete().eq("id", integration_id).execute()
