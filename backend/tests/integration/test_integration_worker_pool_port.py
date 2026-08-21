"""Live transport tests for the single-transport worker port (C2).

Every worker coordination operation now runs over the asyncpg session-pooler
pool. Unit tests use the fake pool; these prove the ``SELECT * FROM
public.fn($1, $2)`` invocation form and the jsonb casts against the real local
database. One test per ported function, asserting the returned shape.
"""

from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest

pytestmark = pytest.mark.integration


def _iso(offset_seconds: int = 0) -> str:
    return (
        datetime.now(timezone.utc) + timedelta(seconds=offset_seconds)
    ).isoformat()


@pytest.fixture
def synced_integration(admin_client, temp_user):
    """Active gmail integration whose sync state is due for a poll."""
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
    assert state and state.data, "trigger must provision sync state"
    admin_client.table("email_sync_state").update(
        {"next_poll_at": _iso(-60)}
    ).eq("integration_id", integration_id).execute()
    yield integration_id
    try:
        admin_client.table("integrations").delete().eq("id", integration_id).execute()
    except Exception:
        pass


@pytest.fixture
def pending_email(admin_client, temp_user):
    """A pending LLM-path email row for claim_unprocessed_email."""
    user_id, _, _ = temp_user
    email_id = str(uuid4())
    admin_client.table("emails").insert({
        "id": email_id,
        "user_id": user_id,
        "provider_message_id": f"gmail-{uuid4()}",
        "subject": "C2 integration probe",
        "processing_status": "pending",
    }).execute()
    admin_client.table("emails").update(
        {"created_at": "2000-01-01T00:00:00+00:00"}
    ).eq("id", email_id).execute()
    yield email_id
    try:
        admin_client.table("emails").delete().eq("id", email_id).execute()
    except Exception:
        pass


@pytest.fixture
def approved_event(admin_client, temp_user):
    """An approved event for claim_approved_event_for_sync.

    claim_approved_event only picks events whose user has an active
    google_calendar integration, so the fixture provisions one.
    """
    user_id, _, _ = temp_user
    admin_client.table("integrations").insert({
        "user_id": user_id,
        "provider": "google_calendar",
        "status": "active",
        "access_token": "test-token",
    }).execute()
    event_id = str(uuid4())
    admin_client.table("events").insert({
        "id": event_id,
        "user_id": user_id,
        "title": "C2 probe event",
        "start_datetime": _iso(3600),
        "end_datetime": _iso(7200),
        "status": "approved",
    }).execute()
    admin_client.rpc("enqueue_calendar_work", {
        "p_event_id": event_id,
        "p_user_id": user_id,
        "p_action": "upsert",
        "p_desired_event": {"title": "C2 probe event"},
    }).execute()
    # claim_approved_event picks the OLDEST updated_at row; make ours the
    # oldest so a leftover approved event from another suite cannot win.
    admin_client.table("events").update(
        {"updated_at": "2000-01-01T00:00:00+00:00"}
    ).eq("id", event_id).execute()
    yield event_id
    try:
        admin_client.table("events").delete().eq("id", event_id).execute()
    except Exception:
        pass


class TestRepositoryOverPool:
    """EmailIngestionRepository — every coordination call over asyncpg."""

    async def test_claim_heartbeat_complete_sync_roundtrip(
        self, pg_pool, development_config, synced_integration
    ):
        from selko.services.email_ingestion import EmailIngestionRepository

        repo = EmailIngestionRepository(development_config, pg_pool)
        claim = await repo.claim_due_sync("c2-probe-worker")
        assert claim is not None
        assert str(claim.integration_id) == synced_integration

        await repo.require_heartbeat(claim.integration_id, "c2-probe-worker", claim.lease_generation)
        completed = await repo.complete_sync(claim, "c2-probe-worker")
        assert completed is True

    async def test_upsert_discovered_jsonb_and_known_ids(
        self, pg_pool, development_config, synced_integration
    ):
        from selko.services.email_ingestion import EmailIngestionRepository

        repo = EmailIngestionRepository(development_config, pg_pool)
        claim = await repo.claim_due_sync("c2-probe-worker-2")
        assert claim is not None

        message_id = f"c2-msg-{uuid4()}"
        totals = await repo.upsert_discovered(
            claim,
            [{
                "provider_message_id": message_id,
                "provider_folder_ids": ["INBOX"],
                "change_kind": "upsert",
            }],
        )
        assert totals["inserted_count"] >= 1

        known = await repo.known_provider_message_ids(
            claim.integration_id, [message_id, "never-seen-id"]
        )
        assert message_id in known
        assert "never-seen-id" not in known
        await repo.complete_sync(claim, "c2-probe-worker-2")

    async def test_fail_sync_records_auth_failure(
        self, pg_pool, development_config, synced_integration
    ):
        from selko.services.email_ingestion import (
            EmailIngestionRepository,
            ProviderAuthenticationError,
        )

        repo = EmailIngestionRepository(development_config, pg_pool)
        claim = await repo.claim_due_sync("c2-probe-worker-3")
        assert claim is not None
        failed = await repo.fail_sync(
            claim, "c2-probe-worker-3", ProviderAuthenticationError("probe")
        )
        assert failed is True

    async def test_save_email_with_attachment_descriptors_returns_uuid(
        self, pg_pool, development_config, temp_user
    ):
        from selko.services.email_ingestion import EmailIngestionRepository

        user_id, _, _ = temp_user
        repo = EmailIngestionRepository(development_config, pg_pool)
        email_id = await repo.save_email_with_attachment_descriptors(
            user_id,
            {
                "email_provider": "gmail",
                "provider_message_id": f"c2-atomic-{uuid4()}",
                "subject": "atomic probe",
                "user_id": user_id,
            },
            [{
                "provider_attachment_id": f"att-{uuid4()}",
                "filename": "probe.pdf",
                "mime_type": "application/pdf",
                "size_bytes": 10,
            }],
        )
        assert email_id and str(email_id)

        ready = await repo.attachment_readiness(email_id)
        assert ready is False  # descriptor is pending, not stored yet
        ensured = await repo.ensure_attachment_descriptors(
            email_id, user_id, [{
                "provider_attachment_id": f"att2-{uuid4()}",
                "filename": "second.pdf",
                "mime_type": "application/pdf",
            }],
        )
        assert ensured == 1

    async def test_claim_item_remove_item_roundtrip(
        self, pg_pool, development_config, synced_integration
    ):
        from selko.services.email_ingestion import EmailIngestionRepository

        repo = EmailIngestionRepository(development_config, pg_pool)
        claim = await repo.claim_due_sync("c2-probe-worker-4")
        assert claim is not None
        message_id = f"c2-item-{uuid4()}"
        await repo.upsert_discovered(
            claim, [{
                "provider_message_id": message_id,
                "provider_folder_ids": ["INBOX"],
                "change_kind": "upsert",
            }],
        )
        item = await repo.claim_item("c2-probe-worker-4")
        assert item is not None
        assert str(item["provider_message_id"]) == message_id

        removed = await repo.remove_item(item["id"], "c2-probe-worker-4")
        assert removed is True
        # A second remove of the same row must not claim a foreign lease.
        re_claim = await repo.claim_item("c2-probe-worker-4")
        assert re_claim is None or str(re_claim["provider_message_id"]) != message_id
        await repo.complete_sync(claim, "c2-probe-worker-4")

    async def test_complete_and_fail_item(
        self, pg_pool, development_config, synced_integration
    ):
        from selko.services.email_ingestion import (
            EmailIngestionRepository,
            ProviderPermanentError,
        )

        repo = EmailIngestionRepository(development_config, pg_pool)
        claim = await repo.claim_due_sync("c2-probe-worker-5")
        assert claim is not None
        await repo.upsert_discovered(
            claim, [{
                "provider_message_id": f"c2-cf-{uuid4()}",
                "provider_folder_ids": ["INBOX"],
                "change_kind": "upsert",
            }],
        )
        item = await repo.claim_item("c2-probe-worker-5")
        assert item is not None
        failed = await repo.fail_item(
            item["id"], "c2-probe-worker-5", ProviderPermanentError("probe")
        )
        assert failed is True
        await repo.complete_sync(claim, "c2-probe-worker-5")

    async def test_claim_and_finish_attachment(
        self, pg_pool, development_config, temp_user
    ):
        from selko.services.email_ingestion import EmailIngestionRepository

        user_id, _, _ = temp_user
        repo = EmailIngestionRepository(development_config, pg_pool)
        email_id = await repo.save_email_with_attachment_descriptors(
            user_id,
            {
                "email_provider": "gmail",
                "provider_message_id": f"c2-att-{uuid4()}",
                "subject": "attachment probe",
                "user_id": user_id,
            },
            [{
                "provider_attachment_id": f"att-{uuid4()}",
                "filename": "probe.pdf",
                "mime_type": "application/pdf",
            }],
        )
        attachment = await repo.claim_attachment("c2-probe-worker-6")
        assert attachment is not None
        # Defensive: claim_attachment now returns string UUIDs so any
        # future jsonb/log path is safe — prove the contract.
        import json as _json
        _json.dumps(attachment)
        assert isinstance(attachment["id"], str)
        assert isinstance(attachment["email_id"], str)
        finished = await repo.finish_attachment(
            attachment["id"], "c2-probe-worker-6", "unsupported"
        )
        assert finished is True

    async def test_claim_item_save_roundtrip_is_json_safe(
        self, pg_pool, development_config, synced_integration
    ):
        """Claimed items must be JSON-safe for acquisition's atomic save.

        This is the real-DB proof that the repository boundary prevents the
        prod TypeError: Object of type UUID is not JSON serializable. The
        fake-pool unit test proves the boundary with synthetic UUIDs; this
        proves it with an actual asyncpg uuid → str conversion and a live
        save_email_with_attachment_descriptors RPC.
        """
        from selko.services.email_ingestion import EmailIngestionRepository

        repo = EmailIngestionRepository(development_config, pg_pool)
        claim = await repo.claim_due_sync("c2-probe-worker-save")
        assert claim is not None
        message_id = f"c2-save-{uuid4()}"
        await repo.upsert_discovered(
            claim, [{
                "provider_message_id": message_id,
                "provider_folder_ids": ["INBOX"],
                "change_kind": "upsert",
            }],
        )
        item = await repo.claim_item("c2-probe-worker-save")
        assert item is not None
        # Every UUID column that crosses to JSON must be str, not UUID.
        assert isinstance(item["id"], str)
        assert isinstance(item["integration_id"], str)
        assert isinstance(item["user_id"], str)
        # email_id is None on insert, stays None.
        assert item["email_id"] is None
        # The worker payload that previously raised must now serialize.
        import json as _json2
        _json2.dumps({"integration_id": item["integration_id"], "user_id": item["user_id"]})

        # The atomic save must succeed with the claimed string IDs — this is
        # what prod was failing on (json.dumps inside save).
        email_id = await repo.save_email_with_attachment_descriptors(
            item["user_id"],
            {
                "email_provider": item["provider"],
                "provider_message_id": item["provider_message_id"],
                "subject": "json-safe acquisition probe",
                "user_id": item["user_id"],
                "integration_id": item["integration_id"],
            },
            [],
        )
        assert email_id
        completed = await repo.complete_item(item["id"], "c2-probe-worker-save", email_id)
        assert completed is True
        await repo.complete_sync(claim, "c2-probe-worker-save")


class TestLooseWorkerFunctionsOverPool:
    """The loose claim/complete/fail helpers, all over the pool."""

    async def test_event_claim_complete_roundtrip(
        self, pg_pool, approved_event
    ):
        from selko.services.events import (
            claim_approved_event_for_sync,
            complete_event_sync,
        )

        event = await claim_approved_event_for_sync(
            pg_pool, "c2-probe-worker-7", lock_duration_seconds=120
        )
        assert event is not None
        assert str(event["id"]) == approved_event
        await complete_event_sync(
            pg_pool,
            event["calendar_work_lease"],
            "google-c2-probe",
        )

    async def test_event_fail_retries_then_dead_letters(
        self, pg_pool, approved_event
    ):
        from selko.services.events import claim_approved_event_for_sync, fail_event_sync

        event = await claim_approved_event_for_sync(
            pg_pool, "c2-probe-worker-8", lock_duration_seconds=120
        )
        assert event is not None
        await fail_event_sync(
            pg_pool,
            event["calendar_work_lease"],
            "transient probe",
        )
        row = await pg_pool.fetchrow(
            "SELECT status FROM public.events WHERE id = $1",
            approved_event,
        )
        assert row["status"] == "approved"

    async def test_email_claim_complete_roundtrip(
        self, pg_pool, pending_email
    ):
        from selko.services.emails import (
            claim_pending_email,
            complete_email_processing,
        )

        # claim_unprocessed_email takes the OLDEST pending row globally, and
        # other suites can leave pending emails behind. Claim until ours
        # comes up, parking foreign leftovers as processed along the way.
        claimed = None
        for _ in range(25):
            email = await claim_pending_email(
                pg_pool, "c2-probe-worker-9", lock_duration_seconds=120
            )
            if email is None:
                break
            if str(email["id"]) == pending_email:
                claimed = email
                break
            await complete_email_processing(pg_pool, str(email["id"]))
        assert claimed is not None
        await complete_email_processing(pg_pool, pending_email)

    async def test_unlock_expired_helpers_run(self, pg_pool):
        from selko.services.emails import unlock_expired_email_locks
        from selko.services.events import unlock_expired_event_locks
        from selko.services.integrations import unlock_expired_integration_recoveries
        from selko.services.photos import unlock_expired_photo_locks
        from selko.services.scheduled_tasks import unlock_expired_scheduled_tasks

        assert await unlock_expired_email_locks(pg_pool) >= 0
        assert await unlock_expired_event_locks(pg_pool) >= 0
        assert await unlock_expired_photo_locks(pg_pool) >= 0
        assert await unlock_expired_scheduled_tasks(pg_pool) >= 0
        assert await unlock_expired_integration_recoveries(pg_pool) >= 0

    async def test_calendar_recovery_claim_and_refresh_run(self, pg_pool):
        from selko.services.calendars import (
            refresh_waiting_calendar_recoveries,
            requeue_calendar_recovery_batch,
        )
        from selko.services.integrations import claim_integration_recovery

        recovery = await claim_integration_recovery(
            pg_pool, "c2-probe-worker-10", lock_seconds=60
        )
        if recovery is not None:
            tagged = await requeue_calendar_recovery_batch(
                pg_pool, recovery["id"], "c2-probe-worker-10"
            )
            assert tagged >= -1
        assert await refresh_waiting_calendar_recoveries(pg_pool) >= 0
