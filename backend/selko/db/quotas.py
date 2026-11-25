"""Daily usage quotas and LLM usage (docs/specs/sqlite-single-process/02-data-layer.md §2.9, §3.11).

Ports of ``check_and_increment_quota`` (55), ``get_user_quota_usage`` (56)
and ``get_llm_usage_summary`` (57), and the ``global_limits`` /
``usage_quotas`` table calls of ``services/quotas.py``.

The quota day is the UTC date of the transaction (Postgres ``CURRENT_DATE``
in Supabase's UTC database time zone). The advisory lock Postgres took is not
needed: writers are serialized.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any

from selko.db import errors
from selko.db.codec import new_id, to_date
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


# ---------------------------------------------------------------------------
# 57 get_llm_usage_summary (no production caller; kept for LLMLoggingService)
# ---------------------------------------------------------------------------


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
    "max_allowed",
    "set_user_limit",
]
