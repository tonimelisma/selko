"""Real-Postgres proof that Graph failures reach the durable ledger."""

from unittest.mock import MagicMock, patch

import pytest

from selko.services.msgraph import GraphRequestError, request_json
from tests.integration.test_integration_email_ingestion_v2 import synced_integration


pytestmark = [pytest.mark.integration, pytest.mark.development]


def test_graph_failure_is_recorded_with_redacted_operation_and_run(
    admin_client, config, synced_integration, request
):
    # claim_due_email_sync claims ONE due integration across the whole
    # database, not this test's. `next(...)` without a default therefore raised
    # StopIteration whenever another test's integration was due first -- which
    # depends on the random ordering seed, so this passed in isolation and
    # failed in the suite.
    #
    # Backdate this integration's cursor so it sorts first, and RESTORE it
    # afterwards. email_sync_state is shared: leaving it permanently due made
    # every later test's claim pick it up instead of their own, which turned
    # one failure into eleven across the suite.
    original = (
        admin_client.table("email_sync_state")
        .select("next_poll_at,lease_owner,lease_expires_at")
        .eq("integration_id", synced_integration)
        .single().execute().data
    )
    admin_client.table("email_sync_state").update(
        {"next_poll_at": "1990-01-01T00:00:00+00:00"}
    ).eq("integration_id", synced_integration).execute()

    # claim_due_email_sync is `ORDER BY s.next_poll_at ... LIMIT 1`, so the
    # backdated cursor above makes this integration the one it takes -- a
    # single claim, deterministically ours.
    #
    # A bounded retry loop was tried first and was worse: claiming up to 25
    # integrations held 900-second leases on all of them and starved six other
    # tests in the same run. Ordering the queue beats racing it.
    claimed = admin_client.rpc(
        "claim_due_email_sync",
        {"p_worker_id": "graph-ledger-test", "p_lease_seconds": 900},
    ).execute().data or []
    claim = next(
        (row for row in claimed if row["integration_id"] == synced_integration),
        None,
    )
    assert claim is not None, (
        f"expected to claim {synced_integration}, got "
        f"{[r['integration_id'] for r in claimed]}"
    )

    def _restore_sync_state():
        admin_client.table("email_sync_state").update({
            "next_poll_at": original["next_poll_at"],
            "lease_owner": original["lease_owner"],
            "lease_expires_at": original["lease_expires_at"],
        }).eq("integration_id", synced_integration).execute()
        admin_client.table("email_sync_runs").update(
            {"status": "abandoned", "completed_at": "now()"}
        ).eq("id", claim["run_id"]).eq("status", "running").execute()

    request.addfinalizer(_restore_sync_state)

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
