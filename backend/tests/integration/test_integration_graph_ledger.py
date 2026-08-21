"""Real-Postgres proof that Graph failures reach the durable ledger."""

from unittest.mock import MagicMock, patch

import pytest

from selko.services.msgraph import GraphRequestError, request_json
from tests.integration.test_integration_email_ingestion_v2 import synced_integration


pytestmark = [pytest.mark.integration, pytest.mark.development]


def test_graph_failure_is_recorded_with_redacted_operation_and_run(
    admin_client, config, synced_integration
):
    claimed = admin_client.rpc(
        "claim_due_email_sync",
        {"p_worker_id": "graph-ledger-test", "p_lease_seconds": 900},
    ).execute().data
    claim = next(
        row for row in claimed if row["integration_id"] == synced_integration
    )

    response = MagicMock(
        status_code=503,
        headers={"request-id": "graph-request-123"},
        content=b'{"error":"unavailable"}',
    )
    response.json.return_value = {
        "error": {"code": "ServiceUnavailable", "message": "temporary outage"}
    }
    with patch("selko.services.msgraph.requests.get", return_value=response):
        with pytest.raises(GraphRequestError):
            request_json(
                "token",
                "https://graph.microsoft.com/v1.0/me/messages/opaque-message-id",
                client=admin_client,
                config=config,
                integration_id=synced_integration,
                run_id=claim["run_id"],
                operation="GET /me/messages/{message-id}",
                max_attempts=1,
            )

    row = (
        admin_client.table("graph_api_failures")
        .select(
            "environment,integration_id,graph_surface,operation,safe_url_template,"
            "http_status,graph_error_code,run_id,attempt,will_retry"
        )
        .eq("run_id", claim["run_id"])
        .single()
        .execute()
        .data
    )
    assert row == {
        "environment": "development",
        "integration_id": synced_integration,
        "graph_surface": "outlook_mail",
        "operation": "GET /me/messages/{message-id}",
        "safe_url_template": "https://graph.microsoft.com/v1.0/me/messages/{message-id}",
        "http_status": 503,
        "graph_error_code": "ServiceUnavailable",
        "run_id": claim["run_id"],
        "attempt": 1,
        "will_retry": False,
    }
