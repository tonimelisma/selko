"""Live coordination tests for durable polling email ingestion v2.

These exercise the SQL claim/heartbeat/complete/fail contract directly. Unit
tests mock the RPC layer, so only a real database catches defects such as an
out-parameter shadowing a column inside the function body.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest


def _iso(delta_seconds: int = 0) -> str:
    return (datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)).isoformat()


@pytest.fixture
def synced_integration(admin_client, temp_user):
    """An active Gmail integration with durable sync state due for a poll.

    Sync state is created by the `integrations_ensure_email_sync_state`
    trigger, not by this fixture — a newly connected account must become
    pollable on its own.
    """
    user_id, _, _ = temp_user
    integration_id = str(uuid4())
    admin_client.table("integrations").insert({
        "id": integration_id,
        "user_id": user_id,
        "provider": "gmail",
        "status": "active",
        "access_token": "test-token",
    }).execute()

    state = (
        admin_client.table("email_sync_state")
        .select("integration_id")
        .eq("integration_id", integration_id)
        .maybe_single()
        .execute()
    )
    assert state and state.data, "trigger must provision sync state for a new integration"

    admin_client.table("email_sync_state").update(
        {"next_poll_at": _iso(-60)}
    ).eq("integration_id", integration_id).execute()

    yield integration_id

    try:
        admin_client.table("integrations").delete().eq("id", integration_id).execute()
    except Exception:
        pass


def _claim(admin_client, worker_id):
    result = admin_client.rpc(
        "claim_due_email_sync", {"p_worker_id": worker_id, "p_lease_seconds": 900}
    ).execute()
    return result.data or []


def _claim_for(admin_client, worker_id, integration_id):
    rows = [row for row in _claim(admin_client, worker_id) if row["integration_id"] == integration_id]
    assert len(rows) == 1, f"expected exactly one claim for {integration_id}, got {rows!r}"
    return rows[0]


@pytest.fixture
def isolated_due_claim_queue(admin_client, synced_integration):
    """Keep unrelated due rows from consuming this global one-row claim."""
    rows = admin_client.table("email_sync_state").select(
        "integration_id,next_poll_at"
    ).execute().data or []
    deferred = [
        row for row in rows if row["integration_id"] != synced_integration
    ]
    for row in deferred:
        admin_client.table("email_sync_state").update(
            {"next_poll_at": _iso(3600)}
        ).eq("integration_id", row["integration_id"]).execute()

    try:
        yield
    finally:
        for row in deferred:
            admin_client.table("email_sync_state").update(
                {"next_poll_at": row["next_poll_at"]}
            ).eq("integration_id", row["integration_id"]).execute()


@pytest.mark.integration
@pytest.mark.development
def test_only_one_worker_owns_an_integration_and_expired_leases_return(
    admin_client, synced_integration, isolated_due_claim_queue
):
    """A live lease blocks a second claim; an expired one needs no cleanup job."""
    first = _claim(admin_client, "worker-a")
    owned_rows = [row for row in first if row["integration_id"] == synced_integration]
    assert len(owned_rows) == 1, f"expected exactly one claim for {synced_integration}, got {owned_rows!r}"
    owned = owned_rows[0]
    assert owned["run_kind"] == "initial"

    assert not any(
        row["integration_id"] == synced_integration
        for row in _claim(admin_client, "worker-b")
    )

    admin_client.table("email_sync_state").update(
        {"lease_expires_at": _iso(-1)}
    ).eq("integration_id", synced_integration).execute()

    reclaimed = _claim(admin_client, "worker-b")
    assert any(
        row["integration_id"] == synced_integration for row in reclaimed
    )


@pytest.mark.integration
@pytest.mark.development
def test_heartbeat_and_completion_require_matching_ownership(
    admin_client, synced_integration
):
    """Ownership checks stop a stale worker from mutating a reassigned lease."""
    claim = _claim_for(admin_client, "worker-a", synced_integration)

    assert admin_client.rpc("heartbeat_email_sync", {
        "p_integration_id": synced_integration,
        "p_worker_id": "worker-a",
        "p_lease_seconds": 900,
    }).execute().data is True

    assert admin_client.rpc("heartbeat_email_sync", {
        "p_integration_id": synced_integration,
        "p_worker_id": "worker-b",
        "p_lease_seconds": 900,
    }).execute().data is False

    assert admin_client.rpc("complete_email_sync", {
        "p_integration_id": synced_integration,
        "p_run_id": claim["run_id"],
        "p_worker_id": "worker-b",
        "p_poll_interval_seconds": 300,
        "p_reconciled": False,
    }).execute().data is False

    assert admin_client.rpc("complete_email_sync", {
        "p_integration_id": synced_integration,
        "p_run_id": claim["run_id"],
        "p_worker_id": "worker-a",
        "p_poll_interval_seconds": 300,
        "p_reconciled": False,
    }).execute().data is True


@pytest.mark.integration
@pytest.mark.development
def test_failure_backoff_grows_and_stays_capped(admin_client, synced_integration):
    """Repeated failures must back off without drifting past the cap."""
    delays = []
    for _ in range(4):
        admin_client.table("email_sync_state").update(
            {"next_poll_at": _iso(-60), "lease_owner": None, "lease_expires_at": None}
        ).eq("integration_id", synced_integration).execute()
        claim = _claim_for(admin_client, "worker-a", synced_integration)
        admin_client.rpc("fail_email_sync", {
            "p_integration_id": synced_integration,
            "p_run_id": claim["run_id"],
            "p_worker_id": "worker-a",
            "p_error_code": "provider_transient",
            "p_error_detail": "transient",
            "p_retry_base_seconds": 60,
            "p_retry_max_seconds": 300,
            "p_auth_failure": False,
        }).execute()
        state = admin_client.table("email_sync_state").select(
            "consecutive_failures,next_poll_at"
        ).eq("integration_id", synced_integration).single().execute().data
        delays.append(
            (datetime.fromisoformat(state["next_poll_at"]) - datetime.now(timezone.utc)).total_seconds()
        )

    assert delays[1] > delays[0]
    assert all(delay <= 300 for delay in delays)


@pytest.mark.integration
@pytest.mark.development
def test_discovery_page_write_records_run_counters(admin_client, synced_integration):
    """Regression: the provider_ids_seen out-parameter shadowed the run column,
    which made every discovery page write fail with an ambiguous reference."""
    claim = _claim_for(admin_client, "worker-a", synced_integration)

    result = admin_client.rpc("upsert_discovered_email_items", {
        "p_integration_id": synced_integration,
        "p_run_id": claim["run_id"],
        "p_items": [{"provider_message_id": "m1", "provider_folder_ids": ["INBOX"]}],
        "p_cursor": None,
        "p_folder_id": None,
    }).execute().data

    row = result[0] if isinstance(result, list) else result
    assert row["inserted_count"] == 1
    assert row["provider_ids_seen"] == 1

    run = admin_client.table("email_sync_runs").select(
        "provider_ids_seen,ingestion_items_inserted"
    ).eq("id", claim["run_id"]).single().execute().data
    assert run["provider_ids_seen"] == 1
    assert run["ingestion_items_inserted"] == 1


@pytest.mark.integration
@pytest.mark.development
def test_identity_upsert_unions_folders_and_protects_completed_items(
    admin_client, synced_integration
):
    """Reconciliation overlap must not duplicate or requeue finished work."""
    claim = _claim_for(admin_client, "worker-a", synced_integration)
    payload = {
        "p_integration_id": synced_integration,
        "p_run_id": claim["run_id"],
        "p_cursor": None,
        "p_folder_id": None,
    }

    admin_client.rpc("upsert_discovered_email_items", {
        **payload,
        "p_items": [{"provider_message_id": "m1", "provider_folder_ids": ["INBOX"]}],
    }).execute()
    admin_client.rpc("upsert_discovered_email_items", {
        **payload,
        "p_items": [{"provider_message_id": "m1", "provider_folder_ids": ["ARCHIVE"]}],
    }).execute()

    item = admin_client.table("email_ingestion_items").select(
        "id,provider_folder_ids,acquisition_status"
    ).eq("integration_id", synced_integration).single().execute().data
    assert sorted(item["provider_folder_ids"]) == ["ARCHIVE", "INBOX"]

    admin_client.table("email_ingestion_items").update(
        {"acquisition_status": "completed"}
    ).eq("id", item["id"]).execute()
    admin_client.rpc("upsert_discovered_email_items", {
        **payload,
        "p_items": [{"provider_message_id": "m1", "provider_folder_ids": ["INBOX"]}],
    }).execute()

    after = admin_client.table("email_ingestion_items").select(
        "acquisition_status"
    ).eq("id", item["id"]).single().execute().data
    assert after["acquisition_status"] == "completed"


@pytest.mark.integration
@pytest.mark.development
def test_cursor_advances_only_when_discovery_supplies_one(
    admin_client, synced_integration
):
    """Reconciliation passes no cursor, so normal poll state must survive it."""
    admin_client.table("integrations").update(
        {"sync_cursor": "history-999"}
    ).eq("id", synced_integration).execute()
    claim = _claim_for(admin_client, "worker-a", synced_integration)

    admin_client.rpc("upsert_discovered_email_items", {
        "p_integration_id": synced_integration,
        "p_run_id": claim["run_id"],
        "p_items": [{"provider_message_id": "m2", "provider_folder_ids": ["INBOX"]}],
        "p_cursor": None,
        "p_folder_id": None,
    }).execute()
    unchanged = admin_client.table("integrations").select("sync_cursor").eq(
        "id", synced_integration
    ).single().execute().data
    assert unchanged["sync_cursor"] == "history-999"

    admin_client.rpc("upsert_discovered_email_items", {
        "p_integration_id": synced_integration,
        "p_run_id": claim["run_id"],
        "p_items": [],
        "p_cursor": "history-1000",
        "p_folder_id": None,
    }).execute()
    advanced = admin_client.table("integrations").select("sync_cursor").eq(
        "id", synced_integration
    ).single().execute().data
    assert advanced["sync_cursor"] == "history-1000"


@pytest.mark.integration
@pytest.mark.development
def test_newly_connected_integration_becomes_pollable(admin_client, temp_user):
    """Regression: nothing created sync state after the one-time backfill, so a
    newly connected account was never polled and ingested nothing at all."""
    user_id, _, _ = temp_user
    integration_id = str(uuid4())

    admin_client.table("integrations").insert({
        "id": integration_id, "user_id": user_id, "provider": "gmail",
        "status": "active", "access_token": "test-token",
    }).execute()

    state = admin_client.table("email_sync_state").select("*").eq(
        "integration_id", integration_id
    ).single().execute().data
    assert state["provider"] == "gmail"
    assert datetime.fromisoformat(state["next_poll_at"]) <= datetime.now(timezone.utc)

    # The claim RPC is a bounded global oldest-first batch. Make this newly
    # connected account deterministic and assert its own row was claimed.
    admin_client.table("email_sync_state").update(
        {"next_poll_at": "2000-01-01T00:00:00+00:00"}
    ).eq("integration_id", integration_id).execute()
    _claim_for(admin_client, "worker-a", integration_id)

    admin_client.table("integrations").delete().eq("id", integration_id).execute()


@pytest.mark.integration
@pytest.mark.development
def test_non_email_providers_get_no_sync_state(admin_client, temp_user):
    """Calendar and photo integrations must not enter the email poll rotation."""
    user_id, _, _ = temp_user
    integration_id = str(uuid4())

    admin_client.table("integrations").insert({
        "id": integration_id, "user_id": user_id, "provider": "google_calendar",
        "status": "active", "access_token": "test-token",
    }).execute()

    state = admin_client.table("email_sync_state").select("integration_id").eq(
        "integration_id", integration_id
    ).execute()
    assert state.data == []

    admin_client.table("integrations").delete().eq("id", integration_id).execute()


@pytest.mark.integration
@pytest.mark.development
def test_reconnecting_clears_backoff_but_respects_a_live_lease(
    admin_client, synced_integration
):
    """Reconnecting should resume promptly, without yanking a running lease."""
    admin_client.table("email_sync_state").update({
        "consecutive_failures": 5, "next_poll_at": _iso(1800),
    }).eq("integration_id", synced_integration).execute()

    admin_client.table("integrations").update({"status": "expired"}).eq(
        "id", synced_integration
    ).execute()
    admin_client.table("integrations").update({"status": "active"}).eq(
        "id", synced_integration
    ).execute()

    state = admin_client.table("email_sync_state").select(
        "consecutive_failures,next_poll_at"
    ).eq("integration_id", synced_integration).single().execute().data
    assert state["consecutive_failures"] == 0
    assert datetime.fromisoformat(state["next_poll_at"]) <= datetime.now(timezone.utc)

    # With a worker holding the lease, a reconnect must not rewind next_poll_at.
    admin_client.table("email_sync_state").update({
        "lease_owner": "worker-x", "lease_expires_at": _iso(600), "next_poll_at": _iso(600),
    }).eq("integration_id", synced_integration).execute()
    admin_client.table("integrations").update({"status": "active"}).eq(
        "id", synced_integration
    ).execute()

    held = admin_client.table("email_sync_state").select("next_poll_at").eq(
        "integration_id", synced_integration
    ).single().execute().data
    assert datetime.fromisoformat(held["next_poll_at"]) > datetime.now(timezone.utc)


@pytest.mark.integration
@pytest.mark.development
def test_atomic_save_blocks_llm_claim_until_attachment_descriptors_settle(
    admin_client, temp_user
):
    """The race this is here to catch: an LLM worker claims an email whose
    attachment rows do not yet exist; the LLM then processes the body with no
    attachments, degrading extraction quality invisibly.

    Pre-fix: save_emails + N×(SELECT+INSERT) left a multi-round-trip window in
    which claim_unprocessed_email observed zero attachment rows and passed
    the readiness gate. The atomic RPC commits both writes in one transaction,
    so the gate can never see the gap. This test must run against a real
    database because the bug is a transaction-boundary bug.
    """
    user_id, _, _ = temp_user
    integration_id = str(uuid4())
    admin_client.table("integrations").insert({
        "id": integration_id,
        "user_id": user_id,
        "provider": "gmail",
        "status": "active",
        "access_token": "test-token",
    }).execute()

    message_id = f"race-msg-{uuid4()}"
    email_payload = {
        "email_provider": "gmail",
        "provider_message_id": message_id,
        "subject": "atomic descriptor race",
        "from_email": "sender@selko.local",
        # Oldest-first claim (date_sent ASC) keeps this test deterministic: the
        # gate considers our email before any other pending rows.
        "date_sent": "2000-01-01T00:00:00+00:00",
        "provider_labels": ["INBOX"],
        "has_attachments": True,
        "integration_id": integration_id,
    }
    descriptors = [
        {"provider_attachment_id": "att-1", "filename": "a.txt", "mime_type": "text/plain", "size_bytes": 10},
        {"provider_attachment_id": "att-2", "filename": "b.pdf", "mime_type": "application/pdf", "size_bytes": 200},
        {"provider_attachment_id": "att-3", "filename": "c.png", "mime_type": "image/png", "size_bytes": 1000},
    ]

    email_id = admin_client.rpc("save_email_with_attachment_descriptors", {
        "p_user_id": user_id,
        "p_email": email_payload,
        "p_descriptors": descriptors,
    }).execute().data

    # The RPC's own data shape is a scalar uuid; tolerate the list shape too.
    if isinstance(email_id, list):
        email_id = email_id[0]
    if isinstance(email_id, dict):
        email_id = email_id["id"]
    assert email_id

    try:
        # All three descriptors were written atomically with the email row.
        atts = admin_client.table("attachments").select(
            "provider_attachment_id,ingestion_status"
        ).eq("email_id", email_id).execute().data or []
        assert {a["provider_attachment_id"] for a in atts} == {"att-1", "att-2", "att-3"}
        assert all(a["ingestion_status"] == "pending" for a in atts)

        # The readiness gate must NOT claim the email while attachments are
        # pending/processing/retry. date_sent makes ours oldest, so one call is
        # enough to know the gate saw ours and decided not to claim it.
        claimed = admin_client.rpc("claim_unprocessed_email", {
            "p_worker_id": "race-worker", "p_lock_duration_seconds": 1,
        }).execute().data or []
        if claimed:
            assert claimed[0]["id"] != email_id, "gate claimed an email whose attachments are still pending"

        # Mark all attachments terminal, then the gate must claim our email.
        admin_client.table("attachments").update(
            {"ingestion_status": "stored"}
        ).eq("email_id", email_id).execute()

        found = False
        for _ in range(50):
            claimed = admin_client.rpc("claim_unprocessed_email", {
                "p_worker_id": "race-worker", "p_lock_duration_seconds": 1,
            }).execute().data or []
            if not claimed:
                break
            if claimed[0]["id"] == email_id:
                found = True
                break
        assert found, "gate did not claim the email once all attachments settled"
    finally:
        try:
            admin_client.table("attachments").delete().eq("email_id", email_id).execute()
            admin_client.table("emails").delete().eq("id", email_id).execute()
            admin_client.table("integrations").delete().eq("id", integration_id).execute()
        except Exception:
            pass


@pytest.mark.integration
@pytest.mark.development
def test_re_acquired_email_keeps_existing_attachment_rows_unreset(admin_client, temp_user):
    """Re-acquisition must not duplicate descriptors, and must not reset a
    'stored' attachment row back to 'pending' (which would re-block the gate
    after a worker already paid the attach cost)."""
    user_id, _, _ = temp_user
    integration_id = str(uuid4())
    admin_client.table("integrations").insert({
        "id": integration_id,
        "user_id": user_id,
        "provider": "gmail",
        "status": "active",
        "access_token": "test-token",
    }).execute()

    message_id = f"reacq-msg-{uuid4()}"
    base_payload = {
        "email_provider": "gmail",
        "provider_message_id": message_id,
        "subject": "re-acquire",
        "from_email": "sender@selko.local",
        "date_sent": datetime.now(timezone.utc).isoformat(),
        "provider_labels": ["INBOX"],
        "has_attachments": True,
        "integration_id": integration_id,
    }
    descriptors = [
        {"provider_attachment_id": "att-1", "filename": "a.txt", "mime_type": "text/plain", "size_bytes": 10},
        {"provider_attachment_id": "att-2", "filename": "b.pdf", "mime_type": "application/pdf", "size_bytes": 200},
    ]

    email_id = admin_client.rpc("save_email_with_attachment_descriptors", {
        "p_user_id": user_id, "p_email": base_payload, "p_descriptors": descriptors,
    }).execute().data
    if isinstance(email_id, list):
        email_id = email_id[0]
    if isinstance(email_id, dict):
        email_id = email_id["id"]

    try:
        # Simulate one attachment making it to 'stored' before re-acquisition.
        admin_client.table("attachments").update(
            {"ingestion_status": "stored", "storage_path": "path/a.txt",
             "content_hash": "hash", "size_bytes": 10}
        ).eq("email_id", email_id).eq("provider_attachment_id", "att-1").execute()

        # Re-acquire: same descriptors. ON CONFLICT DO NOTHING must preserve both
        # rows and leave the stored one stored.
        second_id = admin_client.rpc("save_email_with_attachment_descriptors", {
            "p_user_id": user_id, "p_email": base_payload, "p_descriptors": descriptors,
        }).execute().data
        if isinstance(second_id, list):
            second_id = second_id[0]
        if isinstance(second_id, dict):
            second_id = second_id["id"]
        assert second_id == email_id

        atts = admin_client.table("attachments").select(
            "provider_attachment_id,ingestion_status"
        ).eq("email_id", email_id).execute().data or []
        by_id = {a["provider_attachment_id"]: a["ingestion_status"] for a in atts}
        assert by_id == {"att-1": "stored", "att-2": "pending"}, "stored row was reset / descriptors duplicated"
    finally:
        try:
            admin_client.table("attachments").delete().eq("email_id", email_id).execute()
            admin_client.table("emails").delete().eq("id", email_id).execute()
            admin_client.table("integrations").delete().eq("id", integration_id).execute()
        except Exception:
            pass
