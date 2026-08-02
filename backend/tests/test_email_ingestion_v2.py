"""Regression coverage for durable polling email ingestion boundaries."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

from selko.services.email_ingestion import (
    EmailIngestionRepository,
    ProviderMessageMissingError,
    safe_error_code,
    safe_error_detail,
)
from selko.services.email_sync_health import (
    EmailSyncHealthEvaluator,
    ResendOperationalNotifier,
    SafeIncident,
)
from selko.services.msgraph import request_json, safe_url_template
from selko.workers.email_ingestion import EmailIngestionWorker


def test_expired_sync_claim_uses_durable_rpc_and_returns_run(mock_config):
    client = MagicMock()
    client.rpc.return_value.execute.return_value = MagicMock(data=[{
        "integration_id": "integration-1",
        "user_id": "user-1",
        "provider": "outlook",
        "run_id": "run-1",
        "run_kind": "incremental",
        "lease_expires_at": datetime.now(timezone.utc).isoformat(),
    }])

    claim = EmailIngestionRepository(client, mock_config).claim_due_sync("worker-1")

    assert claim.integration_id == "integration-1"
    client.rpc.assert_called_once_with(
        "claim_due_email_sync",
        {"p_worker_id": "worker-1", "p_lease_seconds": mock_config.email_lease_seconds},
    )


def test_ingestion_error_codes_are_stable_and_details_redacted():
    exc = ProviderMessageMissingError("Authorization: Bearer secret-token")

    assert safe_error_code(exc) == "provider_message_missing"
    assert safe_error_detail(exc) == "provider operation failed"


def test_outlook_unsupported_video_attachment_is_terminal_without_provider_call(mock_config):
    worker = EmailIngestionWorker(MagicMock(), mock_config, "attachment-worker")
    attachment = {"mime_type": "video/mp4", "filename": "clip.mp4"}

    assert worker.acquire_attachment(attachment) == "unsupported"


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


def test_gmail_inline_image_is_stored_rather_than_marked_unsupported(mock_config):
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

    with patch("selko.workers.email_ingestion.get_credentials", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.build_service", return_value=MagicMock()), \
         patch("selko.services.gmail.get_full_message", return_value=_gmail_message_with_inline_image()), \
         patch("selko.workers.email_ingestion.download_gmail_attachment", return_value=b"png-bytes") as download, \
         patch("selko.workers.email_ingestion.calculate_content_hash", return_value="hash"), \
         patch("selko.workers.email_ingestion.upload_to_storage", return_value="path/inline_0.png"):
        status = worker.acquire_attachment(attachment)

    assert status == "stored"
    assert download.call_args[0][2] == "inline-att-1"


def test_acquire_item_does_not_query_integrations_per_message(mock_config):
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

    with patch("selko.workers.email_ingestion.get_credentials", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.build_service", return_value=MagicMock()), \
         patch("selko.services.gmail.get_full_message", return_value={"id": "msg-1", "payload": {}}), \
         patch("selko.workers.email_ingestion.parse_gmail_message", return_value={}), \
         patch("selko.workers.email_ingestion.save_emails", return_value=[{"id": "email-1"}]), \
         patch.object(worker.repository, "ensure_attachment_descriptors", return_value=0), \
         patch.object(worker, "_integration") as integration_lookup:
        assert worker.acquire_item(item) == "email-1"

    integration_lookup.assert_not_called()


def _health_state() -> dict:
    return {
        "integration_id": "integration-1",
        "user_id": "user-1",
        "provider": "gmail",
        "last_success_at": datetime.now(timezone.utc).isoformat(),
        "last_started_at": datetime.now(timezone.utc).isoformat(),
        "consecutive_failures": 0,
    }


def test_dead_letter_attachment_incident_is_scoped_to_its_own_integration(mock_config):
    """An unscoped count would open the same incident on every integration."""
    client = MagicMock()
    filters: list[tuple[str, str]] = []

    def table(name):
        handle = MagicMock()
        if name == "email_sync_state":
            handle.select.return_value.execute.return_value.data = [_health_state()]
        elif name == "attachments":
            select = handle.select.return_value

            def eq(column, value):
                filters.append((column, value))
                return select

            select.eq.side_effect = eq
            select.execute.return_value = MagicMock(count=0)
        elif name == "email_ingestion_items":
            handle.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(count=0)
        elif name == "operational_incidents":
            handle.select.return_value.eq.return_value.execute.return_value.data = []
        return handle

    client.table.side_effect = table
    asyncio.run(EmailSyncHealthEvaluator(client, mock_config).evaluate_once())

    assert ("emails.integration_id", "integration-1") in filters


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
        elif name == "attachments":
            handle.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(count=0)
        elif name == "email_ingestion_items":
            handle.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(count=0)
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
            handle.select.return_value.eq.return_value.eq.return_value.execute.return_value = MagicMock(count=0)
        elif name == "operational_incidents":
            handle.select.return_value.eq.return_value.maybe_single.return_value.execute.return_value.data = None
            handle.select.return_value.eq.return_value.execute.return_value.data = []
            handle.insert.side_effect = lambda payload: (inserted.append(payload), MagicMock())[1]
        return handle

    client.table.side_effect = table
    asyncio.run(EmailSyncHealthEvaluator(client, mock_config, None).evaluate_once())

    assert any(row["incident_type"] == "repeated_failures" for row in inserted)


def test_safe_incident_defaults_keep_user_scope_optional():
    incident = SafeIncident("email-sync:integration-1:stale_poll", "gmail", "stale_poll", "warning", "stale")

    assert incident.user_id is None
    assert incident.last_success_at is None
