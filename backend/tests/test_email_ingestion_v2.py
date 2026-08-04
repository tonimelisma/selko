"""Regression coverage for durable polling email ingestion boundaries."""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

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
         patch.object(worker.repository, "require_heartbeat"), \
         patch.object(worker.repository, "upsert_discovered") as upsert:
        worker._discover_outlook(_sync_claim())

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
    with patch("selko.workers.email_ingestion.get_credentials", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.build_service", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.list_labels", return_value=[]), \
         patch("selko.workers.email_ingestion.upsert_discovered_folders"), \
         patch("selko.workers.email_ingestion.fetch_history_message_ids", side_effect=expired), \
         patch("selko.workers.email_ingestion.get_user_profile", side_effect=profile), \
         patch("selko.workers.email_ingestion.list_message_ids", side_effect=listing), \
         patch.object(worker.repository, "require_heartbeat"), \
         patch.object(worker.repository, "upsert_discovered") as upsert:
        worker._discover_gmail(claim)

    assert order == ["profile", "history", "profile", "search"]
    assert upsert.call_args.kwargs["cursor"] == "replacement-cursor"


def test_attachment_failure_cannot_touch_provider_cursors(mock_config):
    """Attachment work is a separate claim, so it can never rewind discovery.

    The legacy poller fetched attachments inline and had to be careful not to
    commit a cursor afterwards; v2 removes the hazard structurally.
    """
    client = MagicMock()
    worker = EmailIngestionWorker(client, mock_config, "attachment-worker")
    attachment = {"id": "attachment-1", "email_id": "email-1", "attempts": 1, "max_attempts": 8,
                  "provider_attachment_id": "att-1", "mime_type": "image/png", "filename": "x.png"}

    with patch.object(worker.repository, "claim_attachment", return_value=attachment), \
         patch.object(worker, "acquire_attachment", side_effect=RuntimeError("download failed")), \
         patch.object(worker.repository, "finish_attachment", return_value=True) as finish, \
         patch.object(worker.repository, "upsert_discovered") as upsert:
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
        stored = worker.acquire_attachment({**{"id": "a", "email_id": "email-1"},
                                            "provider_attachment_id": "file-1",
                                            "mime_type": "text/plain", "filename": "document.txt"})
        unsupported = worker.acquire_attachment({**{"id": "b", "email_id": "email-1"},
                                                 "provider_attachment_id": "item-1",
                                                 "mime_type": "text/plain", "filename": "item"})

    assert stored == "stored"
    assert unsupported == "unsupported"
    assert upload.call_args[0][3] == b"outlook bytes"


def test_missing_credentials_are_classified_as_auth_and_expire_the_integration(mock_config):
    """A missing credential must mark the integration expired, not look like a
    deleted message — otherwise it retries forever and never prompts reconnect."""
    exc = ProviderAuthenticationError("Gmail credentials are unavailable")
    assert safe_error_code(exc) == "provider_auth_expired"

    client = MagicMock()
    client.rpc.return_value.execute.return_value = MagicMock(data=True)
    repository = EmailIngestionRepository(client, mock_config)
    repository.fail_sync(_sync_claim(), "worker-1", exc)

    payload = client.rpc.call_args[0][1]
    assert payload["p_error_code"] == "provider_auth_expired"
    assert payload["p_auth_failure"] is True


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


def test_no_acquisition_failure_is_terminal_on_first_attempt(mock_config):
    """A transient provider error must NOT pass p_terminal=True on the first
    attempt — `fail_email_ingestion_item` dead-letters only by exhausting
    max_attempts server-side (or via explicit ProviderPermanentError)."""
    client = MagicMock()
    client.rpc.return_value.execute.return_value = MagicMock(data=True)
    repository = EmailIngestionRepository(client, mock_config)

    # A plain Gmail 401 — the pre-fix data-loss input.
    repository.fail_item("item-1", "worker-1", _gmail_error(401, message="Invalid Credentials"))

    payload = client.rpc.call_args[0][1]
    assert payload["p_error_code"] == "provider_auth_expired"
    assert payload["p_terminal"] is False


def test_permanent_error_is_terminal_on_first_attempt(mock_config):
    """The only first-attempt terminal path is a deliberate ProviderPermanentError."""
    client = MagicMock()
    client.rpc.return_value.execute.return_value = MagicMock(data=True)
    repository = EmailIngestionRepository(client, mock_config)

    repository.fail_item("item-1", "worker-1", ProviderPermanentError("unparseable"))

    payload = client.rpc.call_args[0][1]
    assert payload["p_error_code"] == "provider_permanent"
    assert payload["p_terminal"] is True


def test_gmail_401_during_discovery_expires_the_integration(mock_config):
    """Regression: Gmail 401 used to never reach p_auth_failure=True (so the
    ConnectionRecovery card never fired for Gmail). The classifier now returns
    auth_failure=True from the typed/structured path."""
    client = MagicMock()
    client.rpc.return_value.execute.return_value = MagicMock(data=True)
    repository = EmailIngestionRepository(client, mock_config)

    repository.fail_sync(_sync_claim(), "worker-1", _gmail_error(401, message="Invalid Credentials"))

    payload = client.rpc.call_args[0][1]
    assert payload["p_error_code"] == "provider_auth_expired"
    assert payload["p_auth_failure"] is True


def test_run_acquisition_once_does_not_mark_terminal_on_code(mock_config):
    """The worker must not pass a hardcoded terminal flag derived from a code
    substring; the default classifier path inside fail_item handles it."""
    client = MagicMock()
    worker = EmailIngestionWorker(client, mock_config, "worker-1")
    item = {"id": "item-1", "provider": "gmail", "user_id": "u",
            "provider_message_id": "m", "provider_folder_ids": ["INBOX"]}

    captured_payloads = []

    def fake_rpc(name, payload):
        if name == "claim_email_ingestion_item":
            return MagicMock(execute=lambda: MagicMock(data=[item]))
        if name == "fail_email_ingestion_item":
            captured_payloads.append(payload)
            return MagicMock(execute=lambda: MagicMock(data=True))
        return MagicMock(execute=lambda: MagicMock(data=False))

    client.rpc.side_effect = fake_rpc

    def fake_acquire(_item):
        # Simulate a Gmail 401 raised mid-acquisition (the data-loss input).
        raise _gmail_error(401, message="Invalid Credentials")

    with patch.object(worker, "acquire_item", side_effect=fake_acquire):
        asyncio.run(worker.run_acquisition_once())

    assert captured_payloads, "fail_item should have been called"
    assert captured_payloads[0]["p_error_code"] == "provider_auth_expired"
    assert captured_payloads[0]["p_terminal"] is False


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
         patch.object(worker.repository, "require_heartbeat"), \
         patch.object(worker.repository, "upsert_discovered") as upsert:
        worker._discover_outlook(_sync_claim())

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
         patch.object(worker.repository, "require_heartbeat"), \
         patch.object(worker.repository, "upsert_discovered") as upsert:
        with pytest.raises(GraphHttpError):
            worker._discover_outlook(_sync_claim())

    committed = [c.kwargs.get("cursor") for c in upsert.call_args_list]
    assert RESYNC_REQUIRED not in committed
