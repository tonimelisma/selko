"""selko.db.quotas against a real SQLite database.

Ports integration/test_rate_limiting.py::test_quota_rpc_check_and_increment
and ::test_quota_rpc_get_user_usage, integration/test_llm_logging.py's usage
summary, and the edge cases of check_and_increment_quota.
"""

from __future__ import annotations

from datetime import timedelta

import pytest

from selko.db import errors, ops, quotas
from selko.db.codec import new_id, to_timestamp, utc_now

LIMITS = {"llm_calls_daily": (100, 1000), "email_syncs_daily": (50, 500), "calendar_syncs_daily": (100, 1000)}


@pytest.fixture
def seeded(db):
    """A fresh database carries the three limits Postgres seeded (20260127000003)."""
    rows = db.query("SELECT limit_type, default_limit, max_allowed, is_active FROM global_limits")
    assert {r[0]: (r[1], r[2]) for r in rows} == LIMITS
    assert all(r[3] == 1 for r in rows)


def _drop_limits(db):
    with db.write() as tx:
        tx.execute("DELETE FROM global_limits")


def _today():
    return utc_now().date().isoformat()


def test_quota_check_and_increment(db, factory, seeded):
    user = factory.user()
    row = quotas.check_and_increment_quota(db, user, "llm_calls", 1)
    assert row == {"allowed": True, "current_count": 1, "quota_limit": 100, "remaining": 99}
    row = quotas.check_and_increment_quota(db, user, "llm_calls", 4)
    assert row == {"allowed": True, "current_count": 5, "quota_limit": 100, "remaining": 95}
    stored = db.query_one("SELECT * FROM usage_quotas WHERE user_id = ?", (user,))
    assert stored["date"] == _today()
    assert stored["llm_calls_count"] == 5
    assert stored["email_syncs_limit"] == 50


def test_quota_refuses_past_the_limit_without_incrementing(db, factory, seeded):
    user = factory.user()
    assert quotas.check_and_increment_quota(db, user, "email_syncs", 50)["allowed"] is True
    refused = quotas.check_and_increment_quota(db, user, "email_syncs", 1)
    assert refused == {"allowed": False, "current_count": 50, "quota_limit": 50, "remaining": 0}
    assert db.query_one("SELECT email_syncs_count FROM usage_quotas WHERE user_id = ?", (user,))[0] == 50


def test_quota_types_are_independent_and_per_user(db, factory, seeded):
    user, other = factory.user(), factory.user()
    quotas.check_and_increment_quota(db, user, "calendar_syncs", 3)
    assert quotas.check_and_increment_quota(db, user, "llm_calls")["current_count"] == 1
    assert quotas.check_and_increment_quota(db, other, "calendar_syncs")["current_count"] == 1


def test_invalid_quota_type(db, factory, seeded):
    with pytest.raises(errors.InvalidArgument, match="Invalid quota type: photos"):
        quotas.check_and_increment_quota(db, factory.user(), "photos")


def test_missing_global_limits_fail_like_postgres(db, factory):
    """Postgres inserts NULL limits into NOT NULL columns and raises; so does the port."""
    _drop_limits(db)
    with pytest.raises(errors.NotNullViolation):
        quotas.check_and_increment_quota(db, factory.user(), "llm_calls")


def test_a_custom_limit_is_used(db, factory, seeded):
    user = factory.user()
    quotas.set_user_limit(db, user, "llm_calls", 2)
    assert quotas.check_and_increment_quota(db, user, "llm_calls", 2)["allowed"] is True
    assert quotas.check_and_increment_quota(db, user, "llm_calls")["allowed"] is False


def test_set_user_limit_changes_only_that_column(db, factory, seeded):
    user = factory.user()
    quotas.check_and_increment_quota(db, user, "llm_calls", 7)
    quotas.set_user_limit(db, user, "email_syncs", 400)
    row = db.query_one("SELECT * FROM usage_quotas WHERE user_id = ?", (user,))
    assert row["email_syncs_limit"] == 400
    assert row["llm_calls_count"] == 7
    with pytest.raises(errors.InvalidArgument):
        quotas.set_user_limit(db, user, "nope", 1)


def test_max_allowed(db, seeded):
    assert quotas.max_allowed(db, "llm_calls_daily") == 1000
    assert quotas.max_allowed(db, "nope_daily") is None


def test_get_user_quota_usage(db, factory, seeded):
    user = factory.user()
    empty = quotas.get_user_quota_usage(db, user)
    assert empty == {"llm_calls_count": 0, "llm_calls_limit": 100, "llm_calls_remaining": 100,
                     "email_syncs_count": 0, "email_syncs_limit": 50, "email_syncs_remaining": 50,
                     "calendar_syncs_count": 0, "calendar_syncs_limit": 100, "calendar_syncs_remaining": 100}
    quotas.check_and_increment_quota(db, user, "llm_calls", 30)
    used = quotas.get_user_quota_usage(db, user, _today())
    assert used["llm_calls_count"] == 30 and used["llm_calls_remaining"] == 70
    assert quotas.get_user_quota_usage(db, user, "2000-01-01")["llm_calls_count"] == 0


def test_get_user_quota_usage_without_global_limits_uses_fallbacks(db, factory):
    _drop_limits(db)
    usage = quotas.get_user_quota_usage(db, factory.user())
    assert usage["email_syncs_limit"] == 50 and usage["llm_calls_limit"] == 100


def _log(db, user, op="extract_events", success=True, latency=1000, prompt=100, completion=50,
         started=None, cost=0.0001):
    row = {"operation_type": op, "model": "m", "prompt_text": "p", "success": success,
           "latency_ms": latency, "prompt_tokens": prompt, "completion_tokens": completion,
           "total_tokens": (prompt + completion) if prompt is not None and completion is not None else None,
           "estimated_cost_usd": cost}
    if started is not None:
        row["started_at"] = started
    return ops.log_llm_call(db, user, row)


def test_llm_usage_summary(db, factory):
    user, other = factory.user(), factory.user()
    for i in range(3):
        _log(db, user, latency=1000 + i * 100)
    _log(db, user, op="compare_events", success=False, latency=201, prompt=None, completion=None, cost=None)
    _log(db, other)
    _log(db, user, started=to_timestamp(utc_now() - timedelta(days=3)))

    summary = quotas.llm_usage_summary(db, user)
    assert summary["total_calls"] == 4
    assert summary["successful_calls"] == 3
    assert summary["failed_calls"] == 1
    assert summary["total_tokens"] == 450
    assert summary["total_prompt_tokens"] == 300
    assert summary["total_completion_tokens"] == 150
    assert summary["total_latency_ms"] == 3501
    assert summary["avg_latency_ms"] == 875  # 875.25
    assert summary["estimated_cost_usd"] == pytest.approx(0.0003)
    assert summary["calls_by_operation"] == {"extract_events": 3, "compare_events": 1}

    start = (utc_now() - timedelta(days=3)).date()
    assert quotas.llm_usage_summary(db, user, start, utc_now().date())["total_calls"] == 5


def test_llm_usage_summary_empty(db, factory):
    assert quotas.llm_usage_summary(db, factory.user()) == {
        "total_calls": 0, "successful_calls": 0, "failed_calls": 0, "total_tokens": 0,
        "total_prompt_tokens": 0, "total_completion_tokens": 0, "total_latency_ms": 0,
        "avg_latency_ms": 0, "estimated_cost_usd": 0.0, "calls_by_operation": {}}
