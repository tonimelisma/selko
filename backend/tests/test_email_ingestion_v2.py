"""Regression coverage for durable polling email ingestion boundaries."""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from selko.services.email_ingestion import (
    EmailIngestionRepository,
    ProviderMessageMissingError,
    safe_error_code,
    safe_error_detail,
)
from selko.services.msgraph import request_json
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
