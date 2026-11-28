"""Reconnect recovery over a real SQLite database.

Covers docs/specs/oauth-reconnect-catch-up.md section 2 regression coverage:
atomic credential+recovery insert, supersession of repeated callbacks,
single-claim leasing, expired-lock recovery, and ownership (a user reads only
their own recovery rows; no client route writes them).
"""


from selko.db import recovery as db_recovery
from selko.services.integrations import (
    claim_integration_recovery,
    complete_integration_reauthorization,
    get_provider_integration,
    unlock_expired_integration_recoveries,
)


def _reauthorize(db, user_id, provider="google_calendar", access="access-1", refresh="refresh-1", scopes=None):
    return complete_integration_reauthorization(
        db,
        user_id=user_id,
        provider=provider,
        access_token=access,
        refresh_token=refresh,
        token_expiry=None,
        scopes=scopes if scopes is not None else ["calendar"],
        provider_email=None,
    )


def _recoveries(db, user_id):
    return [dict(r) for r in db.query(
        "SELECT * FROM integration_recoveries WHERE user_id = ? ORDER BY requested_at", (user_id,)
    )]


class TestCompleteIntegrationReauthorization:
    def test_upserts_credentials_and_creates_calendar_recovery(self, db, factory):
        user_id = factory.user()
        _reauthorize(db, user_id)

        integration = get_provider_integration(db, "google_calendar", user_id=user_id)
        assert integration["status"] == "active"
        assert integration["access_token"] == "access-1"

        recoveries = _recoveries(db, user_id)
        assert len(recoveries) == 1
        assert recoveries[0]["status"] == "pending"
        assert recoveries[0]["reason"] == "reauthorization"
        assert recoveries[0]["integration_id"] == integration["id"]

    def test_preserves_existing_refresh_token_when_omitted(self, db, factory):
        user_id = factory.user()
        _reauthorize(db, user_id)
        # Google omits refresh_token on a subsequent consent screen.
        _reauthorize(db, user_id, access="access-2", refresh=None)

        integration = get_provider_integration(db, "google_calendar", user_id=user_id)
        assert integration["access_token"] == "access-2"
        assert integration["refresh_token"] == "refresh-1"

    def test_repeated_reauthorization_supersedes_previous_recovery(self, db, factory):
        user_id = factory.user()
        _reauthorize(db, user_id)
        _reauthorize(db, user_id, access="access-2", refresh=None)

        assert sorted(r["status"] for r in _recoveries(db, user_id)) == ["pending", "superseded"]

    def test_gmail_reauthorization_creates_no_recovery(self, db, factory):
        user_id = factory.user()
        _reauthorize(db, user_id, provider="gmail", scopes=["gmail.readonly"])

        assert _recoveries(db, user_id) == []


class TestClaimIntegrationRecovery:
    async def test_claim_locks_row_and_increments_attempts(self, db, factory):
        _reauthorize(db, factory.user())

        claimed = await claim_integration_recovery(db, "worker-1", lock_seconds=300)

        assert claimed is not None
        assert claimed["status"] == "processing"
        assert claimed["locked_by"] == "worker-1"
        assert claimed["attempts"] == 1

        # Already claimed: a second worker must not also get it.
        assert await claim_integration_recovery(db, "worker-2") is None

    async def test_unlock_expired_returns_locked_rows_to_pending(self, db, factory):
        user_id = factory.user()
        _reauthorize(db, user_id)
        await claim_integration_recovery(db, "worker-1", lock_seconds=300)

        # Force the lock into the past to simulate a crashed worker.
        with db.write() as tx:
            tx.execute(
                "UPDATE integration_recoveries SET locked_until = '2000-01-01T00:00:00.000000Z' WHERE user_id = ?",
                (user_id,),
            )

        assert await unlock_expired_integration_recoveries(db) == 1

        row = _recoveries(db, user_id)[0]
        assert row["status"] == "pending"
        assert row["locked_by"] is None
        assert row["locked_until"] is None

    async def test_an_expired_lease_is_reclaimed_by_the_next_claim(self, db, factory):
        user_id = factory.user()
        _reauthorize(db, user_id)
        await claim_integration_recovery(db, "worker-1", lock_seconds=300)
        with db.write() as tx:
            tx.execute("UPDATE integration_recoveries SET locked_until = ?", (tx.ts(-1),))

        reclaimed = await claim_integration_recovery(db, "worker-2")
        assert reclaimed["locked_by"] == "worker-2"
        assert reclaimed["attempts"] == 2

    async def test_superseded_recovery_cannot_be_requeued_by_old_worker(self, db, factory):
        user_id = factory.user()
        _reauthorize(db, user_id)
        claimed = await claim_integration_recovery(db, "worker-1", lock_seconds=300)
        assert claimed is not None

        # Reauthorization supersedes the locked generation and creates the
        # only active replacement. The old worker must not revive its row.
        _reauthorize(db, user_id, access="access-2", refresh=None)
        result = db_recovery.requeue_calendar_recovery_batch(
            db, claimed["id"], "worker-1", batch_size=10, max_batches=1
        )

        assert result == -1
        assert sorted(r["status"] for r in _recoveries(db, user_id)) == ["pending", "superseded"]


class TestIntegrationRecoveriesOwnership:
    # Validates: SEL-385
    def test_user_reads_own_recovery_only(self, db, factory):
        """Successor of the RLS test: the card's read is scoped by user_id."""
        alice, bob = factory.user(), factory.user()
        _reauthorize(db, alice)

        assert db_recovery.latest_recovery(db, alice)["status"] == "pending"
        assert db_recovery.latest_recovery(db, bob) is None

    # Validates: SEL-385
    def test_no_client_route_writes_recoveries(self):
        """Recovery rows are written only by the reauthorization and the worker."""
        from selko.api.app import create_app

        app = create_app()
        writers = [
            route.path for route in app.routes
            if getattr(route, "methods", None) and route.methods & {"POST", "PUT", "PATCH", "DELETE"}
            and "recover" in route.path
        ]
        assert writers == []
