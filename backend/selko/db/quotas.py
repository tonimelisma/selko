"""Daily usage quotas and LLM usage (docs/specs/sqlite-single-process/02-data-layer.md §2.9, §3.11).

Ports of ``check_and_increment_quota`` (55), ``get_user_quota_usage`` (56)
and ``get_llm_usage_summary`` (57), and the ``global_limits`` /
``usage_quotas`` table calls of ``services/quotas.py``.

The quota day is the UTC date of the transaction (Postgres ``CURRENT_DATE``
in Supabase's UTC database time zone). The advisory lock Postgres took is not
needed: writers are serialized.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from selko.db import errors
from selko.db.codec import new_id, to_date, to_timestamp, utc_now
from selko.db.connection import Database

# quota type -> (count column, limit column). A fixed whitelist: the column
# names are interpolated into SQL (Postgres: EXECUTE format('%I')).
QUOTA_COLUMNS: dict[str, tuple[str, str]] = {
    "llm_calls": ("llm_calls_count", "llm_calls_limit"),
    "email_syncs": ("email_syncs_count", "email_syncs_limit"),
    "calendar_syncs": ("calendar_syncs_count", "calendar_syncs_limit"),
}


def _quota_columns(quota_type: str) -> tuple[str, str]:
    try:
        return QUOTA_COLUMNS[quota_type]
    except KeyError:
        raise errors.InvalidArgument(f"Invalid quota type: {quota_type}") from None


def _today(now: datetime) -> str:
    return now.astimezone(timezone.utc).date().isoformat()


# ---------------------------------------------------------------------------
# 55 check_and_increment_quota
# ---------------------------------------------------------------------------


def check_and_increment_quota(
    db: Database, user_id: str, quota_type: str, increment: int = 1
) -> dict[str, Any]:
    """Increment today's count when it stays within the limit.

    Returns ``{allowed, current_count, quota_limit, remaining}``. A refused
    increment changes nothing. Today's row is created from ``global_limits``
    defaults on first use; as in Postgres, a missing ``global_limits`` row
    makes that insert fail (NOT NULL), so the quota tables must be seeded.
    """
    count_col, limit_col = _quota_columns(quota_type)
    with db.write() as tx:
        today = _today(tx.now)
        tx.execute(
            """
            INSERT INTO usage_quotas (
                id, user_id, date, llm_calls_limit, email_syncs_limit, calendar_syncs_limit,
                created_at, updated_at
            ) VALUES (
                ?, ?, ?,
                (SELECT COALESCE(default_limit, 100) FROM global_limits WHERE limit_type = 'llm_calls_daily'),
                (SELECT COALESCE(default_limit, 50) FROM global_limits WHERE limit_type = 'email_syncs_daily'),
                (SELECT COALESCE(default_limit, 100) FROM global_limits WHERE limit_type = 'calendar_syncs_daily'),
                ?, ?
            )
            ON CONFLICT (user_id, date) DO NOTHING
            """,
            (new_id(), user_id, today, tx.now_text, tx.now_text),
        )
        row = tx.execute(
            f"SELECT {count_col} AS current, {limit_col} AS quota_limit FROM usage_quotas "
            "WHERE user_id = ? AND date = ?",
            (user_id, today),
        ).fetchone()
        current, limit = row["current"], row["quota_limit"]
        if current + increment > limit:
            return {
                "allowed": False,
                "current_count": current,
                "quota_limit": limit,
                "remaining": max(0, limit - current),
            }
        new_count = current + increment
        tx.execute(
            f"UPDATE usage_quotas SET {count_col} = ?, updated_at = ? WHERE user_id = ? AND date = ?",
            (new_count, tx.now_text, user_id, today),
        )
        return {
            "allowed": True,
            "current_count": new_count,
            "quota_limit": limit,
            "remaining": max(0, limit - new_count),
        }


# ---------------------------------------------------------------------------
# 56 get_user_quota_usage (no production caller; kept for QuotaService.get_usage)
# ---------------------------------------------------------------------------


def get_user_quota_usage(db: Database, user_id: str, for_date: date | str | None = None) -> dict[str, int]:
    """Counts, limits and remaining for all three quotas on ``for_date`` (default: today, UTC)."""
    day = to_date(for_date) if for_date is not None else _today(utc_now())
    row = db.query_one(
        """
        SELECT
            COALESCE(q.llm_calls_count, 0) AS llm_calls_count,
            COALESCE(q.llm_calls_limit, gl_llm.default_limit, 100) AS llm_calls_limit,
            COALESCE(q.email_syncs_count, 0) AS email_syncs_count,
            COALESCE(q.email_syncs_limit, gl_email.default_limit, 50) AS email_syncs_limit,
            COALESCE(q.calendar_syncs_count, 0) AS calendar_syncs_count,
            COALESCE(q.calendar_syncs_limit, gl_cal.default_limit, 100) AS calendar_syncs_limit
        FROM (SELECT 1) AS dummy
        LEFT JOIN usage_quotas q ON q.user_id = ? AND q.date = ?
        LEFT JOIN global_limits gl_llm ON gl_llm.limit_type = 'llm_calls_daily'
        LEFT JOIN global_limits gl_email ON gl_email.limit_type = 'email_syncs_daily'
        LEFT JOIN global_limits gl_cal ON gl_cal.limit_type = 'calendar_syncs_daily'
        """,
        (user_id, day),
    )
    out: dict[str, int] = {}
    for kind in ("llm_calls", "email_syncs", "calendar_syncs"):
        count, limit = row[f"{kind}_count"], row[f"{kind}_limit"]
        out[f"{kind}_count"] = count
        out[f"{kind}_limit"] = limit
        out[f"{kind}_remaining"] = max(0, limit - count)
    return out


# ---------------------------------------------------------------------------
# 57 get_llm_usage_summary (no production caller; kept for LLMLoggingService)
# ---------------------------------------------------------------------------


def _pg_round_int(value: Decimal) -> int:
    return int(value.quantize(Decimal(1), rounding=ROUND_HALF_UP))


def llm_usage_summary(
    db: Database,
    user_id: str,
    start_date: date | str | None = None,
    end_date: date | str | None = None,
) -> dict[str, Any]:
    """Totals of the user's LLM calls started in ``[start_date, end_date + 1 day)`` (UTC dates)."""
    today = utc_now().date()
    start = date.fromisoformat(to_date(start_date)) if start_date is not None else today  # type: ignore[arg-type]
    end = date.fromisoformat(to_date(end_date)) if end_date is not None else today  # type: ignore[arg-type]
    lower = to_timestamp(datetime(start.year, start.month, start.day, tzinfo=timezone.utc))
    upper_day = end + timedelta(days=1)
    upper = to_timestamp(datetime(upper_day.year, upper_day.month, upper_day.day, tzinfo=timezone.utc))
    rows = db.query(
        """
        SELECT success, total_tokens, prompt_tokens, completion_tokens, latency_ms,
               estimated_cost_usd, operation_type
        FROM llm_call_log
        WHERE user_id = ? AND started_at >= ? AND started_at < ?
        """,
        (user_id, lower, upper),
    )
    latencies = [r["latency_ms"] for r in rows if r["latency_ms"] is not None]
    by_operation: dict[str, int] = {}
    for r in rows:
        by_operation[r["operation_type"]] = by_operation.get(r["operation_type"], 0) + 1
    cost = sum((Decimal(str(r["estimated_cost_usd"])) for r in rows if r["estimated_cost_usd"] is not None), Decimal(0))
    return {
        "total_calls": len(rows),
        "successful_calls": sum(1 for r in rows if r["success"] == 1),
        "failed_calls": sum(1 for r in rows if r["success"] == 0),
        "total_tokens": sum(r["total_tokens"] or 0 for r in rows),
        "total_prompt_tokens": sum(r["prompt_tokens"] or 0 for r in rows),
        "total_completion_tokens": sum(r["completion_tokens"] or 0 for r in rows),
        "total_latency_ms": sum(latencies),
        "avg_latency_ms": _pg_round_int(Decimal(sum(latencies)) / len(latencies)) if latencies else 0,
        "estimated_cost_usd": float(cost.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)),
        "calls_by_operation": by_operation,
    }


# ---------------------------------------------------------------------------
# services/quotas.py table calls (QuotaService.set_user_limit)
# ---------------------------------------------------------------------------


def max_allowed(db: Database, limit_type: str) -> int | None:
    """``global_limits.max_allowed`` for ``limit_type`` (e.g. ``llm_calls_daily``), or None."""
    row = db.query_one("SELECT max_allowed FROM global_limits WHERE limit_type = ?", (limit_type,))
    return row["max_allowed"] if row else None


def set_user_limit(
    db: Database,
    user_id: str,
    quota_type: str,
    new_limit: int,
    for_date: date | str | None = None,
) -> None:
    """Upsert the user's limit for one quota on ``for_date`` (default: today, UTC).

    Only that limit column changes on an existing row (PostgREST upsert of the
    given columns); a new row takes the table defaults for everything else.
    """
    _, limit_col = _quota_columns(quota_type)
    with db.write() as tx:
        day = to_date(for_date) if for_date is not None else _today(tx.now)
        tx.execute(
            f"""
            INSERT INTO usage_quotas (id, user_id, date, {limit_col}, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT (user_id, date) DO UPDATE SET {limit_col} = excluded.{limit_col}
            """,
            (new_id(), user_id, day, new_limit, tx.now_text, tx.now_text),
        )


__all__ = [
    "QUOTA_COLUMNS",
    "check_and_increment_quota",
    "get_user_quota_usage",
    "llm_usage_summary",
    "max_allowed",
    "set_user_limit",
]
