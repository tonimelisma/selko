"""Unit tests for API routes.

Tests FastAPI route handlers with mocked dependencies. No real Supabase or
external services needed — all deps are overridden via app.dependency_overrides.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from selko.api.app import create_app
from selko.api.deps import (
    CurrentUser,
    get_authenticated_client,
    get_config,
    get_current_user,
    get_llm_gateway,
    get_quota_service,
    get_service_role_client,
)
from selko.config import Config

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_config():
    """Config with test values."""
    return Config(
        environment="development",
        google_client_id="test-client-id",
        google_client_secret="test-client-secret",
        jwt_secret="test-jwt-secret-" + "x" * 32,
    )


@pytest.fixture
def mock_user():
    """Authenticated user for dependency overrides."""
    return CurrentUser(id="test-user-id", email="test@example.com", token="fake-jwt")


@pytest.fixture
def mock_client():
    """Mock Supabase client."""
    return MagicMock()


@pytest.fixture
def mock_service_client():
    """Mock service-role Supabase client."""
    return MagicMock()


@pytest.fixture
def mock_quota():
    """Mock QuotaService that always allows."""
    qs = MagicMock()
    qs.check_and_increment.return_value = MagicMock(
        allowed=True, remaining=9, limit=10, resets_at="2026-01-02T00:00:00Z"
    )
    return qs


@pytest.fixture
def mock_gateway():
    """Mock LLMGateway."""
    return MagicMock()


@pytest.fixture
def test_client(
    mock_config,
    mock_user,
    mock_client,
    mock_service_client,
    mock_quota,
    mock_gateway,
):
    """Fully-overridden TestClient — all deps mocked."""
    # The callback's per-IP limiter is process state shared by every test.
    from selko.api.routes import integrations as integration_routes

    integration_routes._callback_request_log.clear()
    app = create_app()
    app.dependency_overrides[get_config] = lambda: mock_config
    app.dependency_overrides[get_current_user] = lambda: mock_user
    app.dependency_overrides[get_authenticated_client] = lambda: mock_client
    app.dependency_overrides[get_quota_service] = lambda: mock_quota
    app.dependency_overrides[get_service_role_client] = lambda: mock_service_client
    app.dependency_overrides[get_llm_gateway] = lambda: mock_gateway
    yield TestClient(app, raise_server_exceptions=False)
    app.dependency_overrides.clear()


@pytest.fixture
def unauthed_app(mock_config, db):
    """App with only config overridden and a real database; auth is not overridden.

    The database is installed because routes also depend on it: without one,
    dependency resolution fails with a 500 before the 401 under test.
    """
    from selko.db import runtime

    runtime.use_database(db)
    app = create_app()
    app.dependency_overrides[get_config] = lambda: mock_config
    yield app
    app.dependency_overrides.clear()
    runtime.use_database(None)


# ===========================================================================
# Health endpoints
# ===========================================================================


class TestHealthEndpoints:
    """/health, /health/db and /health/ingestion over a real SQLite database.

    The work-state roll-up is computed by selko.db.health from rows the test
    writes; nothing stubs the database.
    """

    @pytest.fixture
    def health_db(self, db, test_client):
        from selko.db import runtime

        runtime.use_database(db)
        test_client.app.state.db = db
        yield db
        runtime.use_database(None)

    def test_health_ok(self, test_client, health_db):
        resp = test_client.get("/health")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["resolution"]["pending_emails"] == 0

    def test_health_publishes_build_sha(self, test_client, mock_config, health_db):
        mock_config.build_sha = "abc123"
        resp = test_client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["build_sha"] == "abc123"

    def test_health_publishes_this_process_memory(self, test_client, health_db):
        memory = test_client.get("/health").json()["memory"]
        # The suite runs on Linux: /proc is there, so these are real numbers.
        assert memory["rss_bytes"] > 10 * 1024 * 1024
        assert memory["peak_rss_bytes"] >= memory["rss_bytes"]
        assert set(memory) == {"rss_bytes", "peak_rss_bytes", "cgroup_current_bytes", "cgroup_limit_bytes",
                               "threads", "reader_connections"}
        from selko.db import connection

        assert memory["threads"] >= 1
        assert 1 <= memory["reader_connections"] <= connection.READER_POOL_SIZE  # the request itself read

    def test_memory_snapshot_reads_proc_and_cgroup_and_reports_absence_as_none(self, tmp_path):
        from selko.api.routes.health import memory_snapshot

        status_file = tmp_path / "status"
        status_file.write_text("Name:\tpython\nVmHWM:\t  240000 kB\nVmRSS:\t  131072 kB\n")
        cgroup = tmp_path / "cg"
        cgroup.mkdir()
        (cgroup / "memory.current").write_text("150000000\n")
        (cgroup / "memory.max").write_text("419430400\n")
        snapshot = memory_snapshot(str(status_file), str(cgroup))
        assert {k: snapshot[k] for k in ("rss_bytes", "peak_rss_bytes", "cgroup_current_bytes", "cgroup_limit_bytes")} == {
            "rss_bytes": 131072 * 1024,
            "peak_rss_bytes": 240000 * 1024,
            "cgroup_current_bytes": 150000000,
            "cgroup_limit_bytes": 419430400,
        }
        (cgroup / "memory.max").write_text("max\n")  # no limit set
        snapshot = memory_snapshot(str(tmp_path / "missing"), str(cgroup))
        assert {k: snapshot[k] for k in ("rss_bytes", "peak_rss_bytes", "cgroup_current_bytes", "cgroup_limit_bytes")} == {
            "rss_bytes": None, "peak_rss_bytes": None,
            "cgroup_current_bytes": 150000000, "cgroup_limit_bytes": None,
        }
        v1 = tmp_path / "v1"
        (v1 / "memory").mkdir(parents=True)
        (v1 / "memory" / "memory.usage_in_bytes").write_text("99000000\n")
        (v1 / "memory" / "memory.limit_in_bytes").write_text("419430400\n")
        assert memory_snapshot(str(status_file), str(v1))["cgroup_limit_bytes"] == 419430400
        (v1 / "memory" / "memory.limit_in_bytes").write_text("9223372036854771712\n")  # v1's "no limit"
        assert memory_snapshot(str(status_file), str(v1))["cgroup_limit_bytes"] is None

    def test_health_degraded_when_work_state_reports_degraded(self, test_client, health_db, factory):
        factory.email(factory.user(), processing_status="processing")  # no lease: stale
        resp = test_client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "degraded"

    def test_health_counts_pending_email(self, test_client, health_db, factory):
        factory.email(factory.user(), processing_status="pending")
        assert test_client.get("/health").json()["resolution"]["pending_emails"] == 1

    def test_health_degrades_when_work_state_unreachable(self, test_client):
        """No database open: degraded, never a 500."""
        from selko.db import runtime

        runtime.use_database(None)
        resp = test_client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "degraded"

    def test_health_db_connected(self, test_client, health_db):
        resp = test_client.get("/health/db")
        assert resp.status_code == 200
        assert resp.json()["database"] == "connected"

    def test_health_db_failure(self, test_client):
        """No database to answer: 503."""
        from selko.db import runtime

        runtime.use_database(None)
        resp = test_client.get("/health/db")
        assert resp.status_code == 503

    def test_health_ingestion_when_background_processing_is_off(self, test_client, health_db, factory):
        """Runtime is None: report the disabled state, never "down", and still
        report the work-state roll-up, which describes the DATABASE, not this
        process. Stale polling is the expected steady state with workers off.
        """
        user = factory.user()
        factory.integration(user, "gmail")  # due now: its sync state is created due
        with patch("selko.api.app.ingestion_runtime", None):
            resp = test_client.get("/health/ingestion")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["background_processing_enabled"] is False
        assert body["tasks"] == []
        assert body["integrations_due"] == 1
        assert body["listener"]["kind"] == "in_process"
        assert set(body["listener"]) == {"kind", "bound", "signals_sent", "last_signal_at"}

    def test_health_ingestion_degrades_on_lost_work_even_with_workers_off(
        self, test_client, health_db, factory
    ):
        """Dead-lettered or unclaimable work is a defect whatever the posture."""
        factory.email(factory.user(), processing_status="processing")  # stale lease
        with patch("selko.api.app.ingestion_runtime", None):
            body = test_client.get("/health/ingestion").json()
        assert body["status"] == "degraded"
        assert body["stale_processing_emails"] == 1

    def test_health_ingestion_does_not_degrade_on_terminal_failures(self, test_client, health_db, factory):
        """failed_emails is history, not a current degradation.

        Degrading on it meant that a single permanently failed email pinned
        /health to 'degraded' forever and made assert-health.sh unsatisfiable.
        """
        user = factory.user()
        for _ in range(3):
            factory.email(user, processing_status="failed")
        with patch("selko.api.app.ingestion_runtime", None):
            body = test_client.get("/health/ingestion").json()
        assert body["status"] == "ok", body
        assert body["failed_emails"] == 3, "the count must still be reported"

    def test_health_ingestion_reports_runtime_snapshot(self, test_client, health_db):
        """The route surfaces IngestionRuntime.health_snapshot()."""
        snapshot = {
            "status": "ok",
            "background_processing_enabled": True,
            "instance_id": "instance-1",
            "tasks": [
                {"name": "email-sync-coordinator", "alive": True, "restarts": 0,
                 "last_exception_code": None},
                {"name": "email-sync-health", "alive": False, "restarts": 2,
                 "last_exception_code": "database_transient"},
            ],
            "integrations_due": 2,
            "oldest_next_poll_seconds": 41,
            "leases_held": 1,
            "items_pending": 17,
            "items_dead_letter": 0,
            "attachments_dead_letter": 0,
            "open_incidents": 0,
        }
        runtime = MagicMock()
        runtime.health_snapshot.return_value = snapshot
        with patch("selko.api.app.ingestion_runtime", runtime):
            resp = test_client.get("/health/ingestion")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ok"
        assert body["background_processing_enabled"] is True
        assert body["instance_id"] == "instance-1"
        assert {t["name"] for t in body["tasks"]} == {
            "email-sync-coordinator", "email-sync-health"
        }
        dead = next(t for t in body["tasks"] if t["name"] == "email-sync-health")
        assert dead["alive"] is False
        assert dead["restarts"] == 2
        assert dead["last_exception_code"] == "database_transient"
        assert body["integrations_due"] == 2
        assert body["oldest_next_poll_seconds"] == 41
        assert body["items_pending"] == 17
        assert body["listener"]["kind"] == "in_process"

    def test_health_ingestion_degrades_when_snapshot_raises(self, test_client, health_db):
        """A snapshot failure must not 500 — degrade to a safe payload."""
        runtime = MagicMock()
        runtime.health_snapshot.side_effect = RuntimeError("db down")
        runtime.instance_id = "instance-1"
        with patch("selko.api.app.ingestion_runtime", runtime):
            resp = test_client.get("/health/ingestion")
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "degraded"
        assert body["background_processing_enabled"] is True

    def test_health_egress_reports_the_sqlite_transport(self, test_client, health_db, factory):
        factory.integration(factory.user(), "gmail")
        body = test_client.get("/health/egress").json()
        assert body["transport"] == "sqlite"
        assert "supabase" not in body["by_destination"]


# ===========================================================================
# Auth validation
# ===========================================================================


class TestAuthValidation:
    """Tests for authentication enforcement on protected endpoints."""

    def test_no_auth_header_returns_401(self, unauthed_app):
        """Missing Authorization header -> 401."""
        client = TestClient(unauthed_app, raise_server_exceptions=False)
        resp = client.post("/emails/sync", json={})
        assert resp.status_code == 401

    def test_malformed_bearer_returns_401(self, unauthed_app):
        """Bearer prefix missing -> 401."""
        client = TestClient(unauthed_app, raise_server_exceptions=False)
        resp = client.post(
            "/emails/sync",
            json={},
            headers={"Authorization": "Token abc123"},
        )
        assert resp.status_code == 401

    def test_invalid_token_returns_401(self, unauthed_app):
        """Valid Bearer format but fake token -> 401 from Supabase validation."""
        client = TestClient(unauthed_app, raise_server_exceptions=False)
        resp = client.post(
            "/emails/sync",
            json={},
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert resp.status_code == 401

    def test_events_sync_requires_auth(self, unauthed_app):
        """Events sync endpoint also requires auth."""
        client = TestClient(unauthed_app, raise_server_exceptions=False)
        resp = client.post("/events/00000000-0000-0000-0000-000000000001/sync")
        assert resp.status_code == 401

    def test_integrations_google_auth_requires_auth(self, unauthed_app):
        """Google OAuth initiation requires auth."""
        client = TestClient(unauthed_app, raise_server_exceptions=False)
        resp = client.get("/integrations/google/auth")
        assert resp.status_code == 401

    def test_integrations_outlook_auth_requires_auth(self, unauthed_app):
        """Outlook OAuth initiation requires auth just like Gmail."""
        client = TestClient(unauthed_app, raise_server_exceptions=False)
        resp = client.get("/integrations/outlook/auth")
        assert resp.status_code == 401

    def test_photos_routes_are_gone(self, test_client):
        """Google Photos ingestion was removed: no route answers for it."""
        assert test_client.get("/integrations/photos/auth").status_code == 404
        assert test_client.get("/photos").status_code == 404


# ===========================================================================
# CORS headers
# ===========================================================================


class TestCORSHeaders:
    """Tests for CORS middleware configuration."""

    def test_allowed_origin(self, test_client):
        resp = test_client.get(
            "/health",
            headers={"Origin": "http://localhost:5173"},
        )
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"

    def test_disallowed_origin(self, test_client):
        resp = test_client.get(
            "/health",
            headers={"Origin": "http://evil.example.com"},
        )
        assert "access-control-allow-origin" not in resp.headers

    def test_preflight(self, test_client):
        resp = test_client.options(
            "/emails/sync",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization, Content-Type",
            },
        )
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"

    def test_no_origin_no_cors_header(self, test_client):
        resp = test_client.get("/health")
        assert "access-control-allow-origin" not in resp.headers


# ===========================================================================
# Request validation (422)
# ===========================================================================


class TestRequestValidation:
    """Tests for Pydantic request validation returning 422."""

    def test_sync_invalid_max_results(self, test_client):
        resp = test_client.post("/emails/sync", json={"max_results": 0})
        assert resp.status_code == 422

    def test_batch_process_invalid_max_emails(self, test_client):
        resp = test_client.post("/emails/batch-process", json={"max_emails": 999})
        assert resp.status_code == 422


# ===========================================================================
# Not-found responses
# ===========================================================================


@pytest.fixture
def db_client(db, factory, mock_config, mock_gateway):
    """A TestClient whose user-scoped client is a real temporary database."""
    user_id = factory.user()
    app = create_app()
    app.dependency_overrides[get_config] = lambda: mock_config
    app.dependency_overrides[get_current_user] = lambda: CurrentUser(id=user_id, email="u@example.test", token="t")
    app.dependency_overrides[get_authenticated_client] = lambda: db
    app.dependency_overrides[get_service_role_client] = lambda: db
    app.dependency_overrides[get_llm_gateway] = lambda: mock_gateway
    yield TestClient(app, raise_server_exceptions=False), user_id
    app.dependency_overrides.clear()


class TestReprocessEmail:
    """S1: reprocess refuses a row with a live processing lease instead of
    silently returning no rows; everything runs on the real database."""

    def test_reprocess_resets_the_users_email_to_pending(self, db_client, factory):
        client, user_id = db_client
        email_id = factory.email(user_id, processing_status="failed", processing_error="boom",
                                 dead_letter_reason="boom", attempts=3, max_attempts=3)

        resp = client.post(f"/emails/{email_id}/reprocess")

        assert resp.status_code == 200
        assert resp.json()["processing_status"] == "pending"
        assert resp.json()["email_id"] == email_id
        row = factory.row("emails", email_id)
        assert (row["processing_status"], row["attempts"], row["dead_letter_reason"]) == ("pending", 0, None)

    def test_actively_leased_email_returns_409(self, db_client, factory):
        client, user_id = db_client
        email_id = factory.email(user_id, processing_status="processing", locked_by="worker-1",
                                 locked_until="2999-01-01T00:00:00.000000Z", attempts=1)

        resp = client.post(f"/emails/{email_id}/reprocess")

        assert resp.status_code == 409
        assert "already pending or being processed" in resp.json()["detail"]["detail"]
        assert factory.row("emails", email_id)["locked_by"] == "worker-1"

    def test_another_users_email_is_not_reprocessed(self, db_client, factory):
        client, _user_id = db_client
        other = factory.user()
        email_id = factory.email(other, processing_status="failed", attempts=3, max_attempts=3)

        resp = client.post(f"/emails/{email_id}/reprocess")

        assert resp.status_code == 409
        assert factory.row("emails", email_id)["processing_status"] == "failed"

    def test_other_database_error_returns_500(self, db_client, db):
        client, _user_id = db_client
        db.close()
        for suffix in ("", "-wal", "-shm"):
            db.path.with_name(db.path.name + suffix).unlink(missing_ok=True)

        resp = client.post("/emails/00000000-0000-4000-8000-000000000001/reprocess")

        assert resp.status_code == 500


class TestNotFoundResponses:
    """Tests for 404 when resources don't exist."""

    def test_email_not_found(self, db_client):
        """Processing a non-existent email returns 404."""
        client, _user_id = db_client
        resp = client.post("/emails/00000000-0000-4000-8000-000000000001/process")
        assert resp.status_code == 404

    def test_another_users_email_is_not_found(self, db_client, factory):
        client, _user_id = db_client
        email_id = factory.email(factory.user())
        with patch("selko.api.routes.emails.process_email_for_events") as process:
            resp = client.post(f"/emails/{email_id}/process")
        assert resp.status_code == 404
        process.assert_not_called()

    def test_process_returns_the_events_of_the_users_email(self, db_client, factory):
        client, user_id = db_client
        email_id = factory.email(user_id)
        event_id = factory.event(user_id)
        factory.event_source(event_id, email_id)
        with patch("selko.api.routes.emails.process_email_for_events",
                   return_value={"num_events": 1, "num_new": 1, "num_updated": 0}):
            resp = client.post(f"/emails/{email_id}/process")
        assert resp.status_code == 200
        assert resp.json()["event_ids"] == [event_id]

    def test_batch_process_takes_only_the_users_newest_emails(self, db_client, factory):
        client, user_id = db_client
        old = factory.email(user_id, date_sent="2026-01-01T00:00:00.000000Z")
        new = factory.email(user_id, date_sent="2026-06-01T00:00:00.000000Z")
        factory.email(factory.user(), date_sent="2026-07-01T00:00:00.000000Z")
        with patch("selko.api.routes.emails.process_email_for_events",
                   return_value={"num_events": 0, "num_new": 0, "num_updated": 0}) as process:
            resp = client.post("/emails/batch-process", json={"max_emails": 1})
        assert resp.status_code == 200
        assert [c.kwargs["email_id"] for c in process.call_args_list] == [new]
        assert old != new


class TestServiceRoleOAuthRoutes:
    """OAuth-backed service calls use service role after user-scoped checks."""




    def test_email_sync_uses_service_role_client(
        self, test_client, mock_service_client
    ):
        with patch(
            "selko.api.routes.emails.fetch_emails_for_user",
            return_value={"fetched": 1, "saved": 1, "attachments_downloaded": 0},
        ) as fetch:
            response = test_client.post("/emails/sync", json={})

        assert response.status_code == 200
        assert fetch.call_args.kwargs["client"] is mock_service_client
        assert fetch.call_args.kwargs["user_id"] == "test-user-id"

    def test_calendar_list_uses_service_role_client(
        self, test_client, mock_service_client
    ):
        with patch(
            "selko.api.routes.calendars.calendars.list_calendars",
            return_value=[],
        ) as list_calendars:
            response = test_client.get("/calendars")

        assert response.status_code == 200
        list_calendars.assert_called_once_with(mock_service_client, "test-user-id")





# ===========================================================================
# OAuth callback (public endpoint)
# ===========================================================================


class TestOAuthCallback:
    """Tests for the Google OAuth callback endpoint."""

    def test_callback_invalid_state(self, test_client):
        """Invalid state redirects to frontend with oauth=error."""
        from selko.services.integrations import OAuthStateError

        with patch(
            "selko.api.routes.integrations.complete_oauth_flow",
            side_effect=OAuthStateError("Invalid or expired state parameter"),
        ):
            resp = test_client.get(
                "/integrations/google/callback",
                params={"code": "auth-code", "state": "bad-state"},
                follow_redirects=False,
            )
        assert resp.status_code == 302
        assert "oauth=error" in resp.headers["location"]

    def test_callback_expired_state(self, test_client):
        """Expired state redirects to frontend with oauth=error."""
        from selko.services.integrations import OAuthStateError

        with patch(
            "selko.api.routes.integrations.complete_oauth_flow",
            side_effect=OAuthStateError("State parameter expired"),
        ):
            resp = test_client.get(
                "/integrations/google/callback",
                params={"code": "auth-code", "state": "expired-state"},
                follow_redirects=False,
            )
        assert resp.status_code == 302
        assert "oauth=error" in resp.headers["location"]

    def test_microsoft_callback_invalid_state_redirects(self, test_client):
        from selko.services.integrations import OAuthStateError

        with patch(
            "selko.api.routes.integrations.complete_oauth_flow",
            side_effect=OAuthStateError("Invalid or expired state parameter"),
        ):
            resp = test_client.get(
                "/integrations/microsoft/callback",
                params={"code": "auth-code", "state": "bad-state"},
                follow_redirects=False,
            )

        assert resp.status_code == 302
        assert "oauth=error" in resp.headers["location"]

    @pytest.fixture
    def callback_db(self, db):
        """The callback writes through the process database."""
        from selko.db import runtime

        runtime.use_database(db)
        yield db
        runtime.use_database(None)

    @staticmethod
    def _google_creds(granted_scopes=None):
        creds = MagicMock()
        creds.token = "google-access"
        creds.refresh_token = "google-refresh"
        creds.expiry = None
        creds.scopes = list(granted_scopes or [])
        creds.granted_scopes = granted_scopes
        return creds

    @staticmethod
    def _rows(db, user):
        return {
            r["provider"]: dict(r)
            for r in db.query("SELECT * FROM integrations WHERE user_id = ?", (user,))
        }

    def test_callback_success(self, test_client, callback_db, factory):
        """Successful callback stores the integration and redirects with oauth=success."""
        user = factory.user()
        with (
            patch(
                "selko.api.routes.integrations.complete_oauth_flow",
                return_value=(self._google_creds(), user, "gmail"),
            ),
            patch("selko.api.routes.integrations.build_service"),
            patch(
                "selko.api.routes.integrations.get_user_profile",
                return_value={"emailAddress": "user@gmail.com"},
            ),
        ):
            resp = test_client.get(
                "/integrations/google/callback",
                params={"code": "valid-code", "state": "valid-state"},
                follow_redirects=False,
            )
        assert resp.status_code == 302
        location = resp.headers["location"]
        assert "oauth=success" in location
        assert "provider=gmail" in location
        row = self._rows(callback_db, user)["gmail"]
        assert (row["status"], row["access_token"], row["provider_email"]) == (
            "active", "google-access", "user@gmail.com"
        )

    def _combined_callback(self, test_client, user, granted_scopes, timezone_value="Europe/Helsinki"):
        creds = self._google_creds(granted_scopes)
        calendar = MagicMock()
        calendar.settings.return_value.get.return_value.execute.return_value = {"value": timezone_value}
        with (
            patch(
                "selko.api.routes.integrations.complete_oauth_flow",
                return_value=(creds, user, "google"),
            ),
            patch("selko.api.routes.integrations.build_service"),
            patch(
                "selko.api.routes.integrations.get_user_profile",
                return_value={"emailAddress": "user@gmail.com"},
            ) as profile,
            patch("googleapiclient.discovery.build", return_value=calendar),
        ):
            resp = test_client.get(
                "/integrations/google/callback",
                params={"code": "valid-code", "state": "valid-state"},
                follow_redirects=False,
            )
        return resp, profile

    def test_one_consent_connects_gmail_and_calendar(self, test_client, callback_db, factory):
        """Both rows get the same token, so they can never expire apart."""
        from selko.services.integrations import CALENDAR_SCOPES, GMAIL_SCOPES

        user = factory.user()
        resp, _ = self._combined_callback(test_client, user, GMAIL_SCOPES + CALENDAR_SCOPES)

        assert resp.status_code == 302
        assert "oauth=success" in resp.headers["location"]
        rows = self._rows(callback_db, user)
        assert set(rows) == {"gmail", "google_calendar"}
        assert {r["access_token"] for r in rows.values()} == {"google-access"}
        assert {r["provider_email"] for r in rows.values()} == {"user@gmail.com"}
        settings = callback_db.query_one(
            "SELECT timezone FROM user_calendar_settings WHERE user_id = ?", (user,)
        )
        assert settings["timezone"] == "Europe/Helsinki", "calendar timezone auto-detected"

    def test_an_unticked_product_is_not_connected(self, test_client, callback_db, factory):
        """Google lets the user untick a scope; that product gets no row."""
        from selko.services.integrations import CALENDAR_SCOPES

        user = factory.user()
        resp, profile = self._combined_callback(test_client, user, CALENDAR_SCOPES)

        assert "oauth=success" in resp.headers["location"]
        assert set(self._rows(callback_db, user)) == {"google_calendar"}
        profile.assert_not_called()

    def test_a_consent_granting_nothing_connects_nothing(self, test_client, callback_db, factory):
        user = factory.user()
        resp, _ = self._combined_callback(test_client, user, ["openid"])

        assert "oauth=error" in resp.headers["location"]
        assert self._rows(callback_db, user) == {}

    def test_microsoft_callback_stores_outlook_tokens(self, test_client, callback_db, factory):
        user = factory.user()
        with (
            patch(
                "selko.api.routes.integrations.complete_oauth_flow",
                return_value=({"access_token": "ms-access", "refresh_token": "ms-refresh",
                               "expires_in": 3600, "scope": "Mail.Read"}, user, "outlook"),
            ),
            patch(
                "selko.api.routes.integrations.get_outlook_user_profile",
                return_value={"mail": "me@outlook.com"},
            ),
        ):
            resp = test_client.get(
                "/integrations/microsoft/callback",
                params={"code": "c", "state": "s"},
                follow_redirects=False,
            )
        assert "oauth=success" in resp.headers["location"]
        row = self._rows(callback_db, user)["outlook"]
        assert (row["access_token"], row["provider_email"]) == ("ms-access", "me@outlook.com")

    def test_callback_no_auth_required(self, test_client):
        """Callback endpoint is public — no JWT needed. Verify it doesn't 401."""
        from selko.services.integrations import IntegrationError

        # Even an IntegrationError proves we reached the handler (no 401 gate)
        with patch(
            "selko.api.routes.integrations.complete_oauth_flow",
            side_effect=IntegrationError("Invalid or expired state"),
        ):
            resp = test_client.get(
                "/integrations/google/callback",
                params={"code": "any-code", "state": "any-state"},
                follow_redirects=False,
            )
        assert resp.status_code != 401
        assert resp.status_code == 302


# ===========================================================================
# Redirect URI validation
# ===========================================================================


class TestEmailFolderRoutes:
    """Settings' folder list and preference, over a real SQLite database."""

    @pytest.fixture
    def folders(self, db, factory, test_client):
        from selko.db.codec import new_id

        alice, bob = factory.user(), factory.user()
        gmail = factory.integration(alice, "gmail")
        ids = {}
        for name, system in (("Work", False), ("INBOX", True), ("Archive", False)):
            ids[name] = new_id()
            factory._insert("email_folders", {
                "id": ids[name], "user_id": alice, "integration_id": gmail, "provider": "gmail",
                "provider_folder_id": f"label-{name}", "name": name, "full_path": name,
                "folder_kind": "label", "is_system": system, "is_included": False,
                "sync_cursor": "cursor-1",
            })
        test_client.app.dependency_overrides[get_authenticated_client] = lambda: db
        test_client.app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            id=alice, email="alice@example.test", token="t"
        )
        return {"alice": alice, "bob": bob, "integration": gmail, **ids}

    def test_list_shows_the_users_non_system_folders_by_path(self, test_client, folders):
        resp = test_client.get("/integrations/gmail/folders")
        assert resp.status_code == 200
        assert [f["name"] for f in resp.json()] == ["Archive", "Work"]
        assert "sync_cursor" not in resp.json()[0], "provider state stays server-side"

    def test_list_is_empty_for_another_user(self, test_client, folders):
        test_client.app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            id=folders["bob"], email=None, token="t"
        )
        assert test_client.get("/integrations/gmail/folders").json() == []

    def test_enabling_a_folder_persists_and_requests_a_poll(self, test_client, folders, db):
        with db.write() as tx:
            later = tx.ts(3600)
            tx.execute("UPDATE email_sync_state SET next_poll_at = ?", (later,))
        resp = test_client.patch(f"/integrations/gmail/folders/{folders['Work']}", json={"is_included": True})
        assert resp.status_code == 200, resp.text
        assert resp.json()["is_included"] is True and resp.json()["user_override"] is True
        row = db.query_one("SELECT is_included, sync_cursor FROM email_folders WHERE id = ?", (folders["Work"],))
        assert (row[0], row[1]) == (1, None), "enabling resets the cursor"
        due = db.query_one(
            "SELECT next_poll_at FROM email_sync_state WHERE integration_id = ?", (folders["integration"],)
        )[0]
        assert due < later, "the integration is due now, not in an hour"

    def test_system_and_foreign_folders_are_not_found(self, test_client, folders):
        assert test_client.patch(
            f"/integrations/gmail/folders/{folders['INBOX']}", json={"is_included": True}
        ).status_code == 404
        test_client.app.dependency_overrides[get_current_user] = lambda: CurrentUser(
            id=folders["bob"], email=None, token="t"
        )
        assert test_client.patch(
            f"/integrations/gmail/folders/{folders['Work']}", json={"is_included": True}
        ).status_code == 404


class TestGoogleConnectIsOneConsent:
    """Google connects through one combined consent, at one path."""

    def test_google_auth_starts_the_combined_flow(self, test_client):
        with patch(
            "selko.api.routes.integrations.initiate_oauth_flow",
            return_value={"auth_url": "https://accounts.google.com/o/oauth2"},
        ) as initiate:
            resp = test_client.get("/integrations/google/auth", follow_redirects=False)

        assert resp.status_code == 302
        assert initiate.call_args.kwargs["provider"] == "google"

    @pytest.mark.parametrize(
        "path", ["/integrations/gmail/auth", "/integrations/calendar/auth"]
    )
    def test_the_old_mobile_only_paths_are_gone(self, test_client, path):
        """They existed only for the native apps, which are unmaintained (legacy/)."""
        with patch("selko.api.routes.integrations.initiate_oauth_flow") as initiate:
            resp = test_client.get(path, follow_redirects=False)

        assert resp.status_code == 404
        initiate.assert_not_called()


class TestRedirectURIValidation:
    """Tests for OAuth redirect URI allowlist."""

    def test_valid_redirect_uri(self, test_client):
        """Valid redirect URI initiates OAuth (mock the flow)."""
        with patch(
            "selko.api.routes.integrations.initiate_oauth_flow",
            return_value={"auth_url": "https://accounts.google.com/o/oauth2"},
        ):
            resp = test_client.get(
                "/integrations/google/auth",
                params={
                    "redirect_uri": "http://localhost:8000/integrations/google/callback"
                },
                follow_redirects=False,
            )
        assert resp.status_code == 302

    def test_invalid_redirect_uri_returns_400(self, test_client):
        """Disallowed redirect URI returns 400."""
        resp = test_client.get(
            "/integrations/google/auth",
            params={"redirect_uri": "http://evil.example.com/callback"},
            follow_redirects=False,
        )
        assert resp.status_code == 400

    def test_json_accept_returns_auth_url(self, test_client):
        """Accept: application/json returns auth_url instead of redirecting."""
        with patch(
            "selko.api.routes.integrations.initiate_oauth_flow",
            return_value={"auth_url": "https://accounts.google.com/o/oauth2"},
        ):
            resp = test_client.get(
                "/integrations/google/auth",
                headers={"Accept": "application/json"},
                follow_redirects=False,
            )
        assert resp.status_code == 200
        assert resp.json()["auth_url"] == "https://accounts.google.com/o/oauth2"

    def test_default_redirect_uses_configured_api_host(
        self, test_client, mock_config
    ):
        """A dotenv-loaded API URL must authorize its own default callback."""
        mock_config.api_public_url = "https://custom-api.example.com"
        with patch(
            "selko.api.routes.integrations.initiate_oauth_flow",
            return_value={"auth_url": "https://accounts.google.com/o/oauth2"},
        ) as initiate:
            resp = test_client.get(
                "/integrations/google/auth",
                headers={"Accept": "application/json"},
                follow_redirects=False,
            )

        assert resp.status_code == 200
        assert initiate.call_args.kwargs["redirect_uri"] == (
            "https://custom-api.example.com/integrations/google/callback"
        )

    def test_production_redirect_host_allowed(self, test_client):
        """Custom production API host is an allowed OAuth callback."""
        with patch(
            "selko.api.routes.integrations.initiate_oauth_flow",
            return_value={"auth_url": "https://accounts.google.com/o/oauth2"},
        ):
            resp = test_client.get(
                "/integrations/google/auth",
                params={
                    "redirect_uri": (
                        "https://api.selkoapp.com/integrations/google/callback"
                    )
                },
                follow_redirects=False,
            )
        assert resp.status_code == 302
