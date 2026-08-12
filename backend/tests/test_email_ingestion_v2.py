"""Regression coverage for durable polling email ingestion boundaries."""

import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from selko.services.email_ingestion import (
    EmailIngestionRepository,
    ProviderAuthenticationError,
    ProviderMessageMissingError,
    ProviderPermanentError,
    classify_email_error,
    safe_error_code,
    safe_error_detail,
    SyncClaim,
)
from selko.services.email_sync_health import (
    EmailSyncHealthEvaluator,
    ResendOperationalNotifier,
    SafeIncident,
)
from selko.services.gmail import GmailError
from selko.services.gmail import GmailAuthError, GmailHistoryExpiredError
from selko.services.msgraph import request_json, safe_url_template
from selko.services.outlook import GraphHttpError
from selko.workers.email_ingestion import EmailIngestionWorker


def test_expired_sync_claim_uses_durable_rpc_and_returns_run(mock_config, fake_pg_pool):
    client = MagicMock()
    client.rpc.return_value.execute.return_value = MagicMock(data=[{
        "integration_id": "integration-1",
        "user_id": "user-1",
        "provider": "outlook",
        "run_id": "run-1",
        "run_kind": "incremental",
        "lease_expires_at": datetime.now(timezone.utc).isoformat(),
    }])

    fake_pg_pool.rows.append({
        "integration_id": "integration-1",
        "user_id": "user-1",
        "provider": "outlook",
        "run_id": "run-1",
        "run_kind": "incremental",
        "lease_expires_at": datetime.now(timezone.utc).isoformat(),
    })
    claim = asyncio.run(
        EmailIngestionRepository(mock_config, fake_pg_pool).claim_due_sync("worker-1")
    )

    assert claim.integration_id == "integration-1"
    sql, args = fake_pg_pool.calls[0]
    assert "claim_due_email_sync" in sql
    assert args == ("worker-1", mock_config.email_lease_seconds)


def test_ingestion_error_codes_are_stable_and_details_redacted():
    exc = ProviderMessageMissingError("Authorization: Bearer secret-token")

    assert safe_error_code(exc) == "provider_message_missing"
    assert safe_error_detail(exc) == "provider operation failed"


def test_upsert_discovered_normalizes_uuid_provider_identifiers(mock_config, fake_pg_pool):
    """Provider identity JSONB must accept UUID-backed database identifiers."""
    fake_pg_pool.rows.append({
        "provider_ids_seen": 1,
        "inserted_count": 1,
        "existing_count": 0,
    })
    repository = EmailIngestionRepository(mock_config, fake_pg_pool)
    claim = SyncClaim("integration-1", "user-1", "gmail", "run-1", "incremental")
    message_id = uuid4()
    folder_id = uuid4()

    result = asyncio.run(repository.upsert_discovered(
        claim,
        [{
            "provider_message_id": message_id,
            "provider_folder_ids": [folder_id],
            "change_kind": "upsert",
        }],
    ))

    payload = fake_pg_pool.calls[0][1][2]
    assert result["inserted_count"] == 1
    assert f'"provider_message_id": "{message_id}"' in payload
    assert f'"provider_folder_ids": ["{folder_id}"]' in payload


def test_outlook_unsupported_video_attachment_is_terminal_without_provider_call(mock_config, fake_pg_pool):
    worker = EmailIngestionWorker(MagicMock(), mock_config, "attachment-worker")
    attachment = {"mime_type": "video/mp4", "filename": "clip.mp4"}

    assert asyncio.run(worker.acquire_attachment(attachment)) == "unsupported"


def test_graph_transport_sends_correlation_and_immutable_request_headers():
    response = MagicMock(status_code=200, headers={"request-id": "server-request"})
    response.json.return_value = {"value": []}
    with patch("selko.services.msgraph.requests.get", return_value=response) as get:
        result = request_json(
            "token",
            "https://graph.microsoft.com/v1.0/me/messages",
            prefer='IdType="ImmutableId"',
            max_attempts=1,
        )

    assert result == {"value": []}
    headers = get.call_args.kwargs["headers"]
    assert headers["Prefer"] == 'IdType="ImmutableId"'
    assert headers["return-client-request-id"] == "true"
    assert headers["client-request-id"]


def test_graph_429_honors_retry_after_before_success():
    throttled = MagicMock(status_code=429, headers={"Retry-After": "7"})
    throttled.json.return_value = {"error": {"code": "TooManyRequests"}}
    success = MagicMock(status_code=200, headers={})
    success.json.return_value = {"value": [{"id": "immutable-id"}]}
    sleeps = []
    with patch("selko.services.msgraph.requests.get", side_effect=[throttled, success]):
        result = request_json("token", "https://graph.microsoft.com/v1.0/me/messages", sleep=sleeps.append)

    assert result["value"][0]["id"] == "immutable-id"
    assert sleeps == [7.0]


def _gmail_message_with_inline_image() -> dict:
    """A CID image carries an attachmentId but no filename."""
    return {
        "id": "msg-inline",
        "payload": {
            "parts": [
                {
                    "mimeType": "image/png",
                    "filename": "",
                    "headers": [{"name": "Content-ID", "value": "<logo@selko>"}],
                    "body": {"attachmentId": "inline-att-1", "size": 12},
                }
            ]
        },
    }


def test_gmail_inline_image_is_stored_rather_than_marked_unsupported(mock_config, fake_pg_pool):
    """extract_attachments() skips CID images, so the descriptor lookup must
    also consult extract_inline_images() or every inline image dead-ends."""
    client = MagicMock()
    client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "user_id": "user-1",
        "email_provider": "gmail",
        "provider_message_id": "msg-inline",
        "integration_id": "integration-1",
    }
    worker = EmailIngestionWorker(client, mock_config, "attachment-worker")
    attachment = {
        "id": "attachment-1",
        "email_id": "email-1",
        "provider_attachment_id": "inline-att-1",
        "mime_type": "image/png",
        "filename": "inline_0.png",
    }

    with patch("selko.workers.email_ingestion.get_gmail_credentials", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.build_service", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.get_gmail_full_message", return_value=_gmail_message_with_inline_image()), \
         patch("selko.workers.email_ingestion.download_gmail_attachment", return_value=b"png-bytes") as download, \
         patch("selko.workers.email_ingestion.calculate_content_hash", return_value="hash"), \
         patch("selko.workers.email_ingestion.upload_to_storage", return_value="path/inline_0.png"):
        status = asyncio.run(worker.acquire_attachment(attachment))

    assert status == "stored"
    assert download.call_args[0][2] == "inline-att-1"


def test_acquire_item_does_not_query_integrations_per_message(mock_config, fake_pg_pool):
    """A dead per-message integrations lookup costs a round trip and can raise
    on a missing row, dead-lettering mail for an unrelated reason."""
    client = MagicMock()
    worker = EmailIngestionWorker(client, mock_config, "acquisition-worker")
    item = {
        "id": "item-1",
        "integration_id": "integration-1",
        "user_id": "user-1",
        "provider": "gmail",
        "provider_message_id": "msg-1",
        "provider_folder_ids": ["INBOX"],
    }

    with patch("selko.workers.email_ingestion.get_gmail_credentials", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.build_service", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.get_gmail_full_message", return_value={"id": "msg-1", "payload": {}}), \
         patch("selko.workers.email_ingestion.parse_gmail_message", return_value={}), \
         patch.object(worker.repository, "save_email_with_attachment_descriptors", new=AsyncMock(return_value="email-1")) as atomic_save, \
         patch.object(worker, "_integration") as integration_lookup:
        assert asyncio.run(worker.acquire_item(item)) == "email-1"

    integration_lookup.assert_not_called()
    atomic_save.assert_awaited_once()


def _health_state() -> dict:
    return {
        "integration_id": "integration-1",
        "user_id": "user-1",
        "provider": "gmail",
        "last_success_at": datetime.now(timezone.utc).isoformat(),
        "last_started_at": datetime.now(timezone.utc).isoformat(),
        "consecutive_failures": 0,
    }


def _dead_letter_scan(rows: list[dict]):
    """Serve the paged dead-letter scan: .select(cols).eq(col, ...).range(a, b)."""

    def _range(start: int, end: int):
        return MagicMock(
            execute=MagicMock(return_value=MagicMock(data=rows[start : end + 1]))
        )

    return _range


def test_dead_letter_attachment_incident_is_scoped_to_its_own_integration(mock_config):
    """A dead letter belonging to another integration must not raise an incident here.

    6e replaced the per-integration `count="exact"` pair with one grouped scan
    per table, so scoping moved from a SQL filter into the row->integration
    mapping. This pins that the mapping still scopes: the only dead-letter
    attachment in the deployment belongs to integration-2, so integration-1 —
    the sole `email_sync_state` row — must come out clean.
    """
    client = MagicMock()
    inserted: list[dict] = []

    def table(name):
        handle = MagicMock()
        if name == "email_sync_state":
            handle.select.return_value.execute.return_value.data = [_health_state()]
        elif name == "attachments":
            handle.select.return_value.eq.return_value.range.side_effect = _dead_letter_scan(
                [{"email_id": "email-9", "emails": {"integration_id": "integration-2"}}]
            )
        elif name == "email_ingestion_items":
            handle.select.return_value.eq.return_value.range.side_effect = _dead_letter_scan([])
        elif name == "operational_incidents":
            handle.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = None
            handle.select.return_value.eq.return_value.like.return_value.execute.return_value.data = []
            handle.insert.side_effect = lambda payload: (inserted.append(payload), MagicMock())[1]
        return handle

    client.table.side_effect = table
    asyncio.run(EmailSyncHealthEvaluator(client, mock_config).evaluate_once())

    assert not [row for row in inserted if row["incident_type"] == "attachment_dead_letter"]


def test_dead_letter_scan_pages_past_the_postgrest_row_cap(mock_config):
    """A deployment with more dead letters than one page must still be seen.

    PostgREST caps a single response, so the grouped scan has to page. Without
    paging, every integration whose dead letter sorts past the cap silently
    stops raising incidents — a monitoring gap that reads as "all healthy".
    """
    from selko.services.email_sync_health import _DEAD_LETTER_PAGE_SIZE

    # integration-1's only dead letter sits one row past the first page.
    rows = [{"integration_id": f"filler-{i}"} for i in range(_DEAD_LETTER_PAGE_SIZE)]
    rows.append({"integration_id": "integration-1"})
    inserted: list[dict] = []

    client = MagicMock()

    def table(name):
        handle = MagicMock()
        if name == "email_sync_state":
            handle.select.return_value.execute.return_value.data = [_health_state()]
        elif name == "email_ingestion_items":
            handle.select.return_value.eq.return_value.range.side_effect = _dead_letter_scan(rows)
        elif name == "attachments":
            handle.select.return_value.eq.return_value.range.side_effect = _dead_letter_scan([])
        elif name == "operational_incidents":
            handle.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = None
            handle.select.return_value.eq.return_value.like.return_value.execute.return_value.data = []
            handle.insert.side_effect = lambda payload: (inserted.append(payload), MagicMock())[1]
        return handle

    client.table.side_effect = table
    asyncio.run(EmailSyncHealthEvaluator(client, mock_config).evaluate_once())

    assert [row["incident_type"] for row in inserted if row["incident_type"] == "acquisition_dead_letter"]


def test_incident_sweep_does_not_resolve_a_foreign_incident_key(mock_config):
    """The evaluator must only resolve incidents it owns.

    `operational_incidents` is a generic table. Before 6e the sweep resolved
    every open row absent from its own `expected` set, so the first non-email
    subsystem to write there would have had its incidents silently closed.
    """
    client = MagicMock()
    swept: list[str] = []
    like_filters: list[tuple[str, str]] = []

    def table(name):
        handle = MagicMock()
        if name == "email_sync_state":
            handle.select.return_value.execute.return_value.data = []
        elif name in ("email_ingestion_items", "attachments"):
            handle.select.return_value.eq.return_value.range.side_effect = _dead_letter_scan([])
        elif name == "operational_incidents":
            def like(column, pattern):
                like_filters.append((column, pattern))
                # A correctly scoped query cannot return the billing incident.
                return MagicMock(
                    execute=MagicMock(return_value=MagicMock(data=[]))
                )

            handle.select.return_value.eq.return_value.like.side_effect = like
            handle.update.return_value.eq.side_effect = lambda col, val: (
                swept.append(val), MagicMock()
            )[1]
        return handle

    client.table.side_effect = table
    asyncio.run(EmailSyncHealthEvaluator(client, mock_config).evaluate_once())

    assert ("incident_key", "email-sync:%") in like_filters
    assert swept == []


def test_reopened_incident_can_send_a_second_recovery_notification(mock_config):
    """Leaving resolved_notification_sent_at set silences every later recovery."""
    client = MagicMock()
    updates: list[dict] = []

    def table(name):
        handle = MagicMock()
        if name == "email_sync_state":
            state = _health_state()
            state["consecutive_failures"] = 3
            handle.select.return_value.execute.return_value.data = [state]
        elif name in ("attachments", "email_ingestion_items"):
            handle.select.return_value.eq.return_value.range.side_effect = _dead_letter_scan([])
        elif name == "operational_incidents":
            handle.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = {
                "id": "incident-1",
                "status": "resolved",
                "opened_notification_sent_at": "2026-08-01T00:00:00+00:00",
                "resolved_notification_sent_at": "2026-08-01T00:05:00+00:00",
            }
            handle.select.return_value.eq.return_value.execute.return_value.data = []

            def update(payload):
                updates.append(payload)
                return MagicMock()

            handle.update.side_effect = update
        return handle

    client.table.side_effect = table
    notifier = MagicMock()
    notifier.send_incident_opened = MagicMock(return_value=asyncio.sleep(0))
    asyncio.run(EmailSyncHealthEvaluator(client, mock_config, notifier).evaluate_once())

    reopen = next(u for u in updates if u.get("status") == "open")
    assert reopen["resolved_notification_sent_at"] is None
    assert reopen["opened_notification_sent_at"] is None


def test_graph_ledger_url_template_drops_item_ids_and_delta_tokens():
    url = (
        "https://graph.microsoft.com/v1.0/me/mailFolders/AAMkFolderId/messages/"
        "AAMkMessageId/attachments?%24deltatoken=secret-cursor"
    )

    assert safe_url_template(url) == (
        "https://graph.microsoft.com/v1.0/me/mailFolders/{folder-id}/messages/"
        "{message-id}/attachments"
    )


def test_notifier_reports_unconfigured_so_the_worker_can_skip_it(mock_config):
    """Without credentials the worker must not construct a notifier that fails
    on every cycle; incidents still land in operational_incidents."""
    assert ResendOperationalNotifier.is_configured(mock_config) is False

    mock_config.operational_notification_api_key = "key"
    mock_config.operational_notification_sender = "alerts@example.com"
    mock_config.operational_notification_recipient = "ops@example.com"

    assert ResendOperationalNotifier.is_configured(mock_config) is True


def test_health_evaluation_records_incidents_without_a_notifier(mock_config):
    """A missing notifier must not stop incident bookkeeping."""
    client = MagicMock()
    inserted: list[dict] = []

    def table(name):
        handle = MagicMock()
        if name == "email_sync_state":
            state = _health_state()
            state["consecutive_failures"] = 3
            handle.select.return_value.execute.return_value.data = [state]
        elif name in {"attachments", "email_ingestion_items"}:
            handle.select.return_value.eq.return_value.range.side_effect = _dead_letter_scan([])
        elif name == "operational_incidents":
            handle.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = None
            handle.select.return_value.eq.return_value.execute.return_value.data = []
            handle.select.return_value.eq.return_value.like.return_value.execute.return_value.data = []
            handle.insert.side_effect = lambda payload: (inserted.append(payload), MagicMock())[1]
        return handle

    client.table.side_effect = table
    asyncio.run(EmailSyncHealthEvaluator(client, mock_config, None).evaluate_once())

    assert any(row["incident_type"] == "repeated_failures" for row in inserted)


def test_safe_incident_defaults_keep_user_scope_optional():
    incident = SafeIncident("email-sync:integration-1:stale_poll", "gmail", "stale_poll", "warning", "stale")

    assert incident.user_id is None
    assert incident.last_success_at is None


def test_new_integration_first_poll_in_flight_does_not_open_stale_incident(mock_config):
    """7b: a new integration whose first poll is still running must not be stale."""
    now = datetime.now(timezone.utc)
    state = _health_state()
    state["last_success_at"] = None
    state["last_started_at"] = now.isoformat()
    state["consecutive_failures"] = 0

    client = MagicMock()
    inserted: list[dict] = []

    def table(name):
        handle = MagicMock()
        if name == "email_sync_state":
            handle.select.return_value.execute.return_value.data = [state]
        elif name in {"attachments", "email_ingestion_items"}:
            handle.select.return_value.eq.return_value.range.side_effect = _dead_letter_scan([])
        elif name == "operational_incidents":
            handle.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = None
            handle.select.return_value.eq.return_value.execute.return_value.data = []
            handle.select.return_value.eq.return_value.like.return_value.execute.return_value.data = []
            handle.insert.side_effect = lambda payload: (inserted.append(payload), MagicMock())[1]
        return handle

    client.table.side_effect = table
    asyncio.run(EmailSyncHealthEvaluator(client, mock_config, None).evaluate_once())

    assert inserted == [], "first poll in-flight should not open stale_poll"


def test_new_integration_never_started_has_grace_and_no_stale_incident(mock_config):
    """Both timestamps null — before first claim — must not be stale."""
    state = _health_state()
    state["last_success_at"] = None
    state["last_started_at"] = None
    state["consecutive_failures"] = 0

    client = MagicMock()
    inserted: list[dict] = []

    def table(name):
        handle = MagicMock()
        if name == "email_sync_state":
            handle.select.return_value.execute.return_value.data = [state]
        elif name in {"attachments", "email_ingestion_items"}:
            handle.select.return_value.eq.return_value.range.side_effect = _dead_letter_scan([])
        elif name == "operational_incidents":
            handle.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = None
            handle.select.return_value.eq.return_value.execute.return_value.data = []
            handle.select.return_value.eq.return_value.like.return_value.execute.return_value.data = []
            handle.insert.side_effect = lambda payload: (inserted.append(payload), MagicMock())[1]
        return handle

    client.table.side_effect = table
    asyncio.run(EmailSyncHealthEvaluator(client, mock_config, None).evaluate_once())

    assert inserted == []

def test_stale_poll_after_grace_does_open_incident(mock_config):
    """After warning_seconds with no success, stale_poll must open."""
    now = datetime.now(timezone.utc)
    state = _health_state()
    # last_started 40 minutes ago, warning is 1800s (30m) -> should be stale warning
    state["last_success_at"] = None
    state["last_started_at"] = (now - timedelta(seconds=mock_config.email_health_warning_seconds + 600)).isoformat()
    state["consecutive_failures"] = 0

    client = MagicMock()
    inserted: list[dict] = []

    def table(name):
        handle = MagicMock()
        if name == "email_sync_state":
            handle.select.return_value.execute.return_value.data = [state]
        elif name in {"attachments", "email_ingestion_items"}:
            handle.select.return_value.eq.return_value.range.side_effect = _dead_letter_scan([])
        elif name == "operational_incidents":
            handle.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = None
            handle.select.return_value.eq.return_value.execute.return_value.data = []
            handle.select.return_value.eq.return_value.like.return_value.execute.return_value.data = []
            handle.insert.side_effect = lambda payload: (inserted.append(payload), MagicMock())[1]
        return handle

    client.table.side_effect = table
    asyncio.run(EmailSyncHealthEvaluator(client, mock_config, None).evaluate_once())

    assert any(row["incident_type"] == "stale_poll" for row in inserted)


# --- Behaviours inherited from the removed legacy poller -------------------
# These were regression tests against selko.workers.email_fetch. That module is
# gone, but the production lessons behind them are not, so they are re-asserted
# against the durable v2 implementation that replaced it.


def _sync_claim():
    return SyncClaim(
        integration_id="integration-1",
        user_id="user-1",
        provider="outlook",
        run_id="run-1",
        run_kind="incremental",
    )


@pytest.mark.parametrize("provider", ["gmail", "outlook"])
@pytest.mark.asyncio
async def test_discover_dispatch_awaits_provider_discovery(mock_config, fake_pg_pool, provider):
    """The public discovery dispatcher must return provider totals, not a coroutine."""
    worker = EmailIngestionWorker(MagicMock(), mock_config, "worker-1", pg_pool=fake_pg_pool)
    claim = replace(_sync_claim(), provider=provider)
    expected = {"provider_ids_seen": 2, "items_inserted": 1, "items_existing": 1}

    with patch.object(worker, f"_discover_{provider}", new=AsyncMock(return_value=expected)) as discover:
        result = await worker.discover(claim)

    assert result == expected
    discover.assert_awaited_once_with(claim)


@pytest.mark.parametrize("provider", ["gmail", "outlook"])
@pytest.mark.asyncio
async def test_reconcile_dispatch_awaits_provider_discovery(mock_config, fake_pg_pool, provider):
    """Reconciliation must use the same awaited provider-dispatch contract."""
    worker = EmailIngestionWorker(MagicMock(), mock_config, "worker-1", pg_pool=fake_pg_pool)
    claim = replace(_sync_claim(), provider=provider)
    expected = {"provider_ids_seen": 3, "items_inserted": 2, "items_existing": 1}

    with patch.object(
        worker,
        f"_discover_{provider}",
        new=AsyncMock(return_value=expected),
    ) as discover:
        result = await worker.reconcile(claim, lookback_days=14)

    assert result == expected
    discover.assert_awaited_once_with(claim, lookback_days=14)


def test_outlook_deleted_folder_is_removed_without_blocking_later_folders(mock_config):
    """One folder's 404 must not abort the pass or lose other folders' cursors."""
    deleted = {"id": "row-deleted", "provider_folder_id": "deleted", "is_included": True, "is_scannable": True}
    current = {"id": "row-current", "provider_folder_id": "current", "is_included": True, "is_scannable": True}
    client = MagicMock()
    client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[deleted, current]
    )
    worker = EmailIngestionWorker(client, mock_config, "worker-1")

    from selko.services.outlook import GraphHttpError

    with patch("selko.workers.email_ingestion.get_access_token", return_value="token"), \
         patch("selko.workers.email_ingestion.resolve_well_known_folder_ids", return_value={}), \
         patch("selko.workers.email_ingestion.fetch_mail_folders", return_value=[]), \
         patch("selko.workers.email_ingestion.normalize_mail_folders", return_value=[]), \
         patch("selko.workers.email_ingestion.upsert_discovered_folders"), \
         patch("selko.workers.email_ingestion.record_graph_failure"), \
         patch("selko.workers.email_ingestion.fetch_message_changes",
               side_effect=[GraphHttpError(404, "folder missing"), ([], "cursor-current")]) as changes, \
         patch.object(worker.repository, "require_heartbeat", new=AsyncMock()), \
         patch.object(worker.repository, "upsert_discovered", new=AsyncMock(return_value={"provider_ids_seen": 1, "items_inserted": 1, "items_existing": 0})) as upsert:
        asyncio.run(worker._discover_outlook(_sync_claim()))

    assert changes.call_count == 2, "the second folder must still be polled"
    client.table.return_value.delete.return_value.eq.assert_any_call("id", "row-deleted")
    assert upsert.call_args.kwargs["folder_id"] == "row-current"
    assert upsert.call_args.kwargs["cursor"] == "cursor-current"


def test_gmail_history_expiry_captures_replacement_cursor_before_listing(mock_config):
    """The replacement historyId must be read before the bounded listing.

    Reading it afterwards loses any message that arrives during the listing.
    """
    order: list[str] = []
    client = MagicMock()
    client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
        data={"sync_cursor": "expired-cursor"}
    )
    client.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    worker = EmailIngestionWorker(client, mock_config, "worker-1")

    def expired(*_args):
        order.append("history")
        raise GmailHistoryExpiredError("expired")

    def profile(*_args):
        order.append("profile")
        return {"historyId": "replacement-cursor"}

    def listing(*_args, **_kwargs):
        order.append("search")
        return []

    claim = SyncClaim("integration-1", "user-1", "gmail", "run-1", "incremental")
    with patch("selko.workers.email_ingestion.get_gmail_credentials", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.build_service", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.list_labels", return_value=[]), \
         patch("selko.workers.email_ingestion.upsert_discovered_folders"), \
         patch("selko.workers.email_ingestion.fetch_history_message_ids", side_effect=expired), \
         patch("selko.workers.email_ingestion.get_user_profile", side_effect=profile), \
         patch("selko.workers.email_ingestion.list_message_ids", side_effect=listing), \
         patch.object(worker.repository, "require_heartbeat", new=AsyncMock()), \
         patch.object(worker.repository, "upsert_discovered", new=AsyncMock(return_value={"provider_ids_seen": 1, "items_inserted": 1, "items_existing": 0})) as upsert:
        asyncio.run(worker._discover_gmail(claim))

    assert order == ["history", "profile", "search"]
    assert upsert.call_args.kwargs["cursor"] == "replacement-cursor"


def _gmail_discovery_client(cursor: str | None = "history-cursor"):
    client = MagicMock()
    client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
        data={"sync_cursor": cursor}
    )
    client.table.return_value.select.return_value.eq.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(data=[])
    return client


def test_gmail_incremental_poll_does_not_fetch_the_user_profile(mock_config):
    """6c: the profile call is only needed where replacement_cursor is used.

    `get_user_profile` used to run unconditionally on every discovery pass, but
    its result is only consumed on initial sync and on History expiry. On the
    healthy incremental path that was one wasted Gmail call per integration per
    five-minute poll, forever.
    """
    worker = EmailIngestionWorker(_gmail_discovery_client(), mock_config, "worker-1")
    claim = SyncClaim("integration-1", "user-1", "gmail", "run-1", "incremental")

    with patch("selko.workers.email_ingestion.get_gmail_credentials", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.build_service", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.list_labels", return_value=[]), \
         patch("selko.workers.email_ingestion.upsert_discovered_folders"), \
         patch("selko.workers.email_ingestion.fetch_history_message_ids", return_value=([], "next-cursor")), \
         patch("selko.workers.email_ingestion.get_user_profile") as profile, \
         patch.object(worker.repository, "require_heartbeat", new=AsyncMock()), \
         patch.object(worker.repository, "upsert_discovered", new=AsyncMock(return_value={"provider_ids_seen": 1, "items_inserted": 1, "items_existing": 0})):
        asyncio.run(worker._discover_gmail(claim))

    profile.assert_not_called()


def test_gmail_discovery_batches_metadata_and_matches_the_serial_result(mock_config):
    """6a: batching must not change what discovery decides, only what it costs.

    The serial path issued one `get_message_metadata` call per message. The
    batch path collapses those into one HTTP request per 100 IDs, so this pins
    the two invariants that matter: every identity still gets classified, and a
    message deleted between listing and metadata fetch still becomes `removed`
    rather than failing the pass.
    """
    worker = EmailIngestionWorker(_gmail_discovery_client(), mock_config, "worker-1")
    claim = SyncClaim("integration-1", "user-1", "gmail", "run-1", "incremental")

    batched = {
        "message-eligible": {"id": "message-eligible", "labelIds": ["INBOX"]},
        # 404 in the batch callback: deleted between listing and fetch.
        "message-deleted": {"id": "message-deleted", "_deleted": True},
        "message-excluded": {"id": "message-excluded", "labelIds": ["TRASH"]},
    }

    with patch("selko.workers.email_ingestion.get_gmail_credentials", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.build_service", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.list_labels", return_value=[]), \
         patch("selko.workers.email_ingestion.upsert_discovered_folders"), \
         patch("selko.workers.email_ingestion.fetch_history_message_ids",
               return_value=(list(batched), "next-cursor")), \
         patch("selko.workers.email_ingestion.get_messages_metadata_batch",
               return_value=batched) as batch, \
         patch.object(worker.repository, "require_heartbeat", new=AsyncMock()), \
         patch.object(worker.repository, "upsert_discovered", new=AsyncMock(return_value={"provider_ids_seen": 1, "items_inserted": 1, "items_existing": 0})) as upsert:
        asyncio.run(worker._discover_gmail(claim))

    # One batched call for the whole page, not one call per message.
    batch.assert_called_once()
    assert list(batch.call_args.args[1]) == list(batched)

    discovered = {item["provider_message_id"]: item for item in upsert.call_args.args[1]}
    assert set(discovered) == set(batched)
    assert discovered["message-eligible"]["change_kind"] == "upsert"
    assert discovered["message-deleted"]["change_kind"] == "removed"
    assert discovered["message-excluded"]["change_kind"] == "removed"


def test_gmail_reconcile_skips_known_identities_and_resumes_next_pass(mock_config):
    """6b: the reconcile bound must make forward progress, not re-truncate.

    A plain `identities[:cap]` would hand the same prefix to every pass, so a
    mailbox larger than the cap would never reconcile its tail. Filtering out
    identities already in `email_ingestion_items` first is what makes the cap
    resumable: this pass commits what it processed, so the next pass sees a
    smaller undiscovered set and continues from there.
    """
    mock_config.email_reconcile_max_identities = 2
    worker = EmailIngestionWorker(_gmail_discovery_client(cursor=None), mock_config, "worker-1")
    claim = SyncClaim("integration-1", "user-1", "gmail", "run-1", "reconcile")

    window = [f"message-{i}" for i in range(6)]
    already_known = {"message-0", "message-1", "message-2"}

    with patch("selko.workers.email_ingestion.get_gmail_credentials", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.build_service", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.list_labels", return_value=[]), \
         patch("selko.workers.email_ingestion.upsert_discovered_folders"), \
         patch("selko.workers.email_ingestion.get_user_profile", return_value={"historyId": "h"}), \
         patch("selko.workers.email_ingestion.list_message_ids",
               return_value=[{"id": mid} for mid in window]), \
         patch.object(worker.repository, "known_provider_message_ids", new=AsyncMock(return_value=already_known)), \
         patch("selko.workers.email_ingestion.get_messages_metadata_batch",
               return_value={}) as batch, \
         patch.object(worker.repository, "require_heartbeat", new=AsyncMock()), \
         patch.object(worker.repository, "upsert_discovered", new=AsyncMock(return_value={"provider_ids_seen": 1, "items_inserted": 1, "items_existing": 0})):
        asyncio.run(worker._discover_gmail(claim, lookback_days=90))

    requested = list(batch.call_args.args[1])
    # Known identities are never re-fetched, and what remains honours the cap.
    assert not already_known.intersection(requested)
    assert requested == ["message-3", "message-4"]


def test_gmail_reconcile_does_not_bound_the_incremental_path(mock_config, fake_pg_pool):
    """Only reconcile passes are bounded; an incremental delta is already O(delta)."""
    mock_config.email_reconcile_max_identities = 1
    worker = EmailIngestionWorker(_gmail_discovery_client(), mock_config, "worker-1")
    claim = SyncClaim("integration-1", "user-1", "gmail", "run-1", "incremental")

    with patch("selko.workers.email_ingestion.get_gmail_credentials", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.build_service", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.list_labels", return_value=[]), \
         patch("selko.workers.email_ingestion.upsert_discovered_folders"), \
         patch("selko.workers.email_ingestion.fetch_history_message_ids",
               return_value=(["a", "b", "c"], "next-cursor")), \
         patch.object(worker.repository, "known_provider_message_ids", new=AsyncMock()) as known, \
         patch("selko.workers.email_ingestion.get_messages_metadata_batch", return_value={}) as batch, \
         patch.object(worker.repository, "require_heartbeat", new=AsyncMock()), \
         patch.object(worker.repository, "upsert_discovered", new=AsyncMock(return_value={"provider_ids_seen": 1, "items_inserted": 1, "items_existing": 0})):
        asyncio.run(worker._discover_gmail(claim))

    known.assert_not_called()
    assert list(batch.call_args.args[1]) == ["a", "b", "c"]


def test_known_provider_message_ids_chunks_its_in_filter(mock_config, fake_pg_pool):
    """A full reconcile window would overflow the PostgREST request line."""
    from selko.services.email_ingestion import KNOWN_ID_QUERY_CHUNK

    ids = [f"message-{i}" for i in range(KNOWN_ID_QUERY_CHUNK * 2 + 5)]

    asyncio.run(
        EmailIngestionRepository(mock_config, fake_pg_pool)
        .known_provider_message_ids("integration-1", ids)
    )

    # One query per chunk; each binds a chunk of ids via ANY($2::text[]).
    chunk_calls = [
        args for sql, args in fake_pg_pool.calls if "provider_message_id = ANY" in sql
    ]
    assert len(chunk_calls) == 3
    bound = [list(args[1]) for args in chunk_calls]
    assert all(len(chunk) <= KNOWN_ID_QUERY_CHUNK for chunk in bound)
    assert [mid for chunk in bound for mid in chunk] == ids


def test_attachment_failure_cannot_touch_provider_cursors(mock_config, fake_pg_pool):
    """Attachment work is a separate claim, so it can never rewind discovery.

    The legacy poller fetched attachments inline and had to be careful not to
    commit a cursor afterwards; v2 removes the hazard structurally.
    """
    client = MagicMock()
    worker = EmailIngestionWorker(client, mock_config, "attachment-worker")
    attachment = {"id": "attachment-1", "email_id": "email-1", "attempts": 1, "max_attempts": 8,
                  "provider_attachment_id": "att-1", "mime_type": "image/png", "filename": "x.png"}

    with patch.object(worker.repository, "claim_attachment", new=AsyncMock(return_value=attachment)), \
         patch.object(worker, "acquire_attachment", new=AsyncMock(side_effect=RuntimeError("download failed"))), \
         patch.object(worker.repository, "finish_attachment", new=AsyncMock(return_value=True)) as finish, \
         patch.object(worker.repository, "upsert_discovered", new=AsyncMock(return_value={"provider_ids_seen": 1, "items_inserted": 1, "items_existing": 0})) as upsert:
        assert asyncio.run(worker.run_attachment_once()) is True

    assert finish.call_args[0][2] == "retry"
    upsert.assert_not_called()
    touched = {call.args[0] for call in client.table.call_args_list if call.args}
    assert "integrations" not in touched
    assert "email_sync_state" not in touched


def test_outlook_attachment_decodes_base64_and_skips_item_attachments(mock_config):
    """Only fileAttachment carries contentBytes; itemAttachment must not store."""
    import base64 as _b64

    client = MagicMock()
    client.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value.data = {
        "user_id": "user-1", "email_provider": "outlook",
        "provider_message_id": "message-1", "integration_id": "integration-1",
    }
    worker = EmailIngestionWorker(client, mock_config, "attachment-worker")
    encoded = _b64.b64encode(b"outlook bytes").decode("ascii")
    listing = [
        {"@odata.type": "#microsoft.graph.itemAttachment", "id": "item-1"},
        {"@odata.type": "#microsoft.graph.fileAttachment", "id": "file-1",
         "name": "document.txt", "contentType": "text/plain", "contentBytes": encoded},
    ]

    with patch("selko.workers.email_ingestion.get_access_token", return_value="token"), \
         patch("selko.workers.email_ingestion.list_attachments", return_value=listing), \
         patch("selko.workers.email_ingestion.calculate_content_hash", return_value="hash"), \
         patch("selko.workers.email_ingestion.upload_to_storage", return_value="path") as upload:
        stored = asyncio.run(worker.acquire_attachment({**{"id": "a", "email_id": "email-1"},
                                            "provider_attachment_id": "file-1",
                                            "mime_type": "text/plain", "filename": "document.txt"}))
        unsupported = asyncio.run(worker.acquire_attachment({**{"id": "b", "email_id": "email-1"},
                                                 "provider_attachment_id": "item-1",
                                                 "mime_type": "text/plain", "filename": "item"}))

    assert stored == "stored"
    assert unsupported == "unsupported"
    assert upload.call_args[0][3] == b"outlook bytes"


def test_missing_credentials_are_classified_as_auth_and_expire_the_integration(mock_config, fake_pg_pool):
    """A missing credential must mark the integration expired, not look like a
    deleted message — otherwise it retries forever and never prompts reconnect."""
    exc = ProviderAuthenticationError("Gmail credentials are unavailable")
    assert safe_error_code(exc) == "provider_auth_expired"

    fake_pg_pool.rows.append(True)
    repository = EmailIngestionRepository(mock_config, fake_pg_pool)
    asyncio.run(repository.fail_sync(_sync_claim(), "worker-1", exc))

    sql, args = fake_pg_pool.calls[0]
    assert "fail_email_sync" in sql
    assert args[3] == "provider_auth_expired"
    assert args[7] is True


# --- Error classification regression table (top-up increment 2) -------------
#
# Pre-fix: `safe_error_code` substring-matched the message, so Gmail 401
# "Invalid Credentials" and `RefreshError: invalid_grant` both classified as
# `parse_invalid` and were dead-lettered on the FIRST attempt — permanent data
# loss. Below is the structural classification table the fix enforces.

def _gmail_error(status, reason=None, message="provider error"):
    return GmailError(message, status_code=status, reason=reason)


@pytest.mark.parametrize(
    "exc, expected_code, expected_retryable, expected_auth_failure",
    [
        # Typed auth paths — auth is a TYPE, not a string.
        (ProviderAuthenticationError("Gmail credentials are unavailable"),
         "provider_auth_expired", True, True),
        (GmailAuthError("Gmail credentials expired or revoked: invalid_grant"),
         "provider_auth_expired", True, True),
        # Genuine permanence is the only terminal-on-first-attempt path.
        (ProviderPermanentError("unparseable payload"),
         "provider_permanent", False, False),
        # Gmail status_code (now carried — was missing, which is why the bug existed).
        (_gmail_error(401, reason="authError", message='Invalid Credentials'),
         "provider_auth_expired", True, True),
        (_gmail_error(403, reason="insufficientPermissions"),
         "provider_auth_expired", True, True),
        (_gmail_error(403, reason="userRateLimitExceeded"),
         "provider_rate_limited", True, False),
        (_gmail_error(429, message="Too Many Requests"),
         "provider_rate_limited", True, False),
        (_gmail_error(403, reason="other"), "provider_forbidden", True, False),
        (_gmail_error(500), "provider_transient", True, False),
        (_gmail_error(503), "provider_transient", True, False),
        (_gmail_error(404, message="Not Found"), "provider_not_found", True, False),
        # GraphHttpError carries graph_error_code rather than Gmail reason.
        (GraphHttpError(401, "InvalidAuthenticationToken", graph_error_code="InvalidAuthenticationToken"),
         "provider_auth_expired", True, True),
        (GraphHttpError(403, "denied", graph_error_code="AuthorizationRequestDenied"),
         "provider_auth_expired", True, True),
        (GraphHttpError(403, "throttle", graph_error_code="TooManyRequests"),
         "provider_rate_limited", True, False),
        (GraphHttpError(429, "TooManyRequests", graph_error_code="TooManyRequests"),
         "provider_rate_limited", True, False),
        (GraphHttpError(404, "not found", graph_error_code="notFound"),
         "provider_not_found", True, False),
        (GraphHttpError(503, "Service Unavailable", graph_error_code="unknown"),
         "provider_transient", True, False),
        # 404 is removed by the caller, not failed — but classify must still be stable.
        (ProviderMessageMissingError("message deleted before acquire"),
         "provider_message_missing", True, False),
    ],
)
def test_email_error_classification_table(exc, expected_code, expected_retryable, expected_auth_failure):
    classification = classify_email_error(exc)
    assert classification.code == expected_code
    assert classification.retryable is expected_retryable
    assert classification.auth_failure is expected_auth_failure


def test_gmail_invalid_credentials_message_no_longer_dead_letters():
    """Regression: substring match on 'invalid' must not classify Gmail 401
    'Invalid Credentials' as parse_invalid/terminal. The structural classifier
    keys on status_code=401 and returns provider_auth_expired (retryable)."""
    exc = _gmail_error(401, message="Invalid Credentials")
    classification = classify_email_error(exc)

    assert classification.code == "provider_auth_expired"
    assert classification.code != "parse_invalid"
    assert classification.retryable is True
    assert classification.auth_failure is True


def test_refresh_error_invalid_grant_no_longer_dead_letters():
    """Regression: `RefreshError: ... invalid_grant` contained the substring
    'invalid' and was terminal on attempt #1. GmailAuthError is now a typed
    auth failure that retries until the user reconnects."""
    exc = GmailAuthError("Gmail credentials expired or revoked: invalid_grant")
    classification = classify_email_error(exc)

    assert classification.code == "provider_auth_expired"
    assert classification.code != "parse_invalid"
    assert classification.retryable is True
    assert classification.auth_failure is True


def test_safe_error_code_is_the_classifier_not_a_shadowed_substring_matcher():
    """Regression for the duplicate definition reported on PR #242.

    `safe_error_code` and `safe_error_detail` were each defined twice in
    `services/email_ingestion.py`, and the old substring-based pair came second,
    so it won at import time. Every increment-2 regression test called
    `classify_email_error` directly, so the suite stayed green while the workers
    — which import `safe_error_code` — kept using the substring matcher and kept
    dead-lettering `invalid_grant` as `parse_invalid`.

    Assert through the exported name that production imports, not the classifier
    it is supposed to delegate to.
    """
    from selko.services import email_ingestion as module

    revoked = GmailAuthError("Gmail credentials expired or revoked: invalid_grant")
    assert module.safe_error_code(revoked) == "provider_auth_expired"
    assert module.safe_error_code(revoked) == classify_email_error(revoked).code

    unauthorized = _gmail_error(401, message="Invalid Credentials")
    assert module.safe_error_code(unauthorized) == "provider_auth_expired"

    # And exactly one definition survives, so no later import can re-shadow it.
    source = Path(module.__file__).read_text()
    assert source.count("\ndef safe_error_code(") == 1
    assert source.count("\ndef safe_error_detail(") == 1


def test_no_acquisition_failure_is_terminal_on_first_attempt(mock_config, fake_pg_pool):
    """A transient provider error must NOT pass p_terminal=True on the first
    attempt — `fail_email_ingestion_item` dead-letters only by exhausting
    max_attempts server-side (or via explicit ProviderPermanentError)."""
    fake_pg_pool.rows.append(True)
    repository = EmailIngestionRepository(mock_config, fake_pg_pool)

    # A plain Gmail 401 — the pre-fix data-loss input.
    asyncio.run(repository.fail_item("item-1", "worker-1", _gmail_error(401, message="Invalid Credentials")))

    sql, args = fake_pg_pool.calls[0]
    assert "fail_email_ingestion_item" in sql
    assert args[2] == "provider_auth_expired"
    assert args[5] is False


def test_permanent_error_is_terminal_on_first_attempt(mock_config, fake_pg_pool):
    """The only first-attempt terminal path is a deliberate ProviderPermanentError."""
    fake_pg_pool.rows.append(True)
    repository = EmailIngestionRepository(mock_config, fake_pg_pool)

    asyncio.run(repository.fail_item("item-1", "worker-1", ProviderPermanentError("unparseable")))

    sql, args = fake_pg_pool.calls[0]
    assert "fail_email_ingestion_item" in sql
    assert args[2] == "provider_permanent"
    assert args[5] is True


def test_gmail_401_during_discovery_expires_the_integration(mock_config, fake_pg_pool):
    """Regression: Gmail 401 used to never reach p_auth_failure=True (so the
    ConnectionRecovery card never fired for Gmail). The classifier now returns
    auth_failure=True from the typed/structured path."""
    fake_pg_pool.rows.append(True)
    repository = EmailIngestionRepository(mock_config, fake_pg_pool)

    asyncio.run(repository.fail_sync(_sync_claim(), "worker-1", _gmail_error(401, message="Invalid Credentials")))

    sql, args = fake_pg_pool.calls[0]
    assert "fail_email_sync" in sql
    assert args[3] == "provider_auth_expired"
    assert args[7] is True


def test_run_acquisition_once_does_not_mark_terminal_on_code(mock_config, fake_pg_pool):
    """The worker must not pass a hardcoded terminal flag derived from a code
    substring; the default classifier path inside fail_item handles it."""
    client = MagicMock()
    worker = EmailIngestionWorker(client, mock_config, "worker-1", pg_pool=fake_pg_pool)
    item = {"id": "item-1", "provider": "gmail", "user_id": "u",
            "provider_message_id": "m", "provider_folder_ids": ["INBOX"]}

    captured: list[tuple[str, tuple]] = []

    async def fake_fail_item(item_id, worker_id, exc, *, terminal=None):
        captured.append((exc, terminal))
        return True

    def fake_acquire(_item):
        # Simulate a Gmail 401 raised mid-acquisition (the data-loss input).
        raise _gmail_error(401, message="Invalid Credentials")

    with patch.object(worker.repository, "claim_item", new=AsyncMock(return_value=item)), \
         patch.object(worker.repository, "fail_item", new=AsyncMock(side_effect=fake_fail_item)), \
         patch.object(worker, "acquire_item", new=AsyncMock(side_effect=fake_acquire)):
        asyncio.run(worker.run_acquisition_once())

    assert captured, "fail_item should have been called"
    exc, terminal = captured[0]
    assert classify_email_error(exc).code == "provider_auth_expired"
    # The worker passes no terminal flag: the classifier inside fail_item
    # decides (retryable on code, terminal only for ProviderPermanentError).
    assert terminal is None


def test_outlook_token_expiring_mid_pass_refreshes_instead_of_expiring_the_account(
    mock_config,
):
    """A 401 partway through a multi-folder pass must not end the run.

    Graph access tokens last about an hour; a 90-day reconciliation across
    several folders can run longer. Propagating the 401 maps to
    provider_auth_expired, which marks the integration expired and halts
    ingestion until the user reconnects — even though the refresh token is fine.
    """
    from selko.services.outlook import GraphHttpError

    folders = [
        {"id": "row-1", "provider_folder_id": "f1", "is_included": True, "is_scannable": True},
        {"id": "row-2", "provider_folder_id": "f2", "is_included": True, "is_scannable": True},
    ]
    client = MagicMock()
    client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
        data=folders
    )
    worker = EmailIngestionWorker(client, mock_config, "worker-1")

    tokens_used: list[str] = []

    def changes(tok, *_args, **_kwargs):
        tokens_used.append(tok)
        if tok == "stale-token":
            raise GraphHttpError(401, "InvalidAuthenticationToken")
        return ([], "cursor-new")

    with patch("selko.workers.email_ingestion.get_access_token",
               side_effect=["stale-token", "fresh-token"]), \
         patch("selko.workers.email_ingestion.resolve_well_known_folder_ids", return_value={}), \
         patch("selko.workers.email_ingestion.fetch_mail_folders", return_value=[]), \
         patch("selko.workers.email_ingestion.normalize_mail_folders", return_value=[]), \
         patch("selko.workers.email_ingestion.upsert_discovered_folders"), \
         patch("selko.workers.email_ingestion.record_graph_failure"), \
         patch("selko.workers.email_ingestion.fetch_message_changes", side_effect=changes), \
         patch.object(worker.repository, "require_heartbeat", new=AsyncMock()), \
         patch.object(worker.repository, "upsert_discovered", new=AsyncMock(return_value={"provider_ids_seen": 1, "items_inserted": 1, "items_existing": 0})) as upsert:
        asyncio.run(worker._discover_outlook(_sync_claim()))

    assert "fresh-token" in tokens_used, "expected one forced refresh"
    # Both folders still commit their cursors; the run does not fail.
    assert upsert.call_count == 2
    assert {c.kwargs["folder_id"] for c in upsert.call_args_list} == {"row-1", "row-2"}


def test_outlook_resync_sentinel_is_never_persisted_as_a_cursor(mock_config):
    """Committing RESYNC_REQUIRED would be sent to Graph as a URL forever."""
    from selko.services.outlook import GraphHttpError, RESYNC_REQUIRED

    folder = {"id": "row-1", "provider_folder_id": "f1", "is_included": True, "is_scannable": True}
    client = MagicMock()
    client.table.return_value.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(
        data=[folder]
    )
    worker = EmailIngestionWorker(client, mock_config, "worker-1")

    with patch("selko.workers.email_ingestion.get_access_token", return_value="token"), \
         patch("selko.workers.email_ingestion.resolve_well_known_folder_ids", return_value={}), \
         patch("selko.workers.email_ingestion.fetch_mail_folders", return_value=[]), \
         patch("selko.workers.email_ingestion.normalize_mail_folders", return_value=[]), \
         patch("selko.workers.email_ingestion.upsert_discovered_folders"), \
         patch("selko.workers.email_ingestion.record_graph_failure"), \
         patch("selko.workers.email_ingestion.fetch_message_changes",
               return_value=([], RESYNC_REQUIRED)), \
         patch.object(worker.repository, "require_heartbeat", new=AsyncMock()), \
         patch.object(worker.repository, "upsert_discovered", new=AsyncMock(return_value={"provider_ids_seen": 1, "items_inserted": 1, "items_existing": 0})) as upsert:
        with pytest.raises(GraphHttpError):
            asyncio.run(worker._discover_outlook(_sync_claim()))

    committed = [c.kwargs.get("cursor") for c in upsert.call_args_list]
    assert RESYNC_REQUIRED not in committed

def test_discover_heartbeats_around_long_listing(mock_config):
    """R4: listing must heartbeat before and after long provider calls, not just before upsert."""
    from unittest.mock import AsyncMock, MagicMock, patch
    from selko.workers.email_ingestion import EmailIngestionWorker
    from selko.services.email_ingestion import SyncClaim

    def _gmail_discovery_client(cursor="cursor-1"):
        # minimal client for _integration fetch mock
        c = MagicMock()
        c.table.return_value.select.return_value.eq.return_value.single.return_value.execute.return_value = MagicMock(
            data={"sync_cursor": cursor}
        )
        return c

    worker = EmailIngestionWorker(_gmail_discovery_client(), mock_config, "w-1")
    claim = SyncClaim("integration-1", "user-1", "gmail", "run-1", "incremental")
    # fetch_history returns 1 id, but we heartbeat around it
    with patch("selko.workers.email_ingestion.get_gmail_credentials", return_value=MagicMock()),          patch("selko.workers.email_ingestion.build_service", return_value=MagicMock()),          patch("selko.workers.email_ingestion.list_labels", return_value=[]),          patch("selko.workers.email_ingestion.upsert_discovered_folders"),          patch("selko.workers.email_ingestion.fetch_history_message_ids", return_value=(["m1"], "next")) as fh,          patch("selko.workers.email_ingestion.get_messages_metadata_batch", return_value={"m1": {"id": "m1", "labelIds": ["INBOX"]}}),          patch.object(worker.repository, "require_heartbeat", new=AsyncMock()) as hb,          patch.object(worker.repository, "upsert_discovered", new=AsyncMock(return_value={"provider_ids_seen":1, "items_inserted":1, "items_existing":0})):
        asyncio.run(worker._discover_gmail(claim))
        # At least 2 heartbeats for the history fetch (before+after) plus per-upsert
        assert hb.call_count >= 2, f"expected heartbeat around listing, got {hb.call_count}"
        assert fh.called


# --- C4: executor concurrency (acquire before claim) -------------------------


def _concurrency_config(mock_config, width: int):
    from dataclasses import replace
    return replace(
        mock_config,
        email_acquisition_concurrency=width,
        email_attachment_concurrency=width,
    )


class TestExecutorConcurrency:
    """C4: backpressure belongs at the claim, not at the work."""

    def _worker(self, mock_config, pool, width: int):
        from selko.workers.email_ingestion import EmailIngestionWorker
        return EmailIngestionWorker(
            MagicMock(), _concurrency_config(mock_config, width), "c4-worker",
            pg_pool=pool,
        )

    @pytest.mark.asyncio
    async def test_acquisition_respects_executor_width(self, mock_config, fake_pg_pool):
        """Concurrency 4 with 10 items — one claim loop, max 4 in flight, all 10 done."""
        items = [{"id": f"item-{i}", "change_kind": "upsert"} for i in range(10)]
        fake_pg_pool.rows = list(items) + [None] * 20
        worker = self._worker(mock_config, fake_pg_pool, 4)

        done = 0
        started = 0
        peak_in_flight = 0

        async def fake_acquire(item):
            nonlocal done, started, peak_in_flight
            started += 1
            peak_in_flight = max(peak_in_flight, started - done)
            await asyncio.sleep(0.01)
            done += 1
            return "email-1"

        with patch.object(worker, "acquire_item", new=AsyncMock(side_effect=fake_acquire)), \
             patch.object(worker.repository, "complete_item", new=AsyncMock(return_value=True)):
            accepted = 0
            while accepted < 10:
                accepted += int(await worker.run_acquisition_once())
                if accepted < 10:
                    await asyncio.sleep(0.011)
            while worker._acquisition_inflight:
                await asyncio.sleep(0.01)

        assert peak_in_flight <= 4
        assert done == 10

    @pytest.mark.asyncio
    async def test_saturated_acquisition_executor_does_not_block_attachments(
        self, mock_config, fake_pg_pool
    ):
        """A full acquisition executor must not block attachment work."""
        worker = self._worker(mock_config, fake_pg_pool, 1)
        await worker._acquisition_semaphore.acquire()
        try:
            with patch.object(
                worker.repository, "claim_attachment", new=AsyncMock(return_value=None)
            ) as claim:
                assert await worker.run_attachment_once() is False
            claim.assert_awaited_once()
        finally:
            worker._acquisition_semaphore.release()

    @pytest.mark.asyncio
    async def test_claim_never_precedes_acquire(self, mock_config, fake_pg_pool):
        """C4.1: a saturated executor must not claim a row and hold a lease."""
        items = [{"id": f"item-{i}", "change_kind": "upsert"} for i in range(10)]
        fake_pg_pool.rows = list(items) + [None] * 20
        worker = self._worker(mock_config, fake_pg_pool, 1)

        released = asyncio.Event()

        async def blocking_acquire(_item):
            await released.wait()

        with patch.object(worker, "acquire_item", new=AsyncMock(side_effect=blocking_acquire)):
            first = await worker.run_acquisition_once()
            assert first is True
            assert await worker.run_acquisition_once() is False
            released.set()
            await asyncio.wait(worker._acquisition_inflight, timeout=5)

        claim_calls = [sql for sql, _ in fake_pg_pool.calls if "claim_email_ingestion_item" in sql]
        assert len(claim_calls) == 1

    @pytest.mark.asyncio
    async def test_semaphore_released_when_claim_returns_none(self, mock_config, fake_pg_pool):
        """A no-work claim must not leak a permit."""
        worker = self._worker(mock_config, fake_pg_pool, 2)
        assert await worker.run_acquisition_once() is False
        assert worker._acquisition_semaphore._value == 2

    @pytest.mark.asyncio
    async def test_semaphore_released_when_claim_raises(self, mock_config, fake_pg_pool):
        """An error must not leak a permit."""

        async def boom(*_args, **_kwargs):
            raise RuntimeError("db down")

        fake_pg_pool.fetchrow = boom
        worker = self._worker(mock_config, fake_pg_pool, 2)
        with pytest.raises(Exception):
            await worker.run_acquisition_once()
        assert worker._acquisition_semaphore._value == 2


def test_every_concurrency_knob_is_read_by_a_worker():
    """Regression: after Inc2 three of these were read nowhere."""
    import pathlib

    source = "\n".join(
        p.read_text() for p in pathlib.Path("backend/selko/workers").rglob("*.py")
    )
    for knob in (
        "email_acquisition_concurrency",
        "email_attachment_concurrency",
        "llm_extraction_concurrency",
        "worker_calendar_sync_concurrency",
    ):
        assert knob in source, f"{knob} is not read by any worker"
