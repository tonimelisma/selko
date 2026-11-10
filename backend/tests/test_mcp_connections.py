"""Connection verdicts for Claude: one entry per sign-in, a fix for each problem."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from selko.api.mcp.connections import assess_connections, attention_summary

NOW = datetime(2026, 11, 10, 12, 0, tzinfo=timezone.utc)
APP = "https://app.example.test"
CALENDAR_SCOPES = ["offline_access", "Mail.Read", "Calendars.ReadWrite"]


def _row(provider, status="active", email="me@example.test", scopes=None, id_=None):
    return {
        "id": id_ or f"{provider}-id",
        "provider": provider,
        "status": status,
        "provider_email": email,
        "scopes": scopes or [],
    }


def _health(integration_id, *, failures=0, code=None, last_success=NOW - timedelta(minutes=5)):
    return {
        "integration_id": integration_id,
        "consecutive_failures": failures,
        "last_error_code": code,
        "last_success_at": last_success.isoformat() if last_success else None,
        # The scan lookback point, weeks back: must never read as "connected then".
        "initial_watermark_at": (NOW - timedelta(days=30)).isoformat(),
        "last_started_at": None,
        "next_poll_at": (NOW + timedelta(minutes=5)).isoformat(),
    }


def _assess(integrations, health=(), blocked=(), recoveries=()):
    return assess_connections(
        integrations, health, blocked, recoveries, frontend_url=APP, now=NOW
    )


def test_healthy_google_is_all_good_and_reports_last_check():
    result = _assess(
        [_row("gmail"), _row("google_calendar")], [_health("gmail-id")]
    )
    assert result["all_good"] is True
    assert result["needs_attention"] == []
    [google] = result["connections"]
    assert google["sign_in"] == "google"
    assert google["state"] == "connected"
    assert google["mail"]["last_checked"] == (NOW - timedelta(minutes=5)).isoformat()
    assert google["calendar"]["writable"] is True
    assert attention_summary(result) is None


def test_expired_google_names_what_stopped_and_links_the_fix():
    result = _assess([_row("gmail", "expired"), _row("google_calendar", "expired")])
    assert result["all_good"] is False
    [problem] = result["needs_attention"]
    assert problem["action"] == "reconnect"
    assert problem["sign_in"] == "google"
    assert "Gmail and Google Calendar" in problem["problem"]
    assert problem["reconnect_url"] == f"{APP}/app/settings?reconnect=google"
    # A lapsed sign-in is the answer; "connect a mailbox" beside it is not.
    assert not any(p["action"] == "connect" for p in result["needs_attention"])
    assert result["connections"][0]["state"] == "needs_reconnect"


def test_lapsed_google_calendar_is_quiet_while_outlook_calendar_works():
    result = _assess([
        _row("gmail"),
        _row("google_calendar", "expired"),
        _row("outlook", scopes=CALENDAR_SCOPES),
    ])
    assert result["needs_attention"] == []


def test_outlook_mail_only_grant_cannot_reach_a_calendar():
    result = _assess([_row("outlook", scopes=["offline_access", "Mail.Read"])])
    [problem] = result["needs_attention"]
    assert problem["sign_in"] == "outlook"
    assert "mail only" in problem["problem"]
    outlook = result["connections"][0]
    assert outlook["calendar"] == {"connected": False, "writable": False}


def test_google_consent_without_calendar_asks_to_allow_calendar():
    result = _assess([_row("gmail")])
    [problem] = result["needs_attention"]
    assert problem["sign_in"] == "google"
    assert "Calendar access was not granted" in problem["problem"]
    assert result["connections"][0]["state"] == "partial"


def test_nothing_connected_offers_both_sign_ins():
    result = _assess([])
    [problem] = result["needs_attention"]
    assert problem["action"] == "connect"
    assert problem["connect_urls"] == {
        "google": f"{APP}/app/settings?reconnect=google",
        "outlook": f"{APP}/app/settings?reconnect=outlook",
    }


def test_active_mailbox_whose_polls_keep_failing_on_auth_needs_a_sign_in():
    result = _assess(
        [_row("gmail"), _row("google_calendar")],
        [_health("gmail-id", failures=4, code="provider_auth_expired")],
    )
    [problem] = result["needs_attention"]
    assert problem["action"] == "reconnect"
    assert "refusing" in problem["problem"]


def test_transient_poll_failures_are_reported_but_not_pushed_on_every_call():
    result = _assess(
        [_row("gmail"), _row("google_calendar")],
        [_health("gmail-id", failures=3, code="executor_timeout")],
    )
    [problem] = result["needs_attention"]
    assert problem["action"] == "wait"
    assert "executor_timeout" in problem["problem"]
    assert "reconnect_url" not in problem
    assert result["all_good"] is False
    # It fixes itself, so other tools do not repeat it.
    assert attention_summary(result) is None


def test_a_mailbox_not_checked_for_hours_is_flagged_and_clears_on_success():
    stale = _assess(
        [_row("gmail"), _row("google_calendar")],
        [_health("gmail-id", last_success=NOW - timedelta(hours=7))],
    )
    assert [p["action"] for p in stale["needs_attention"]] == ["wait"]
    fresh = _assess([_row("gmail"), _row("google_calendar")], [_health("gmail-id")])
    assert fresh["all_good"] is True


def test_a_freshly_connected_mailbox_is_not_stale():
    fresh = _health("gmail-id", last_success=None)
    assert _assess([_row("gmail"), _row("google_calendar")], [fresh])["all_good"] is True


def test_a_never_checked_mailbox_whose_poll_is_hours_overdue_is_flagged():
    stuck = {**_health("gmail-id", last_success=None),
             "next_poll_at": (NOW - timedelta(hours=7)).isoformat()}
    result = _assess([_row("gmail"), _row("google_calendar")], [stuck])
    [problem] = result["needs_attention"]
    assert "since it was connected" in problem["problem"]


def test_events_parked_on_a_sign_in_are_counted_per_calendar():
    result = _assess(
        [_row("gmail"), _row("google_calendar"), _row("outlook", scopes=CALENDAR_SCOPES)],
        blocked=[
            {"provider": "google_calendar", "failure_code": "oauth_scope_required"},
            {"provider": None, "failure_code": "oauth_required"},
            {"provider": "outlook", "failure_code": "oauth_required"},
        ],
    )
    by_sign_in = {c["sign_in"]: c["events_waiting_on_sign_in"] for c in result["connections"]}
    assert by_sign_in == {"google": 2, "outlook": 1}
    messages = [p["problem"] for p in result["needs_attention"]]
    assert any("2 accepted event(s) are waiting to reach Google Calendar" in m for m in messages)
    assert any("1 accepted event(s) are waiting to reach Outlook Calendar" in m for m in messages)
    summary = attention_summary(result)
    assert summary is not None and len(summary["items"]) == 2


def test_catch_up_progress_after_a_reconnect_is_reported():
    result = _assess(
        [_row("gmail"), _row("google_calendar")],
        recoveries=[{"provider": "google_calendar", "status": "processing",
                     "remaining_count": 3, "completed_count": 2}],
    )
    assert result["catching_up"] == [
        {"provider": "google_calendar", "status": "processing", "remaining": 3, "done": 2}
    ]


def test_photos_rows_are_ignored():
    result = _assess([_row("google_photos", "expired")])
    assert result["connections"] == []
    assert [p["action"] for p in result["needs_attention"]] == ["connect"]
