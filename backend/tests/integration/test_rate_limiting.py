"""Rate limiting and quota enforcement over a real SQLite database.

Tests verify:
1. The quota tables carry their defaults and the quota functions work
2. Quotas are per user, and no client route can change them
3. Quota enforcement returns 429 when exceeded, and the LLM is not called
4. OAuth redirect validation and error sanitization on the real app

Requests carry a real Selko access token for a real account; only the quota
decision (where a test says so) and the LLM are patched.
"""

import ast
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from selko.api.app import create_app
from selko.api.deps import get_config, get_llm_gateway
from selko.config import Config
from selko.db import quotas as db_quotas
from selko.db import runtime
from selko.services import accounts
from selko.services.llm_gateway import LLMGateway
from selko.services.quotas import QuotaCheckResult, QuotaService

ROUTES_DIR = Path(__file__).resolve().parents[2] / "selko" / "api" / "routes"
JWT_SECRET = "rate-limit-test-secret-" + "x" * 24


@pytest.fixture
def api_client(db, factory):
    """The real app on the test database, signed in as a real account."""
    config = Config(
        environment="development",
        google_client_id="test-client-id",
        google_client_secret="test-client-secret",
        jwt_secret=JWT_SECRET,
    )
    runtime.use_database(db)
    app = create_app()
    app.state.db = db
    app.dependency_overrides[get_config] = lambda: config
    # The real gateway over the real quota table: the quota check lives in the
    # gateway, so a mock here would never refuse. No test reaches a provider:
    # the provider is a mock, and an exhausted quota refuses before it.
    app.dependency_overrides[get_llm_gateway] = lambda: LLMGateway(MagicMock(), MagicMock(), QuotaService(db))
    user_id = factory.user()
    token, _ = accounts.issue_access_token(
        accounts.TokenKeys(JWT_SECRET), user_id, "user@example.test", "session-1"
    )
    client = TestClient(app, raise_server_exceptions=False)
    client.headers["Authorization"] = f"Bearer {token}"
    client.user_id = user_id
    yield client
    app.dependency_overrides.clear()
    runtime.use_database(None)


class TestQuotaDatabaseIntegration:
    def test_global_limits_table_has_defaults(self, db):
        rows = {r["limit_type"]: r["default_limit"] for r in db.query("SELECT * FROM global_limits")}
        assert rows["llm_calls_daily"] > 0
        assert rows["email_syncs_daily"] > 0
        assert rows["calendar_syncs_daily"] > 0

    def test_usage_quotas_only_own_data(self, db, factory):
        """Successor of the RLS test: every quota read is by user."""
        alice, bob = factory.user(), factory.user()
        db_quotas.check_and_increment_quota(db, alice, "llm_calls", 7)
        assert db_quotas.get_user_quota_usage(db, alice)["llm_calls_count"] == 7
        assert db_quotas.get_user_quota_usage(db, bob)["llm_calls_count"] == 0

    def test_quota_check_and_increment(self, db, factory):
        user = factory.user()
        result = db_quotas.check_and_increment_quota(db, user, "llm_calls", 1)
        assert result["allowed"] is True
        assert result["current_count"] == 1
        assert result["quota_limit"] > 0
        assert result["remaining"] == result["quota_limit"] - 1

    def test_quota_get_user_usage(self, db, factory):
        usage = db_quotas.get_user_quota_usage(db, factory.user())
        for kind in ("llm_calls", "email_syncs", "calendar_syncs"):
            assert {f"{kind}_count", f"{kind}_limit", f"{kind}_remaining"} <= usage.keys()

    def test_no_client_route_mutates_quotas(self):
        """Successor of the "quota RPCs are denied to a signed-in user" test:
        no route module names the quota tables or the limit writer."""
        offenders = []
        for path in sorted(ROUTES_DIR.glob("*.py")):
            source = path.read_text()
            tree = ast.parse(source)
            names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
            names |= {n.id for n in ast.walk(tree) if isinstance(n, ast.Name)}
            literals = {n.value for n in ast.walk(tree) if isinstance(n, ast.Constant) and isinstance(n.value, str)}
            if "set_user_limit" in names or any(
                "usage_quotas" in s or "global_limits" in s for s in literals
            ):
                offenders.append(path.name)
        assert len(list(ROUTES_DIR.glob("*.py"))) > 3, "scan found no route modules"
        assert offenders == []


class TestQuotaServiceIntegration:
    def test_quota_service_check_and_increment(self, db, factory):
        result = QuotaService(db).check_and_increment(factory.user(), "llm_calls")
        assert result.allowed is True
        assert result.current_count >= 1

    def test_quota_service_get_usage(self, db, factory):
        usage = QuotaService(db).get_usage(factory.user())
        assert usage.llm_calls_limit > 0
        assert usage.email_syncs_limit > 0


class TestQuotaExceeded:
    @patch("selko.services.quotas.QuotaService.check_and_increment")
    def test_llm_quota_exceeded_returns_429(self, mock_quota_check, api_client, factory):
        mock_quota_check.return_value = QuotaCheckResult(
            allowed=False, current_count=100, limit=100, remaining=0,
        )
        email_id = factory.email(api_client.user_id)

        response = api_client.post(f"/emails/{email_id}/process")

        assert response.status_code == 429
        assert "X-RateLimit-Limit" in response.headers
        assert "X-RateLimit-Remaining" in response.headers
        body = response.json()
        assert "quota" in str(body.get("detail", "")).lower() or "quota" in str(body.get("error", "")).lower()

    @patch("selko.services.events.process_email_for_events")
    @patch("selko.services.quotas.QuotaService.check_and_increment")
    def test_llm_not_called_when_quota_exceeded(self, mock_quota_check, mock_process_email, api_client, factory):
        mock_quota_check.return_value = QuotaCheckResult(
            allowed=False, current_count=100, limit=100, remaining=0,
        )

        api_client.post(f"/emails/{factory.email(api_client.user_id)}/process")

        mock_process_email.assert_not_called()

    def test_a_real_exhausted_quota_returns_429(self, api_client, db, factory):
        """No patch: the user's own row in usage_quotas is exhausted."""
        QuotaService(db).set_user_limit(api_client.user_id, "llm_calls", 1)
        QuotaService(db).check_and_increment(api_client.user_id, "llm_calls")

        response = api_client.post(f"/emails/{factory.email(api_client.user_id)}/process")

        assert response.status_code == 429


class TestOAuthRedirectValidation:
    def test_valid_localhost_redirect(self, api_client):
        response = api_client.get(
            "/integrations/google/auth",
            params={"redirect_uri": "http://localhost:8000/integrations/google/callback"},
            follow_redirects=False,
        )
        assert response.status_code == 302, response.text
        assert response.headers["location"].startswith("https://accounts.google.com/")

    def test_invalid_redirect_host_rejected(self, api_client):
        response = api_client.get(
            "/integrations/google/auth",
            params={"redirect_uri": "https://evil.com/callback"},
            follow_redirects=False,
        )

        assert response.status_code == 400
        detail = response.json().get("detail", "")
        msg = detail["detail"] if isinstance(detail, dict) else detail
        assert "redirect" in msg.lower()

    def test_invalid_redirect_path_rejected(self, api_client):
        response = api_client.get(
            "/integrations/google/auth",
            params={"redirect_uri": "http://localhost:8000/malicious/path"},
            follow_redirects=False,
        )

        assert response.status_code == 400


class TestErrorSanitization:
    @pytest.mark.parametrize("method,path,body", [
        ("post", "/emails/sync", {"max_results": 10}),
        ("post", "/emails/nonexistent-id/process", None),
    ])
    def test_errors_do_not_leak_internals(self, api_client, method, path, body):
        response = getattr(api_client, method)(path, json=body)

        if response.status_code >= 500:
            raw_detail = response.json().get("detail", "")
            detail = raw_detail["detail"] if isinstance(raw_detail, dict) else str(raw_detail)
            assert "Traceback" not in detail
            assert "/home/" not in detail and "/Users/" not in detail
            assert "Exception" not in detail
