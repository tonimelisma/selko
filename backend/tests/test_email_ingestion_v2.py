"""Regression coverage for durable polling email ingestion boundaries.

Every database interaction runs against a real temporary SQLite database
(`db`/`factory` fixtures); only Gmail, Graph and the notifier are mocked.
"""

import asyncio
import base64
import json
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest

from selko.db import attachments as db_attachments
from selko.db import codec
from selko.db import email_sync as es
from selko.db import emails as db_emails
from selko.db import ops
from selko.db.runtime import use_database
from selko.services.attachments import read_attachment_file
from selko.services.email_ingestion import (
    EmailIngestionError,
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


# --- helpers ------------------------------------------------------------------


def _ts(seconds: float = 0) -> str:
    return codec.to_timestamp(codec.utc_now() + timedelta(seconds=seconds))  # type: ignore[return-value]


def _set(db, table: str, key: str, key_value: str, **fields: Any) -> None:
    values = db.schema.encode(table, fields)
    with db.write() as tx:
        tx.execute(
            f"UPDATE {table} SET {', '.join(f'{c} = ?' for c in values)} WHERE {key} = ?",
            (*values.values(), key_value),
        )


def _integration(db, factory, *, provider: str = "gmail", status: str = "active", user: str | None = None,
                 **state: Any) -> tuple[str, str]:
    """A user's integration, due for a poll, with optional sync-state fields."""
    user = user or factory.user()
    integration_id = factory.integration(user, provider=provider)
    _set(db, "email_sync_state", "integration_id", integration_id, next_poll_at=_ts(-60), **state)
    if status != "active":
        _set(db, "integrations", "id", integration_id, status=status)
    return user, integration_id


def _claim(db, mock_config) -> SyncClaim:
    claim = asyncio.run(EmailIngestionRepository(mock_config, db).claim_due_sync("worker-1"))
    assert claim is not None
    return claim


def _incidents(db) -> list[dict[str, Any]]:
    rows = db.query("SELECT * FROM operational_incidents ORDER BY rowid")
    return [db.schema.decode("operational_incidents", r) for r in rows]


def _evaluate(db, mock_config, notifier=None) -> int:
    return asyncio.run(EmailSyncHealthEvaluator(db, mock_config, notifier).evaluate_once())


def _discovered_item(db, mock_config, claim: SyncClaim, message_id: str = "msg-1") -> None:
    asyncio.run(EmailIngestionRepository(mock_config, db).upsert_discovered(
        claim, [{"provider_message_id": message_id, "provider_folder_ids": ["INBOX"], "change_kind": "upsert"}],
    ))


def _claimed_attachment(db, user: str, integration_id: str, *, provider: str, message_id: str,
                        provider_attachment_id: str, mime_type: str, filename: str,
                        worker_id: str = "attachment-worker") -> dict[str, Any]:
    """An email with one attachment descriptor, the attachment claimed by ``worker_id``."""
    db_emails.save_email_with_attachment_descriptors(
        db, user,
        {"email_provider": provider, "provider_message_id": message_id, "integration_id": integration_id,
         "subject": "With attachment"},
        [{"provider_attachment_id": provider_attachment_id, "filename": filename, "mime_type": mime_type,
          "size_bytes": 12}],
    )
    claimed = db_attachments.claim_email_attachment(db, worker_id, 900)
    assert claimed is not None and claimed["provider_attachment_id"] == provider_attachment_id
    return claimed


@pytest.fixture
def store(db):
    """The test database as the process database, so attachment files land in its directory."""
    use_database(db)
    yield db
    use_database(None)


# --- repository -----------------------------------------------------------------


# Validates: SEL-004
def test_expired_sync_claim_returns_a_run_and_takes_the_lease(db, factory, mock_config):
    _, integration_id = _integration(
        db, factory, lease_owner="dead-worker", lease_expires_at=_ts(-5), last_success_at=_ts(-600)
    )

    claim = _claim(db, mock_config)

    assert claim.integration_id == integration_id
    assert claim.provider == "gmail"
    assert claim.run_kind == "incremental"
    state = es.get_sync_state(db, integration_id)
    assert state["lease_owner"] == "worker-1"
    assert state["lease_generation"] == claim.lease_generation
    assert state["lease_expires_at"] == claim.lease_expires_at
    run = db.query_one("SELECT status, lease_generation FROM email_sync_runs WHERE id = ?", (claim.run_id,))
    assert (run["status"], run["lease_generation"]) == ("running", claim.lease_generation)


# Validates: SEL-003
def test_a_live_lease_is_not_claimed(db, factory, mock_config):
    _integration(db, factory, lease_owner="other-worker", lease_expires_at=_ts(600))
    assert asyncio.run(EmailIngestionRepository(mock_config, db).claim_due_sync("worker-1")) is None


def test_sync_claim_normalizes_uuid_ids():
    """Claims always expose string ids, whatever type a caller passes."""
    integration_id, user_id, run_id = uuid4(), uuid4(), uuid4()
    claim = SyncClaim(integration_id, user_id, "gmail", run_id, "incremental")  # type: ignore[arg-type]

    assert claim.integration_id == str(integration_id)
    assert claim.user_id == str(user_id)
    assert claim.run_id == str(run_id)


# Validates: SEL-056
def test_ingestion_error_codes_are_stable_and_details_redacted():
    exc = ProviderMessageMissingError("Authorization: Bearer secret-token")

    assert safe_error_code(exc) == "provider_message_missing"
    assert safe_error_detail(exc) == "provider operation failed"


def test_upsert_discovered_normalizes_uuid_provider_identifiers(db, factory, mock_config):
    """A page may carry UUID objects as provider ids; they are stored as text."""
    _, integration_id = _integration(db, factory)
    claim = _claim(db, mock_config)
    message_id, folder_id = uuid4(), uuid4()

    result = asyncio.run(EmailIngestionRepository(mock_config, db).upsert_discovered(
        claim,
        [{"provider_message_id": message_id, "provider_folder_ids": [folder_id], "change_kind": "upsert"}],
    ))

    assert result["inserted_count"] == 1
    row = db.schema.decode("email_ingestion_items", db.query_one(
        "SELECT provider_message_id, provider_folder_ids FROM email_ingestion_items WHERE integration_id = ?",
        (integration_id,),
    ))
    assert row == {"provider_message_id": str(message_id), "provider_folder_ids": [str(folder_id)]}


def test_claimed_item_ids_are_json_safe_strings(db, factory, mock_config):
    """The acquisition worker copies ids from the claimed item into a JSON-bound payload."""
    user, integration_id = _integration(db, factory)
    claim = _claim(db, mock_config)
    _discovered_item(db, mock_config, claim, "msg-123")

    item = asyncio.run(EmailIngestionRepository(mock_config, db).claim_item("worker-1"))

    assert item is not None
    assert item["integration_id"] == integration_id
    assert item["user_id"] == user
    assert item["acquisition_status"] == "processing"
    assert item["lease_owner"] == "worker-1"
    # Not yet acquired: no email, and None rather than "None".
    assert item["email_id"] is None
    assert isinstance(item["created_at"], str)
    json.dumps(item)


def test_claimed_attachment_is_json_safe(db, factory, mock_config):
    user, integration_id = _integration(db, factory)
    db_emails.save_email_with_attachment_descriptors(
        db, user, {"email_provider": "gmail", "provider_message_id": "m-1", "integration_id": integration_id},
        [{"provider_attachment_id": "att-123", "filename": "doc.pdf", "mime_type": "application/pdf"}],
    )

    row = asyncio.run(EmailIngestionRepository(mock_config, db).claim_attachment("worker-1"))

    assert row is not None
    assert row["user_id"] == user
    assert row["locked_by"] == "worker-1"
    assert isinstance(row["created_at"], str)
    json.dumps(row)


# Validates: SEL-078
def test_outlook_unsupported_video_attachment_is_terminal_without_provider_call(db, mock_config):
    worker = EmailIngestionWorker(db, mock_config, "attachment-worker", pg_pool=db)
    attachment = {"mime_type": "video/mp4", "filename": "clip.mp4"}

    assert asyncio.run(worker.acquire_attachment(attachment)) == "unsupported"


# Validates: SEL-095
def test_graph_transport_sends_correlation_and_immutable_request_headers():
    response = MagicMock(status_code=200, headers={"request-id": "server-request"})
    response.json.return_value = {"value": []}
    with patch("selko.services.msgraph.requests.get", return_value=response) as get:
        result = request_json(
            "token",
            "https://graph.microsoft.com/v1.0/me/messages",
            prefer='IdType="ImmutableId"',
            max_attempts=1,
            operation="GET /me/messages/{message-id}",
        )

    assert result == {"value": []}
    headers = get.call_args.kwargs["headers"]
    assert headers["Prefer"] == 'IdType="ImmutableId"'
    assert headers["return-client-request-id"] == "true"
    assert headers["client-request-id"]


# Validates: SEL-095
def test_graph_429_honors_retry_after_before_success():
    throttled = MagicMock(status_code=429, headers={"Retry-After": "7"})
    throttled.json.return_value = {"error": {"code": "TooManyRequests"}}
    success = MagicMock(status_code=200, headers={})
    success.json.return_value = {"value": [{"id": "immutable-id"}]}
    sleeps = []
    with patch("selko.services.msgraph.requests.get", side_effect=[throttled, success]):
        result = request_json(
            "token",
            "https://graph.microsoft.com/v1.0/me/messages",
            sleep=sleeps.append,
            operation="GET /me/messages/{message-id}",
        )

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


# Validates: SEL-080
def test_gmail_inline_image_is_stored_rather_than_marked_unsupported(store, factory, mock_config):
    """extract_attachments() skips CID images, so the descriptor lookup must
    also consult extract_inline_images() or every inline image dead-ends."""
    db = store
    user, integration_id = _integration(db, factory)
    attachment = _claimed_attachment(
        db, user, integration_id, provider="gmail", message_id="msg-inline",
        provider_attachment_id="inline-att-1", mime_type="image/png", filename="inline_0.png",
    )
    worker = EmailIngestionWorker(db, mock_config, "attachment-worker", pg_pool=db)

    with patch("selko.workers.email_ingestion.get_gmail_credentials", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.build_service", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.get_gmail_full_message", return_value=_gmail_message_with_inline_image()), \
         patch("selko.workers.email_ingestion.download_gmail_attachment", return_value=b"png-bytes") as download:
        status = asyncio.run(worker.acquire_attachment(attachment))

    assert status == "stored"
    assert download.call_args[0][2] == "inline-att-1"
    row = factory.row("attachments", attachment["id"])
    assert row["size_bytes"] == len(b"png-bytes")
    assert row["storage_path"].startswith(f"{user}/")
    assert read_attachment_file(row["storage_path"]) == b"png-bytes"


# Validates: SEL-081
def test_a_stale_attachment_worker_cannot_record_a_stored_file(store, factory, mock_config):
    """The row update is fenced on locked_by: a worker that lost its lease writes nothing."""
    db = store
    user, integration_id = _integration(db, factory)
    attachment = _claimed_attachment(
        db, user, integration_id, provider="gmail", message_id="msg-inline",
        provider_attachment_id="inline-att-1", mime_type="image/png", filename="inline_0.png",
        worker_id="current-owner",
    )
    stale = EmailIngestionWorker(db, mock_config, "stale-worker", pg_pool=db)

    with patch("selko.workers.email_ingestion.get_gmail_credentials", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.build_service", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.get_gmail_full_message", return_value=_gmail_message_with_inline_image()), \
         patch("selko.workers.email_ingestion.download_gmail_attachment", return_value=b"png-bytes"):
        asyncio.run(stale.acquire_attachment(attachment))

    assert factory.row("attachments", attachment["id"])["storage_path"] is None


# Validates: SEL-057
def test_acquire_item_does_not_query_integrations_per_message(db, mock_config):
    """A dead per-message integrations lookup costs a round trip and can raise
    on a missing row, dead-lettering mail for an unrelated reason."""
    worker = EmailIngestionWorker(db, mock_config, "acquisition-worker", pg_pool=db)
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


# --- the health evaluator ---------------------------------------------------------


def _healthy_state() -> dict[str, Any]:
    return {"last_success_at": _ts(), "last_started_at": _ts(), "consecutive_failures": 0}


def _dead_letter_attachment(db, factory, user: str, integration_id: str) -> None:
    email_id = factory.email(user, email_provider="gmail", integration_id=integration_id)
    with db.write() as tx:
        tx.execute(
            "INSERT INTO attachments (id, user_id, email_id, provider_attachment_id, filename, mime_type,"
            " size_bytes, ingestion_status, created_at) VALUES (?, ?, ?, 'a', 'f', 'image/png', 1,"
            " 'dead_letter', ?)",
            (codec.new_id(), user, email_id, tx.now_text),
        )


def test_dead_letter_attachment_incident_is_scoped_to_its_own_integration(db, factory, mock_config):
    """A dead letter belonging to another integration must not raise an incident here."""
    _, integration_one = _integration(db, factory, **_healthy_state())
    other_user, integration_two = _integration(db, factory, **_healthy_state())
    _dead_letter_attachment(db, factory, other_user, integration_two)

    _evaluate(db, mock_config)

    keys = {row["incident_key"] for row in _incidents(db) if row["incident_type"] == "attachment_dead_letter"}
    assert keys == {f"email-sync:{integration_two}:attachment_dead_letter"}
    assert f"email-sync:{integration_one}:attachment_dead_letter" not in keys


def test_dead_letter_scan_sees_past_a_thousand_rows(db, factory, mock_config):
    """A deployment with more dead letters than PostgREST's old row cap must still be seen.

    The cap is gone with PostgREST; this keeps the property it was guarding:
    an integration whose dead letter sorts after 1,000 others still raises.
    """
    filler_user, filler = _integration(db, factory, **_healthy_state())
    _, target = _integration(db, factory, **_healthy_state())
    with db.write() as tx:
        for index in range(1001):
            integration_id = filler if index < 1000 else target
            tx.execute(
                "INSERT INTO email_ingestion_items (id, integration_id, user_id, provider, provider_message_id,"
                " acquisition_status, created_at, updated_at, first_discovered_at, last_discovered_at)"
                " SELECT ?, integration_id, user_id, provider, ?, 'dead_letter', ?, ?, ?, ?"
                " FROM email_sync_state WHERE integration_id = ?",
                (codec.new_id(), f"m-{index}", tx.now_text, tx.now_text, tx.now_text, tx.now_text,
                 integration_id),
            )

    _evaluate(db, mock_config)

    keys = {row["incident_key"] for row in _incidents(db) if row["incident_type"] == "acquisition_dead_letter"}
    assert f"email-sync:{target}:acquisition_dead_letter" in keys
    assert f"email-sync:{filler}:acquisition_dead_letter" in keys


def test_incident_sweep_does_not_resolve_a_foreign_incident_key(db, factory, mock_config):
    """The evaluator must only resolve incidents it owns.

    `operational_incidents` is a generic table: an unscoped sweep would close
    the first non-email subsystem's incidents.
    """
    ops.open_incident(db, {"incident_key": "billing:invoice-run", "incident_type": "billing",
                           "severity": "warning", "status": "open", "safe_summary": "billing"})
    _, integration_id = _integration(db, factory, **_healthy_state())
    ops.open_incident(db, {"incident_key": f"email-sync:{integration_id}:stale_poll",
                           "integration_id": integration_id, "incident_type": "stale_poll",
                           "severity": "warning", "status": "open", "safe_summary": "stale"})

    _evaluate(db, mock_config)

    by_key = {row["incident_key"]: row for row in _incidents(db)}
    assert by_key["billing:invoice-run"]["status"] == "open"
    # The evaluator's own, no longer expected, incident is resolved.
    assert by_key[f"email-sync:{integration_id}:stale_poll"]["status"] == "resolved"


def test_reopened_incident_can_send_a_second_recovery_notification(db, factory, mock_config):
    """Leaving resolved_notification_sent_at set silences every later recovery."""
    _, integration_id = _integration(db, factory, **{**_healthy_state(), "consecutive_failures": 3})
    key = f"email-sync:{integration_id}:repeated_failures"
    ops.open_incident(db, {
        "incident_key": key, "integration_id": integration_id, "incident_type": "repeated_failures",
        "severity": "critical", "status": "resolved", "safe_summary": "old",
        "opened_notification_sent_at": "2026-08-01T00:00:00+00:00",
        "resolved_notification_sent_at": "2026-08-01T00:05:00+00:00",
    })
    notifier = MagicMock()
    notifier.send_incident_opened = AsyncMock()
    notifier.send_incident_resolved = AsyncMock()

    _evaluate(db, mock_config, notifier)

    reopened = ops.get_incident(db, key)
    assert reopened["status"] == "open"
    assert reopened["resolved_notification_sent_at"] is None
    # The re-open notified again and stamped a fresh time.
    notifier.send_incident_opened.assert_awaited_once()
    assert reopened["opened_notification_sent_at"] > "2026-08-02"

    # Recovery: the incident resolves and notifies a second time.
    _set(db, "email_sync_state", "integration_id", integration_id, consecutive_failures=0)
    _evaluate(db, mock_config, notifier)
    resolved = ops.get_incident(db, key)
    assert resolved["status"] == "resolved"
    notifier.send_incident_resolved.assert_awaited_once()
    assert resolved["resolved_notification_sent_at"] is not None


# Validates: SEL-096
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


def test_health_evaluation_records_incidents_without_a_notifier(db, factory, mock_config):
    """A missing notifier must not stop incident bookkeeping."""
    user, integration_id = _integration(db, factory, **{**_healthy_state(), "consecutive_failures": 3})

    assert _evaluate(db, mock_config, None) == 1

    [incident] = _incidents(db)
    assert incident["incident_type"] == "repeated_failures"
    assert incident["integration_id"] == integration_id
    assert incident["user_id"] == user
    assert incident["opened_notification_sent_at"] is None


def test_safe_incident_defaults_keep_user_scope_optional():
    incident = SafeIncident("email-sync:integration-1:stale_poll", "gmail", "stale_poll", "warning", "stale")

    assert incident.user_id is None
    assert incident.last_success_at is None


def test_new_integration_first_poll_in_flight_does_not_open_stale_incident(db, factory, mock_config):
    """7b: a new integration whose first poll is still running must not be stale."""
    _integration(db, factory, last_success_at=None, last_started_at=_ts(), consecutive_failures=0)

    _evaluate(db, mock_config, None)

    assert _incidents(db) == [], "first poll in-flight should not open stale_poll"


def test_new_integration_never_started_has_grace_and_no_stale_incident(db, factory, mock_config):
    """Both timestamps null — before first claim — must not be stale."""
    _integration(db, factory, last_success_at=None, last_started_at=None, consecutive_failures=0)

    _evaluate(db, mock_config, None)

    assert _incidents(db) == []


def test_stale_poll_after_grace_does_open_incident(db, factory, mock_config):
    """After warning_seconds with no success, stale_poll must open."""
    _integration(
        db, factory, last_success_at=None,
        last_started_at=_ts(-(mock_config.email_health_warning_seconds + 600)), consecutive_failures=0,
    )

    _evaluate(db, mock_config, None)

    assert [row["incident_type"] for row in _incidents(db)] == ["stale_poll"]


def test_expired_integration_does_not_raise_a_stale_poll_incident(db, factory, mock_config):
    """An expired integration is not polled, so its poll age must not degrade us.

    Production ran for 18 days with a critical `stale_poll` incident against a
    Gmail integration whose OAuth had expired: an expired integration is
    intentionally not claimable, so its poll age grows without bound.
    """
    stale = _ts(-18 * 86400)
    _integration(db, factory, status="expired", last_success_at=stale, last_started_at=stale)

    _evaluate(db, mock_config)

    assert not [row for row in _incidents(db) if row["incident_type"] == "stale_poll"]


def test_active_integration_still_raises_a_stale_poll_incident(db, factory, mock_config):
    """The scope must narrow to inactive integrations only, not silence the check."""
    stale = _ts(-18 * 86400)
    _integration(db, factory, last_success_at=stale, last_started_at=stale)

    _evaluate(db, mock_config)

    [incident] = [row for row in _incidents(db) if row["incident_type"] == "stale_poll"]
    assert incident["severity"] == "critical"


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
async def test_discover_dispatch_awaits_provider_discovery(db, mock_config, provider):
    """The public discovery dispatcher must return provider totals, not a coroutine."""
    worker = EmailIngestionWorker(db, mock_config, "worker-1", pg_pool=db)
    claim = replace(_sync_claim(), provider=provider)
    expected = {"provider_ids_seen": 2, "items_inserted": 1, "items_existing": 1}

    with patch.object(worker, f"_discover_{provider}", new=AsyncMock(return_value=expected)) as discover:
        result = await worker.discover(claim)

    assert result == expected
    discover.assert_awaited_once_with(claim)


@pytest.mark.parametrize("provider", ["gmail", "outlook"])
@pytest.mark.asyncio
async def test_reconcile_dispatch_awaits_provider_discovery(db, mock_config, provider):
    """Reconciliation must use the same awaited provider-dispatch contract."""
    worker = EmailIngestionWorker(db, mock_config, "worker-1", pg_pool=db)
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


def _outlook_with_folders(db, factory, mock_config, folder_ids: list[str]) -> tuple[SyncClaim, dict[str, str]]:
    """An Outlook integration under a live claim, with included folders; returns {provider id: row id}."""
    user, integration_id = _integration(db, factory, provider="outlook")
    rows = es.upsert_folders(db, integration_id, [
        {"user_id": user, "provider": "outlook", "provider_folder_id": pid, "name": pid, "full_path": pid,
         "folder_kind": "folder", "is_included": True, "is_scannable": True}
        for pid in folder_ids
    ])
    claim = _claim(db, mock_config)
    return claim, {row["provider_folder_id"]: row["id"] for row in rows}


def _outlook_patches(**overrides):
    defaults = {
        "get_access_token": {"return_value": "token"},
        "resolve_well_known_folder_ids": {"return_value": {}},
        "fetch_mail_folders": {"return_value": []},
        "normalize_mail_folders": {"return_value": []},
        "upsert_discovered_folders": {},
        "record_graph_failure": {},
    }
    defaults.update(overrides)
    return [patch(f"selko.workers.email_ingestion.{name}", **kwargs) for name, kwargs in defaults.items()]


def _run_with(patches, coro_factory):
    from contextlib import ExitStack

    with ExitStack() as stack:
        mocks = [stack.enter_context(p) for p in patches]
        return asyncio.run(coro_factory()), mocks


# Validates: SEL-029
def test_outlook_deleted_folder_is_removed_without_blocking_later_folders(db, factory, mock_config):
    """One folder's 404 must not abort the pass or lose other folders' cursors."""
    claim, rows = _outlook_with_folders(db, factory, mock_config, ["deleted", "current"])
    worker = EmailIngestionWorker(db, mock_config, "worker-1", pg_pool=db)
    changes = MagicMock(side_effect=[GraphHttpError(404, "folder missing"), ([], "cursor-current")])

    with patch("selko.workers.email_ingestion.fetch_message_changes", changes), \
         patch.object(worker.repository, "upsert_discovered",
                      new=AsyncMock(return_value={"provider_ids_seen": 1, "items_inserted": 1, "items_existing": 0})) as upsert:
        _run_with(_outlook_patches(), lambda: worker._discover_outlook(claim))

    assert changes.call_count == 2, "the second folder must still be polled"
    remaining = {row["provider_folder_id"] for row in es.folders_for_integration(db, claim.integration_id)}
    assert remaining == {"current"}
    assert upsert.call_args.kwargs["folder_id"] == rows["current"]
    assert upsert.call_args.kwargs["cursor"] == "cursor-current"


def _gmail_integration(db, factory, mock_config, cursor: str | None = "history-cursor",
                       run_kind: str = "incremental") -> SyncClaim:
    """A Gmail integration with a stored History cursor, under a live claim."""
    _, integration_id = _integration(db, factory)
    if cursor is not None:
        _set(db, "integrations", "id", integration_id, sync_cursor=cursor)
    return replace(_claim(db, mock_config), run_kind=run_kind)


# Validates: SEL-022
def test_gmail_history_expiry_captures_replacement_cursor_before_listing(db, factory, mock_config):
    """The replacement historyId must be read before the bounded listing.

    Reading it afterwards loses any message that arrives during the listing.
    """
    order: list[str] = []
    claim = _gmail_integration(db, factory, mock_config, cursor="expired-cursor")
    worker = EmailIngestionWorker(db, mock_config, "worker-1", pg_pool=db)

    def expired(*_args):
        order.append("history")
        raise GmailHistoryExpiredError("expired")

    def profile(*_args):
        order.append("profile")
        return {"historyId": "replacement-cursor"}

    def listing(*_args, **_kwargs):
        order.append("search")
        return []

    with patch("selko.workers.email_ingestion.get_gmail_credentials", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.build_service", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.list_labels", return_value=[]), \
         patch("selko.workers.email_ingestion.upsert_discovered_folders"), \
         patch("selko.workers.email_ingestion.fetch_history_message_ids", side_effect=expired), \
         patch("selko.workers.email_ingestion.get_user_profile", side_effect=profile), \
         patch("selko.workers.email_ingestion.list_message_ids", side_effect=listing), \
         patch.object(worker.repository, "upsert_discovered", new=AsyncMock(return_value={"provider_ids_seen": 1, "items_inserted": 1, "items_existing": 0})) as upsert:
        asyncio.run(worker._discover_gmail(claim))

    assert order == ["history", "profile", "search"]
    assert upsert.call_args.kwargs["cursor"] == "replacement-cursor"


# Validates: SEL-021
def test_gmail_history_cursor_is_committed_by_the_real_upsert(db, factory, mock_config):
    """End to end on the database: the page and its cursor land together."""
    claim = _gmail_integration(db, factory, mock_config)
    worker = EmailIngestionWorker(db, mock_config, "worker-1", pg_pool=db)

    with patch("selko.workers.email_ingestion.get_gmail_credentials", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.build_service", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.list_labels", return_value=[]), \
         patch("selko.workers.email_ingestion.upsert_discovered_folders"), \
         patch("selko.workers.email_ingestion.fetch_history_message_ids", return_value=(["m1"], "next-cursor")), \
         patch("selko.workers.email_ingestion.get_messages_metadata_batch",
               return_value={"m1": {"id": "m1", "labelIds": ["INBOX"]}}):
        asyncio.run(worker._discover_gmail(claim))

    integration = es.get_integration_by_id(db, claim.integration_id)
    assert integration["sync_cursor"] == "next-cursor"
    assert es.known_provider_message_ids(db, claim.integration_id, ["m1", "m2"]) == {"m1"}
    assert es.folders_refreshed_at(db, claim.integration_id) is not None


# Validates: SEL-024
def test_gmail_excluded_folders_come_from_the_database(db, factory, mock_config):
    """A label the user excluded removes its messages from discovery."""
    claim = _gmail_integration(db, factory, mock_config)
    es.upsert_folders(db, claim.integration_id, [
        {"user_id": claim.user_id, "provider": "gmail", "provider_folder_id": "Label_Newsletters",
         "name": "Newsletters", "full_path": "Newsletters", "folder_kind": "label",
         "is_included": False, "is_scannable": True},
    ])
    worker = EmailIngestionWorker(db, mock_config, "worker-1", pg_pool=db)
    batched = {
        "kept": {"id": "kept", "labelIds": ["INBOX"]},
        "dropped": {"id": "dropped", "labelIds": ["Label_Newsletters"]},
    }

    with patch("selko.workers.email_ingestion.get_gmail_credentials", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.build_service", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.list_labels", return_value=[]), \
         patch("selko.workers.email_ingestion.upsert_discovered_folders"), \
         patch("selko.workers.email_ingestion.fetch_history_message_ids", return_value=(list(batched), "c")), \
         patch("selko.workers.email_ingestion.get_messages_metadata_batch", return_value=batched), \
         patch.object(worker.repository, "upsert_discovered", new=AsyncMock(return_value={"provider_ids_seen": 2, "items_inserted": 2, "items_existing": 0})) as upsert:
        asyncio.run(worker._discover_gmail(claim))

    kinds = {item["provider_message_id"]: item["change_kind"] for item in upsert.call_args.args[1]}
    assert kinds == {"kept": "upsert", "dropped": "removed"}


# Validates: SEL-021
def test_gmail_incremental_poll_does_not_fetch_the_user_profile(db, factory, mock_config):
    """6c: the profile call is only needed where replacement_cursor is used.

    `get_user_profile` used to run unconditionally on every discovery pass, but
    its result is only consumed on initial sync and on History expiry.
    """
    claim = _gmail_integration(db, factory, mock_config)
    worker = EmailIngestionWorker(db, mock_config, "worker-1", pg_pool=db)

    with patch("selko.workers.email_ingestion.get_gmail_credentials", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.build_service", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.list_labels", return_value=[]), \
         patch("selko.workers.email_ingestion.upsert_discovered_folders"), \
         patch("selko.workers.email_ingestion.fetch_history_message_ids", return_value=([], "next-cursor")), \
         patch("selko.workers.email_ingestion.get_user_profile") as profile, \
         patch.object(worker.repository, "upsert_discovered", new=AsyncMock(return_value={"provider_ids_seen": 1, "items_inserted": 1, "items_existing": 0})):
        asyncio.run(worker._discover_gmail(claim))

    profile.assert_not_called()


# Validates: SEL-023, SEL-024
def test_gmail_discovery_batches_metadata_and_matches_the_serial_result(db, factory, mock_config):
    """6a: batching must not change what discovery decides, only what it costs."""
    claim = _gmail_integration(db, factory, mock_config)
    worker = EmailIngestionWorker(db, mock_config, "worker-1", pg_pool=db)

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


# Validates: SEL-025
def test_gmail_reconcile_skips_known_identities_and_resumes_next_pass(db, factory, mock_config):
    """6b: the reconcile bound must make forward progress, not re-truncate.

    Filtering out identities already in `email_ingestion_items` first is what
    makes the cap resumable: this pass commits what it processed, so the next
    pass sees a smaller undiscovered set and continues from there.
    """
    mock_config.email_reconcile_max_identities = 2
    claim = _gmail_integration(db, factory, mock_config, cursor=None, run_kind="reconcile")
    for known in ("message-0", "message-1", "message-2"):
        _discovered_item(db, mock_config, claim, known)
    worker = EmailIngestionWorker(db, mock_config, "worker-1", pg_pool=db)
    window = [f"message-{i}" for i in range(6)]

    with patch("selko.workers.email_ingestion.get_gmail_credentials", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.build_service", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.list_labels", return_value=[]), \
         patch("selko.workers.email_ingestion.upsert_discovered_folders"), \
         patch("selko.workers.email_ingestion.get_user_profile", return_value={"historyId": "h"}), \
         patch("selko.workers.email_ingestion.list_message_ids",
               return_value=[{"id": mid} for mid in window]), \
         patch("selko.workers.email_ingestion.get_messages_metadata_batch",
               return_value={}) as batch, \
         patch.object(worker.repository, "upsert_discovered", new=AsyncMock(return_value={"provider_ids_seen": 1, "items_inserted": 1, "items_existing": 0})):
        asyncio.run(worker._discover_gmail(claim, lookback_days=90))

    requested = list(batch.call_args.args[1])
    # Known identities are never re-fetched, and what remains honours the cap.
    assert requested == ["message-3", "message-4"]


# Validates: SEL-025
def test_gmail_reconcile_does_not_bound_the_incremental_path(db, factory, mock_config):
    """Only reconcile passes are bounded; an incremental delta is already O(delta)."""
    mock_config.email_reconcile_max_identities = 1
    claim = _gmail_integration(db, factory, mock_config)
    worker = EmailIngestionWorker(db, mock_config, "worker-1", pg_pool=db)

    with patch("selko.workers.email_ingestion.get_gmail_credentials", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.build_service", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.list_labels", return_value=[]), \
         patch("selko.workers.email_ingestion.upsert_discovered_folders"), \
         patch("selko.workers.email_ingestion.fetch_history_message_ids",
               return_value=(["a", "b", "c"], "next-cursor")), \
         patch.object(worker.repository, "known_provider_message_ids", wraps=worker.repository.known_provider_message_ids) as known, \
         patch("selko.workers.email_ingestion.get_messages_metadata_batch", return_value={}) as batch, \
         patch.object(worker.repository, "upsert_discovered", new=AsyncMock(return_value={"provider_ids_seen": 1, "items_inserted": 1, "items_existing": 0})):
        asyncio.run(worker._discover_gmail(claim))

    known.assert_not_called()
    assert list(batch.call_args.args[1]) == ["a", "b", "c"]


# Validates: SEL-025
def test_known_provider_message_ids_answers_in_bounded_chunks(db, factory, mock_config):
    """A full reconcile window is queried a chunk at a time, and the answer is exact."""
    from selko.services.email_ingestion import KNOWN_ID_QUERY_CHUNK

    claim = _gmail_integration(db, factory, mock_config)
    ids = [f"message-{i}" for i in range(KNOWN_ID_QUERY_CHUNK * 2 + 5)]
    known = set(ids[:: KNOWN_ID_QUERY_CHUNK // 2])
    for message_id in sorted(known):
        _discovered_item(db, mock_config, claim, message_id)

    real_query = db.query
    calls: list[int] = []

    def counting_query(sql, params=()):
        if "json_each" in sql:
            calls.append(len(json.loads(params[1])))
        return real_query(sql, params)

    with patch.object(db, "query", side_effect=counting_query):
        found = asyncio.run(
            EmailIngestionRepository(mock_config, db).known_provider_message_ids(claim.integration_id, ids)
        )

    assert found == known
    assert len(calls) == 3
    assert all(size <= KNOWN_ID_QUERY_CHUNK for size in calls)
    assert sum(calls) == len(ids)


# Validates: SEL-077
def test_attachment_failure_cannot_touch_provider_cursors(db, factory, mock_config):
    """Attachment work is a separate claim, so it can never rewind discovery.

    The legacy poller fetched attachments inline and had to be careful not to
    commit a cursor afterwards; v2 removes the hazard structurally.
    """
    user, integration_id = _integration(db, factory)
    _set(db, "integrations", "id", integration_id, sync_cursor="cursor-before")
    db_emails.save_email_with_attachment_descriptors(
        db, user, {"email_provider": "gmail", "provider_message_id": "m-1", "integration_id": integration_id},
        [{"provider_attachment_id": "att-1", "filename": "x.png", "mime_type": "image/png"}],
    )
    state_before = es.get_sync_state(db, integration_id)
    worker = EmailIngestionWorker(db, mock_config, "attachment-worker", pg_pool=db)

    async def scenario():
        with patch.object(worker, "acquire_attachment", new=AsyncMock(side_effect=RuntimeError("download failed"))):
            assert await worker.run_attachment_once() is True
            await asyncio.wait(worker._attachment_inflight, timeout=5)

    asyncio.run(scenario())

    [row] = db.query("SELECT ingestion_status, locked_by FROM attachments")
    assert (row["ingestion_status"], row["locked_by"]) == ("retry", None)
    assert es.get_integration_by_id(db, integration_id)["sync_cursor"] == "cursor-before"
    assert es.get_sync_state(db, integration_id) == state_before


# Validates: SEL-080
def test_outlook_attachment_decodes_base64_and_skips_item_attachments(store, factory, mock_config):
    """Only fileAttachment carries contentBytes; itemAttachment must not store."""
    db = store
    user, integration_id = _integration(db, factory, provider="outlook")
    db_emails.save_email_with_attachment_descriptors(
        db, user, {"email_provider": "outlook", "provider_message_id": "message-1", "integration_id": integration_id},
        [{"provider_attachment_id": "file-1", "filename": "document.txt", "mime_type": "text/plain"},
         {"provider_attachment_id": "item-1", "filename": "item", "mime_type": "text/plain"}],
    )
    first = db_attachments.claim_email_attachment(db, "attachment-worker", 900)
    second = db_attachments.claim_email_attachment(db, "attachment-worker", 900)
    by_provider = {a["provider_attachment_id"]: a for a in (first, second)}
    worker = EmailIngestionWorker(db, mock_config, "attachment-worker", pg_pool=db)
    encoded = base64.b64encode(b"outlook bytes").decode("ascii")
    listing = [
        {"@odata.type": "#microsoft.graph.itemAttachment", "id": "item-1"},
        {"@odata.type": "#microsoft.graph.fileAttachment", "id": "file-1",
         "name": "document.txt", "contentType": "text/plain", "contentBytes": encoded},
    ]

    with patch("selko.workers.email_ingestion.get_access_token", return_value="token"), \
         patch("selko.workers.email_ingestion.list_attachments", return_value=listing):
        stored = asyncio.run(worker.acquire_attachment(by_provider["file-1"]))
        unsupported = asyncio.run(worker.acquire_attachment(by_provider["item-1"]))

    assert stored == "stored"
    assert unsupported == "unsupported"
    path = factory.row("attachments", by_provider["file-1"]["id"])["storage_path"]
    assert read_attachment_file(path) == b"outlook bytes"
    assert factory.row("attachments", by_provider["item-1"]["id"])["storage_path"] is None


# Validates: SEL-010
def test_missing_credentials_are_classified_as_auth_and_expire_the_integration(db, factory, mock_config):
    """A missing credential must mark the integration expired, not look like a
    deleted message — otherwise it retries forever and never prompts reconnect."""
    exc = ProviderAuthenticationError("Gmail credentials are unavailable")
    assert safe_error_code(exc) == "provider_auth_expired"
    _, integration_id = _integration(db, factory)
    claim = _claim(db, mock_config)

    assert asyncio.run(EmailIngestionRepository(mock_config, db).fail_sync(claim, "worker-1", exc)) is True

    assert es.get_integration_by_id(db, integration_id)["status"] == "expired"
    state = es.get_sync_state(db, integration_id)
    assert state["last_error_code"] == "provider_auth_expired"
    assert state["lease_owner"] is None


# --- Error classification regression table (top-up increment 2) -------------
#
# Pre-fix: `safe_error_code` substring-matched the message, so Gmail 401
# "Invalid Credentials" and `RefreshError: invalid_grant` both classified as
# `parse_invalid` and were dead-lettered on the FIRST attempt — permanent data
# loss. Below is the structural classification table the fix enforces.

def _gmail_error(status, reason=None, message="provider error"):
    return GmailError(message, status_code=status, reason=reason)


# Validates: SEL-056
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


# Validates: SEL-056
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



def _claimed_item(db, factory, mock_config) -> dict[str, Any]:
    _integration(db, factory)
    claim = _claim(db, mock_config)
    _discovered_item(db, mock_config, claim)
    item = asyncio.run(EmailIngestionRepository(mock_config, db).claim_item("worker-1"))
    assert item is not None
    return item


def test_no_acquisition_failure_is_terminal_on_first_attempt(db, factory, mock_config):
    """A transient provider error must not dead-letter on the first attempt —
    `fail_email_ingestion_item` dead-letters only by exhausting max_attempts
    (or via an explicit ProviderPermanentError)."""
    item = _claimed_item(db, factory, mock_config)
    repository = EmailIngestionRepository(mock_config, db)

    # A plain Gmail 401 — the pre-fix data-loss input.
    assert asyncio.run(repository.fail_item(item["id"], "worker-1", _gmail_error(401, message="Invalid Credentials")))

    row = factory.row("email_ingestion_items", item["id"])
    assert row["acquisition_status"] == "retry"
    assert row["last_error_code"] == "provider_auth_expired"
    assert row["next_retry_at"] is not None


# Validates: SEL-055
def test_permanent_error_is_terminal_on_first_attempt(db, factory, mock_config):
    """The only first-attempt terminal path is a deliberate ProviderPermanentError."""
    item = _claimed_item(db, factory, mock_config)

    asyncio.run(EmailIngestionRepository(mock_config, db).fail_item(
        item["id"], "worker-1", ProviderPermanentError("unparseable")
    ))

    row = factory.row("email_ingestion_items", item["id"])
    assert row["acquisition_status"] == "dead_letter"
    assert row["last_error_code"] == "provider_permanent"


# Validates: SEL-055
def test_a_stale_worker_cannot_fail_an_item_it_no_longer_owns(db, factory, mock_config):
    item = _claimed_item(db, factory, mock_config)

    assert asyncio.run(EmailIngestionRepository(mock_config, db).fail_item(
        item["id"], "another-worker", ProviderPermanentError("unparseable")
    )) is False

    assert factory.row("email_ingestion_items", item["id"])["acquisition_status"] == "processing"


# Validates: SEL-010
def test_gmail_401_during_discovery_expires_the_integration(db, factory, mock_config):
    """Regression: Gmail 401 used to never reach the auth-failure path (so the
    ConnectionRecovery card never fired for Gmail)."""
    _, integration_id = _integration(db, factory)
    claim = _claim(db, mock_config)

    asyncio.run(EmailIngestionRepository(mock_config, db).fail_sync(
        claim, "worker-1", _gmail_error(401, message="Invalid Credentials")
    ))

    assert es.get_integration_by_id(db, integration_id)["status"] == "expired"
    run = db.query_one("SELECT status, error_code FROM email_sync_runs WHERE id = ?", (claim.run_id,))
    assert (run["status"], run["error_code"]) == ("failed", "provider_auth_expired")


def test_a_transient_discovery_failure_does_not_expire_the_integration(db, factory, mock_config):
    """Guard the guard: only auth failures expire the account."""
    _, integration_id = _integration(db, factory)
    claim = _claim(db, mock_config)

    asyncio.run(EmailIngestionRepository(mock_config, db).fail_sync(claim, "worker-1", _gmail_error(503)))

    assert es.get_integration_by_id(db, integration_id)["status"] == "active"
    assert es.get_sync_state(db, integration_id)["consecutive_failures"] == 1


def test_run_acquisition_once_does_not_mark_terminal_on_code(db, mock_config):
    """The worker must not pass a hardcoded terminal flag derived from a code
    substring; the default classifier path inside fail_item handles it."""
    worker = EmailIngestionWorker(db, mock_config, "worker-1", pg_pool=db)
    item = {"id": "item-1", "provider": "gmail", "user_id": "u",
            "provider_message_id": "m", "provider_folder_ids": ["INBOX"]}

    captured: list[tuple[str, tuple]] = []

    async def fake_fail_item(item_id, worker_id, exc, *, terminal=None):
        captured.append((exc, terminal))
        return True

    def fake_acquire(_item):
        # Simulate a Gmail 401 raised mid-acquisition (the data-loss input).
        raise _gmail_error(401, message="Invalid Credentials")

    async def scenario():
        with patch.object(worker.repository, "claim_item", new=AsyncMock(return_value=item)), \
             patch.object(worker.repository, "fail_item", new=AsyncMock(side_effect=fake_fail_item)), \
             patch.object(worker, "acquire_item", new=AsyncMock(side_effect=fake_acquire)):
            await worker.run_acquisition_once()
            await asyncio.wait(worker._acquisition_inflight, timeout=5)

    asyncio.run(scenario())

    assert captured, "fail_item should have been called"
    exc, terminal = captured[0]
    assert classify_email_error(exc).code == "provider_auth_expired"
    # The worker passes no terminal flag: the classifier inside fail_item
    # decides (retryable on code, terminal only for ProviderPermanentError).
    assert terminal is None


# Validates: SEL-030
def test_outlook_token_expiring_mid_pass_refreshes_instead_of_expiring_the_account(
    db, factory, mock_config,
):
    """A 401 partway through a multi-folder pass must not end the run.

    Graph access tokens last about an hour; a 90-day reconciliation across
    several folders can run longer. Propagating the 401 maps to
    provider_auth_expired, which marks the integration expired and halts
    ingestion until the user reconnects — even though the refresh token is fine.
    """
    claim, rows = _outlook_with_folders(db, factory, mock_config, ["f1", "f2"])
    worker = EmailIngestionWorker(db, mock_config, "worker-1", pg_pool=db)

    tokens_used: list[str] = []

    def changes(tok, *_args, **_kwargs):
        tokens_used.append(tok)
        if tok == "stale-token":
            raise GraphHttpError(401, "InvalidAuthenticationToken")
        return ([], "cursor-new")

    patches = _outlook_patches(get_access_token={"side_effect": ["stale-token", "fresh-token"]})
    with patch("selko.workers.email_ingestion.fetch_message_changes", side_effect=changes):
        _run_with(patches, lambda: worker._discover_outlook(claim))

    assert "fresh-token" in tokens_used, "expected one forced refresh"
    # Both folders still commit their cursors (through the real upsert); the run does not fail.
    cursors = {row["provider_folder_id"]: row["sync_cursor"]
               for row in es.folders_for_integration(db, claim.integration_id)}
    assert cursors == {"f1": "cursor-new", "f2": "cursor-new"}
    assert es.get_integration_by_id(db, claim.integration_id)["status"] == "active"


# Validates: SEL-028
def test_outlook_resync_sentinel_is_never_persisted_as_a_cursor(db, factory, mock_config):
    """Committing RESYNC_REQUIRED would be sent to Graph as a URL forever."""
    from selko.services.outlook import RESYNC_REQUIRED

    claim, _rows = _outlook_with_folders(db, factory, mock_config, ["f1"])
    worker = EmailIngestionWorker(db, mock_config, "worker-1", pg_pool=db)

    patches = _outlook_patches()
    with patch("selko.workers.email_ingestion.fetch_message_changes", return_value=([], RESYNC_REQUIRED)):
        with pytest.raises(GraphHttpError):
            _run_with(patches, lambda: worker._discover_outlook(claim))

    [folder] = es.folders_for_integration(db, claim.integration_id)
    assert folder["sync_cursor"] != RESYNC_REQUIRED


# Validates: SEL-031
def test_discover_heartbeats_around_long_listing(db, factory, mock_config):
    """R4: listing must heartbeat before and after long provider calls, not just before upsert."""
    claim = _gmail_integration(db, factory, mock_config, cursor="cursor-1")
    worker = EmailIngestionWorker(db, mock_config, "w-1", pg_pool=db)
    # The lease belongs to worker-1 (the claimant); heartbeat as that worker.
    worker.worker_id = "worker-1"
    with patch("selko.workers.email_ingestion.get_gmail_credentials", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.build_service", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.list_labels", return_value=[]), \
         patch("selko.workers.email_ingestion.upsert_discovered_folders"), \
         patch("selko.workers.email_ingestion.fetch_history_message_ids", return_value=(["m1"], "next")) as fh, \
         patch("selko.workers.email_ingestion.get_messages_metadata_batch", return_value={"m1": {"id": "m1", "labelIds": ["INBOX"]}}), \
         patch.object(worker.repository, "require_heartbeat", wraps=worker.repository.require_heartbeat) as hb:
        asyncio.run(worker._discover_gmail(claim))
    # At least 2 heartbeats for the history fetch (before+after) plus per-upsert
    assert hb.call_count >= 2, f"expected heartbeat around listing, got {hb.call_count}"
    assert fh.called


# Validates: SEL-031
def test_discovery_stops_when_the_lease_was_taken_over(db, factory, mock_config):
    """A worker whose lease is gone must not commit a page or a cursor."""
    from selko.services.email_ingestion import LeaseLostError

    claim = _gmail_integration(db, factory, mock_config, cursor="cursor-1")
    _set(db, "email_sync_state", "integration_id", claim.integration_id, lease_owner="someone-else")
    worker = EmailIngestionWorker(db, mock_config, "worker-1", pg_pool=db)

    with patch("selko.workers.email_ingestion.get_gmail_credentials", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.build_service", return_value=MagicMock()), \
         patch("selko.workers.email_ingestion.list_labels", return_value=[]), \
         patch("selko.workers.email_ingestion.upsert_discovered_folders"), \
         patch("selko.workers.email_ingestion.fetch_history_message_ids", return_value=(["m1"], "next")), \
         patch("selko.workers.email_ingestion.get_messages_metadata_batch", return_value={"m1": {"id": "m1", "labelIds": ["INBOX"]}}):
        with pytest.raises(LeaseLostError):
            asyncio.run(worker._discover_gmail(claim))

    assert es.get_integration_by_id(db, claim.integration_id)["sync_cursor"] == "cursor-1"
    assert es.known_provider_message_ids(db, claim.integration_id, ["m1"]) == set()


# --- C4: executor concurrency (acquire before claim) -------------------------


def _concurrency_config(mock_config, width: int):
    return replace(
        mock_config,
        email_acquisition_concurrency=width,
        email_attachment_concurrency=width,
    )


def _pending_items(db, factory, mock_config, count: int) -> None:
    """Discovered items ready to acquire (synchronous: called from async tests)."""
    _integration(db, factory)
    claim = es.claim_due_email_sync(db, "worker-1", 900)
    es.upsert_discovered_email_items(
        db, claim["integration_id"], claim["run_id"],
        [{"provider_message_id": f"m-{i}", "provider_folder_ids": ["INBOX"], "change_kind": "upsert"}
         for i in range(count)],
    )


class TestExecutorConcurrency:
    """C4: backpressure belongs at the claim, not at the work."""

    def _worker(self, db, mock_config, width: int):
        return EmailIngestionWorker(db, _concurrency_config(mock_config, width), "c4-worker", pg_pool=db)

    # Validates: SEL-051
    @pytest.mark.asyncio
    async def test_acquisition_respects_executor_width(self, db, factory, mock_config):
        """Concurrency 4 with 10 items — one claim loop, max 4 in flight, all 10 done."""
        _pending_items(db, factory, mock_config, 10)
        worker = self._worker(db, mock_config, 4)

        done = 0
        started = 0
        peak_in_flight = 0

        async def fake_acquire(item):
            nonlocal done, started, peak_in_flight
            started += 1
            peak_in_flight = max(peak_in_flight, started - done)
            await asyncio.sleep(0.01)
            done += 1
            email_id = db_emails.save_email_with_attachment_descriptors(
                db, item["user_id"], {"email_provider": "gmail", "provider_message_id": item["provider_message_id"], "subject": "s"}, [],
            )
            return email_id

        with patch.object(worker, "acquire_item", new=AsyncMock(side_effect=fake_acquire)):
            accepted = 0
            for _ in range(500):
                if accepted >= 10:
                    break
                accepted += int(await worker.run_acquisition_once())
                if accepted < 10:
                    await asyncio.sleep(0.011)
            while worker._acquisition_inflight:
                await asyncio.sleep(0.01)

        assert peak_in_flight <= 4
        assert done == 10
        statuses = {r["acquisition_status"] for r in db.query("SELECT acquisition_status FROM email_ingestion_items")}
        assert statuses == {"completed"}

    # Validates: SEL-051
    @pytest.mark.asyncio
    async def test_saturated_acquisition_executor_does_not_block_attachments(self, db, mock_config):
        """A full acquisition executor must not block attachment work."""
        worker = self._worker(db, mock_config, 1)
        await worker._acquisition_semaphore.acquire()
        try:
            with patch.object(
                worker.repository, "claim_attachment", wraps=worker.repository.claim_attachment
            ) as claim:
                assert await worker.run_attachment_once() is False
            claim.assert_awaited_once()
        finally:
            worker._acquisition_semaphore.release()

    # Validates: SEL-051
    @pytest.mark.asyncio
    async def test_claim_never_precedes_acquire(self, db, factory, mock_config):
        """C4.1: a saturated executor must not claim a row and hold a lease."""
        _pending_items(db, factory, mock_config, 10)
        worker = self._worker(db, mock_config, 1)

        released = asyncio.Event()

        async def blocking_acquire(_item):
            await released.wait()

        with patch.object(worker, "acquire_item", new=AsyncMock(side_effect=blocking_acquire)), \
             patch.object(worker.repository, "claim_item", wraps=worker.repository.claim_item) as claim:
            first = await worker.run_acquisition_once()
            assert first is True
            assert await worker.run_acquisition_once() is False
            leased = db.query("SELECT id FROM email_ingestion_items WHERE acquisition_status = 'processing'")
            released.set()
            await asyncio.wait(worker._acquisition_inflight, timeout=5)

        assert claim.await_count == 1
        assert len(leased) == 1

    @pytest.mark.asyncio
    async def test_semaphore_released_when_claim_returns_none(self, db, mock_config):
        """A no-work claim must not leak a permit."""
        worker = self._worker(db, mock_config, 2)
        assert await worker.run_acquisition_once() is False
        assert worker._acquisition_semaphore._value == 2

    @pytest.mark.asyncio
    async def test_semaphore_released_when_claim_raises(self, db, mock_config):
        """An error must not leak a permit."""
        worker = self._worker(db, mock_config, 2)
        db.close()  # the database itself fails the claim
        with pytest.raises(EmailIngestionError):
            await worker.run_acquisition_once()
        assert worker._acquisition_semaphore._value == 2


def test_every_concurrency_knob_is_read_by_a_worker():
    """Regression: after Inc2 three of these were read nowhere."""
    workers = Path(__file__).resolve().parents[1] / "selko" / "workers"
    files = list(workers.rglob("*.py"))
    assert files, f"no worker modules under {workers}"
    source = "\n".join(p.read_text() for p in files)
    for knob in (
        "email_acquisition_concurrency",
        "email_attachment_concurrency",
        "llm_extraction_concurrency",
        "worker_calendar_sync_concurrency",
    ):
        assert knob in source, f"{knob} is not read by any worker"
