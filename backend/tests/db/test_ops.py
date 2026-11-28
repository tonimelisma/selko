"""selko.db.ops against a real SQLite database.

Ports integration/test_llm_logging.py (the database half),
integration/test_integration_graph_ledger.py's ledger row, and the incident
writes of services/email_sync_health.py.
"""

from __future__ import annotations

import pytest

from selko.db import errors, ops
from selko.db.codec import new_id


def _llm_row(**extra):
    row = {"operation_type": "extract_events", "model": "gemini-3-flash-preview",
           "prompt_text": "Test prompt for event extraction",
           "response_text": '{"events_found": true, "events": []}',
           "prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150,
           "started_at": "2026-11-25T10:00:00.123456+00:00",
           "completed_at": "2026-11-25T10:00:01.623456+00:00",
           "latency_ms": 1500, "success": True, "error_message": None, "error_type": None,
           "estimated_cost_usd": 0.000045}
    row.update(extra)
    return row


class TestLlmCallLog:
    # Validates: SEL-674
    def test_log_successful_call(self, db, factory):
        user = factory.user()
        log_id = ops.log_llm_call(db, user, _llm_row())
        log = ops.get_llm_call(db, user, log_id)
        assert log["user_id"] == user
        assert log["operation_type"] == "extract_events"
        assert log["model"] == "gemini-3-flash-preview"
        assert log["prompt_text"] == "Test prompt for event extraction"
        assert log["response_text"] == '{"events_found": true, "events": []}'
        assert log["latency_ms"] == 1500
        assert log["prompt_tokens"] == 100 and log["completion_tokens"] == 50
        assert log["total_tokens"] == 150
        assert log["success"] is True
        assert log["error_message"] is None
        assert log["estimated_cost_usd"] == pytest.approx(0.000045)
        assert log["started_at"] == "2026-11-25T10:00:00.123456Z"
        assert log["completed_at"] == "2026-11-25T10:00:01.623456Z"

    def test_log_failed_call(self, db, factory):
        user = factory.user()
        log_id = ops.log_llm_call(db, user, _llm_row(
            operation_type="compare_events", response_text=None, success=False,
            error_message="Rate limit exceeded", error_type="rate_limit"))
        log = ops.get_llm_call(db, user, log_id)
        assert log["success"] is False
        assert log["error_message"] == "Rate limit exceeded"
        assert log["error_type"] == "rate_limit"
        assert log["response_text"] is None

    def test_log_call_with_email_id_and_provider(self, db, factory):
        user = factory.user()
        email = factory.email(user)
        log_id = ops.log_llm_call(db, user, _llm_row(email_id=email, provider="anthropic"))
        log = ops.get_llm_call(db, user, log_id)
        assert log["email_id"] == email and log["provider"] == "anthropic"

    @pytest.mark.parametrize("op", ["extract_events", "compare_events", "merge_events",
                                    "propose_event_update", "classify_email_folder"])
    def test_every_operation_type_can_be_logged(self, db, factory, op):
        user = factory.user()
        assert ops.log_llm_call(db, user, _llm_row(operation_type=op))

    # Validates: SEL-674
    def test_started_at_defaults_to_now(self, db, factory):
        user = factory.user()
        row = _llm_row()
        del row["started_at"]
        log = ops.get_llm_call(db, user, ops.log_llm_call(db, user, row))
        assert log["started_at"] == log["created_at"]

    # Validates: SEL-674
    def test_unknown_user_is_refused(self, db):
        with pytest.raises(errors.ForeignKeyViolation):
            ops.log_llm_call(db, "00000000-0000-0000-0000-000000000000", _llm_row())

    # Validates: SEL-621
    def test_unknown_column_is_refused(self, db, factory):
        with pytest.raises(errors.InvalidArgument):
            ops.log_llm_call(db, factory.user(), _llm_row(id="x"))

    # Validates: SEL-674
    def test_another_users_log_is_not_visible(self, db, factory):
        owner, other = factory.user(), factory.user()
        log_id = ops.log_llm_call(db, owner, _llm_row())
        assert ops.get_llm_call(db, other, log_id) is None


class TestGraphLedger:
    # Validates: SEL-096, SEL-675
    def test_failure_is_recorded_with_redacted_operation_and_run(self, db, factory):
        user = factory.user()
        integration = factory.integration(user, provider="outlook")
        run = factory._insert("email_sync_runs", {"id": new_id(), "integration_id": integration,
                                                  "user_id": user, "provider": "outlook",
                                                  "run_kind": "incremental", "status": "running"})
        ops.record_graph_failure(db, {
            "environment": "development", "integration_id": integration,
            "graph_surface": "outlook_mail", "operation": "GET /me/messages/{message-id}",
            "http_method": "GET",
            "safe_url_template": "https://graph.microsoft.com/v1.0/me/messages/{message-id}",
            "http_status": 503, "graph_error_code": "ServiceUnavailable",
            "request_id": "graph-request-123", "client_request_id": None,
            "retry_after_seconds": None, "failure_class": "server",
            "response_summary": "temporary outage", "run_id": run, "attempt": 1, "will_retry": False,
        })
        rows = ops.graph_failures_for_run(db, run)
        assert len(rows) == 1
        row = {k: rows[0][k] for k in ("environment", "integration_id", "graph_surface", "operation",
                                        "safe_url_template", "http_status", "graph_error_code",
                                        "run_id", "attempt", "will_retry")}
        assert row == {
            "environment": "development", "integration_id": integration,
            "graph_surface": "outlook_mail", "operation": "GET /me/messages/{message-id}",
            "safe_url_template": "https://graph.microsoft.com/v1.0/me/messages/{message-id}",
            "http_status": 503, "graph_error_code": "ServiceUnavailable",
            "run_id": run, "attempt": 1, "will_retry": False,
        }
        assert rows[0]["occurred_at"].endswith("Z") and rows[0]["resolved_at"] is None

    def test_minimal_row_takes_defaults(self, db):
        failure_id = ops.record_graph_failure(db, {
            "environment": "unknown", "graph_surface": "outlook_calendar", "operation": "POST /events",
            "http_method": "POST", "safe_url_template": "https://graph/x", "failure_class": "transport"})
        row = db.schema.decode("graph_api_failures",
                               db.query_one("SELECT * FROM graph_api_failures WHERE id = ?", (failure_id,)))
        assert row["attempt"] == 1 and row["will_retry"] is False

    # Validates: SEL-675
    def test_invalid_surface_is_refused(self, db):
        with pytest.raises(errors.CheckViolation):
            ops.record_graph_failure(db, {
                "environment": "e", "graph_surface": "teams", "operation": "o", "http_method": "GET",
                "safe_url_template": "u", "failure_class": "transport"})


class TestIncidents:
    def _raise(self, db, integration, user, severity="warning", summary="stale"):
        return ops.raise_incident(
            db, incident_key=f"email-sync:{integration}:stale_poll", integration_id=integration,
            user_id=user, incident_type="stale_poll", severity=severity, safe_summary=summary)

    # Validates: SEL-676
    def test_raise_creates_then_refreshes_an_open_incident(self, db, factory):
        user = factory.user()
        integration = factory.integration(user)
        created, previous = self._raise(db, integration, user)
        assert previous is None
        assert created["status"] == "open" and created["resolved_at"] is None
        assert created["first_seen_at"] == created["last_seen_at"]
        key = created["incident_key"]

        ops.update_incident(db, key, {"opened_notification_sent_at": "2026-11-25T10:00:00+00:00"})
        refreshed, previous = self._raise(db, integration, user, severity="critical", summary="worse")
        assert previous == "open"
        assert refreshed["id"] == created["id"]
        assert refreshed["severity"] == "critical" and refreshed["safe_summary"] == "worse"
        assert refreshed["last_seen_at"] > created["last_seen_at"]
        assert refreshed["first_seen_at"] == created["first_seen_at"]
        # Still open: the opened notification is not sent again.
        assert refreshed["opened_notification_sent_at"] == "2026-11-25T10:00:00.000000Z"

    # Validates: SEL-676
    def test_a_resolved_incident_reopens_with_cleared_notifications(self, db, factory):
        user = factory.user()
        integration = factory.integration(user)
        created, _ = self._raise(db, integration, user)
        ops.update_incident_by_id(db, created["id"], {
            "status": "resolved", "resolved_at": "2026-11-25T11:00:00+00:00",
            "opened_notification_sent_at": "2026-11-25T10:00:00+00:00",
            "resolved_notification_sent_at": "2026-11-25T11:00:00+00:00"})
        reopened, previous = self._raise(db, integration, user)
        assert previous == "resolved"
        assert reopened["status"] == "open" and reopened["resolved_at"] is None
        assert reopened["opened_notification_sent_at"] is None
        assert reopened["resolved_notification_sent_at"] is None

    # Validates: SEL-621
    def test_open_incident_get_and_duplicate(self, db, factory):
        user = factory.user()
        integration = factory.integration(user)
        row = {"incident_key": f"email-sync:{integration}:x", "integration_id": integration,
               "user_id": user, "incident_type": "acquisition_dead_letter", "severity": "warning",
               "status": "open", "safe_summary": "repair"}
        created = ops.open_incident(db, row)
        assert ops.get_incident(db, row["incident_key"]) == created
        assert ops.get_incident(db, "missing") is None
        with pytest.raises(errors.UniqueViolation):
            ops.open_incident(db, row)

    def test_open_incidents_are_scoped_by_case_sensitive_prefix(self, db, factory):
        user = factory.user()
        integration = factory.integration(user)
        mine, _ = self._raise(db, integration, user)
        for key, status in (("calendar:x", "open"), ("EMAIL-SYNC:x", "open"), ("email-sync:old", "resolved")):
            ops.open_incident(db, {"incident_key": key, "incident_type": "t", "severity": "warning",
                                   "status": status, "safe_summary": "s"})
        assert [r["id"] for r in ops.open_incidents(db, "email-sync:")] == [mine["id"]]

    def test_update_returns_rowcount_and_refuses_unknown_columns(self, db, factory):
        user = factory.user()
        integration = factory.integration(user)
        created, _ = self._raise(db, integration, user)
        assert ops.update_incident(db, "missing", {"status": "resolved"}) == 0
        assert ops.update_incident_by_id(db, created["id"], {"status": "resolved"}) == 1
        with pytest.raises(errors.InvalidArgument):
            ops.update_incident_by_id(db, created["id"], {"incident_key": "other"})
        with pytest.raises(errors.InvalidArgument):
            ops.update_incident(db, created["incident_key"], {})
        with pytest.raises(errors.CheckViolation):
            ops.update_incident(db, created["incident_key"], {"status": "closed"})
