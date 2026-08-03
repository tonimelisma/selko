"""Integration tests for the integration reauthorization recovery schema/RPCs.

Covers docs/specs/oauth-reconnect-catch-up.md section 2 regression coverage:
atomic credential+recovery insert, supersession of concurrent/repeated
callbacks, FOR UPDATE SKIP LOCKED claiming, expired-lock recovery, and RLS
(users read their own recovery rows, cannot write them).
"""

import pytest
from postgrest.exceptions import APIError
from uuid import uuid4

from selko.services.integrations import (
    claim_integration_recovery,
    complete_integration_reauthorization,
    unlock_expired_integration_recoveries,
)


@pytest.fixture(autouse=True)
def _cleanup_recovery_state(admin_client, test_user_id):
    """Leave both integrations and integration_recoveries clean for the test user."""
    def _clear():
        admin_client.table("integration_recoveries").delete().eq(
            "user_id", test_user_id
        ).execute()
        admin_client.table("integrations").delete().eq(
            "user_id", test_user_id
        ).eq("provider", "google_calendar").execute()

    _clear()
    yield
    _clear()


@pytest.mark.integration
@pytest.mark.development
class TestCompleteIntegrationReauthorization:
    def test_upserts_credentials_and_creates_calendar_recovery(
        self, admin_client, test_user_id
    ):
        complete_integration_reauthorization(
            admin_client,
            user_id=test_user_id,
            provider="google_calendar",
            access_token="access-1",
            refresh_token="refresh-1",
            token_expiry=None,
            scopes=["calendar"],
            provider_email=None,
        )

        integration = (
            admin_client.table("integrations")
            .select("*")
            .eq("user_id", test_user_id)
            .eq("provider", "google_calendar")
            .single()
            .execute()
        )
        assert integration.data["status"] == "active"
        assert integration.data["access_token"] == "access-1"

        recoveries = (
            admin_client.table("integration_recoveries")
            .select("*")
            .eq("user_id", test_user_id)
            .execute()
        )
        assert len(recoveries.data) == 1
        assert recoveries.data[0]["status"] == "pending"
        assert recoveries.data[0]["reason"] == "reauthorization"

    def test_preserves_existing_refresh_token_when_omitted(
        self, admin_client, test_user_id
    ):
        complete_integration_reauthorization(
            admin_client,
            user_id=test_user_id,
            provider="google_calendar",
            access_token="access-1",
            refresh_token="refresh-1",
            token_expiry=None,
            scopes=["calendar"],
            provider_email=None,
        )
        # Google omits refresh_token on a subsequent consent screen.
        complete_integration_reauthorization(
            admin_client,
            user_id=test_user_id,
            provider="google_calendar",
            access_token="access-2",
            refresh_token=None,
            token_expiry=None,
            scopes=["calendar"],
            provider_email=None,
        )

        integration = (
            admin_client.table("integrations")
            .select("*")
            .eq("user_id", test_user_id)
            .eq("provider", "google_calendar")
            .single()
            .execute()
        )
        assert integration.data["access_token"] == "access-2"
        assert integration.data["refresh_token"] == "refresh-1"

    def test_repeated_reauthorization_supersedes_previous_recovery(
        self, admin_client, test_user_id
    ):
        complete_integration_reauthorization(
            admin_client,
            user_id=test_user_id,
            provider="google_calendar",
            access_token="access-1",
            refresh_token="refresh-1",
            token_expiry=None,
            scopes=["calendar"],
            provider_email=None,
        )
        complete_integration_reauthorization(
            admin_client,
            user_id=test_user_id,
            provider="google_calendar",
            access_token="access-2",
            refresh_token=None,
            token_expiry=None,
            scopes=["calendar"],
            provider_email=None,
        )

        recoveries = (
            admin_client.table("integration_recoveries")
            .select("status")
            .eq("user_id", test_user_id)
            .execute()
        )
        statuses = sorted(row["status"] for row in recoveries.data)
        assert statuses == ["pending", "superseded"]

    def test_gmail_reauthorization_creates_no_recovery(
        self, admin_client, test_user_id
    ):
        complete_integration_reauthorization(
            admin_client,
            user_id=test_user_id,
            provider="gmail",
            access_token="access-1",
            refresh_token="refresh-1",
            token_expiry=None,
            scopes=["gmail.readonly"],
            provider_email=None,
        )

        recoveries = (
            admin_client.table("integration_recoveries")
            .select("*")
            .eq("user_id", test_user_id)
            .execute()
        )
        assert recoveries.data == []

        admin_client.table("integrations").delete().eq(
            "user_id", test_user_id
        ).eq("provider", "gmail").execute()


@pytest.mark.integration
@pytest.mark.development
class TestClaimIntegrationRecovery:
    def test_claim_locks_row_and_increments_attempts(
        self, admin_client, test_user_id
    ):
        complete_integration_reauthorization(
            admin_client,
            user_id=test_user_id,
            provider="google_calendar",
            access_token="access-1",
            refresh_token="refresh-1",
            token_expiry=None,
            scopes=["calendar"],
            provider_email=None,
        )

        claimed = claim_integration_recovery(admin_client, "worker-1", lock_seconds=300)

        assert claimed is not None
        assert claimed["status"] == "processing"
        assert claimed["locked_by"] == "worker-1"
        assert claimed["attempts"] == 1

        # Already claimed: a second worker must not also get it.
        assert claim_integration_recovery(admin_client, "worker-2") is None

    def test_unlock_expired_returns_locked_rows_to_pending(
        self, admin_client, test_user_id
    ):
        complete_integration_reauthorization(
            admin_client,
            user_id=test_user_id,
            provider="google_calendar",
            access_token="access-1",
            refresh_token="refresh-1",
            token_expiry=None,
            scopes=["calendar"],
            provider_email=None,
        )
        claim_integration_recovery(admin_client, "worker-1", lock_seconds=300)

        # Force the lock into the past to simulate a crashed worker.
        admin_client.table("integration_recoveries").update(
            {"locked_until": "2000-01-01T00:00:00Z"}
        ).eq("user_id", test_user_id).execute()

        unlocked = unlock_expired_integration_recoveries(admin_client)
        assert unlocked >= 1

        row = (
            admin_client.table("integration_recoveries")
            .select("status, locked_by, locked_until")
            .eq("user_id", test_user_id)
            .single()
            .execute()
        )
        assert row.data["status"] == "pending"
        assert row.data["locked_by"] is None
        assert row.data["locked_until"] is None


@pytest.mark.integration
@pytest.mark.development
class TestIntegrationRecoveriesRLS:
    def test_user_can_read_own_recovery_but_not_write_it(
        self, admin_client, authenticated_client, test_user_id
    ):
        complete_integration_reauthorization(
            admin_client,
            user_id=test_user_id,
            provider="google_calendar",
            access_token="access-1",
            refresh_token="refresh-1",
            token_expiry=None,
            scopes=["calendar"],
            provider_email=None,
        )

        visible = (
            authenticated_client.table("integration_recoveries")
            .select("*")
            .eq("user_id", test_user_id)
            .execute()
        )
        assert len(visible.data) == 1

        # The table grants only SELECT to authenticated (20260802000006): the
        # RLS policy added in #237 governs reads, and writes are refused at the
        # privilege layer so a user can never mutate their own recovery row.
        with pytest.raises(APIError):
            (
                authenticated_client.table("integration_recoveries")
                .update({"status": "completed"})
                .eq("user_id", test_user_id)
                .execute()
            )
        with pytest.raises(APIError):
            authenticated_client.table("integration_recoveries").insert(
                {
                    "integration_id": str(uuid4()),
                    "user_id": test_user_id,
                    "provider": "google_calendar",
                    "reason": "reauthorization",
                }
            ).execute()

        row = (
            admin_client.table("integration_recoveries")
            .select("status")
            .eq("user_id", test_user_id)
            .single()
            .execute()
        )
        assert row.data["status"] == "pending"
