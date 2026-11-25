"""Work-state health: the port of ``health_work_state`` and the health reads.

``health_work_state`` is the single counted health query behind ``/health``,
``/health/ingestion`` and ``IngestionRuntime.health_snapshot``
(docs/specs/sqlite-single-process/02-data-layer.md §2.8, function 54). All the
counts come from one SELECT, so they share one read snapshot.

Two counters must stay separate (CLAUDE.md, "Health signals must be able to
return to green"): ``unclaimable_pending`` (a pending row the claim will never
pick up: actionable, degrades the roll-up) and ``failed_emails`` (terminal
history: permanent, never degrades it).
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from selko.db.codec import parse_timestamp, to_timestamp, utc_now
from selko.db.connection import Database
# The pending-email claim predicate, shared with claim_unprocessed_email.
from selko.db.emails import CLAIMABLE_EMAIL_PREDICATE

# claim_email_ingestion_item's predicate, over alias ``i``: the queue
# items_stalled_seconds measures must be the queue the executor drains.
CLAIMABLE_INGESTION_ITEM_PREDICATE = """
    i.acquisition_status IN ('pending', 'retry', 'processing')
    AND i.attempts < i.max_attempts
    AND (i.next_retry_at IS NULL OR i.next_retry_at <= :now)
    AND (i.lease_expires_at IS NULL OR i.lease_expires_at <= :now)
"""

HEALTH_KEYS = (
    "status", "ready_emails", "processing_emails", "stale_processing_emails",
    "unclaimable_pending", "failed_emails", "stale_sync_runs", "items_pending",
    "items_dead_letter", "attachments_dead_letter", "items_stalled_seconds",
    "integrations_due", "leases_held", "oldest_next_poll_seconds", "open_incidents",
)

EMAIL_SYNC_INCIDENT_PREFIX = "email-sync:"

_HEALTH_SQL = f"""
SELECT
    (SELECT count(*) FROM emails e WHERE {CLAIMABLE_EMAIL_PREDICATE}) AS ready_emails,
    (SELECT count(*) FROM emails WHERE processing_status = 'processing') AS processing_emails,
    (SELECT count(*) FROM emails WHERE processing_status = 'processing'
        AND (locked_until IS NULL OR locked_until < :now)) AS stale_processing_emails,
    (SELECT count(*) FROM emails WHERE processing_status = 'pending'
        AND attempts >= max_attempts) AS unclaimable_pending,
    (SELECT count(*) FROM emails WHERE processing_status = 'failed') AS failed_emails,
    (SELECT count(*) FROM email_sync_runs r
        JOIN email_sync_state s ON s.integration_id = r.integration_id
        WHERE r.status = 'running'
          AND (s.lease_expires_at IS NULL OR s.lease_expires_at < :now)) AS stale_sync_runs,
    (SELECT count(*) FROM email_ingestion_items
        WHERE acquisition_status = 'dead_letter') AS items_dead_letter,
    (SELECT count(*) FROM email_ingestion_items
        WHERE acquisition_status IN ('pending', 'retry', 'processing')) AS items_pending,
    (SELECT count(*) FROM attachments WHERE ingestion_status = 'dead_letter') AS attachments_dead_letter,
    (SELECT count(*) FROM email_ingestion_items
        WHERE acquisition_status = 'processing' AND lease_expires_at > :now) AS items_acquiring,
    (SELECT min(COALESCE(i.next_retry_at, i.created_at)) FROM email_ingestion_items i
        WHERE {CLAIMABLE_INGESTION_ITEM_PREDICATE}) AS oldest_claimable_item_at,
    (SELECT count(*) FROM email_sync_state s JOIN integrations i ON i.id = s.integration_id
        WHERE i.status = 'active' AND s.next_poll_at <= :now
          AND (s.lease_expires_at IS NULL OR s.lease_expires_at <= :now)) AS integrations_due,
    (SELECT count(*) FROM email_sync_state WHERE lease_expires_at > :now) AS leases_held,
    (SELECT min(s.next_poll_at) FROM email_sync_state s JOIN integrations i ON i.id = s.integration_id
        WHERE i.status = 'active') AS oldest_next_poll_at,
    (SELECT count(*) FROM operational_incidents oi
        WHERE oi.status = 'open'
          AND substr(oi.incident_key, 1, {len(EMAIL_SYNC_INCIDENT_PREFIX)}) = :prefix) AS open_incidents
"""


def _seconds_since(now_text: str, then_text: str | None) -> int | None:
    """``GREATEST(0, EXTRACT(EPOCH FROM (now() - then))::int)``; NULL stays NULL.

    Postgres casts numeric to int rounding half away from zero.
    """
    if then_text is None:
        return None
    delta = parse_timestamp(now_text) - parse_timestamp(then_text)
    seconds = Decimal(delta.days * 86400 + delta.seconds) + Decimal(delta.microseconds) / Decimal(10**6)
    return max(0, int(seconds.quantize(Decimal(1), rounding=ROUND_HALF_UP)))


def health_work_state(db: Database, warning_seconds: int, *, now: Any = None) -> dict[str, Any]:
    """The 15-key work-state roll-up (Postgres ``health_work_state(p_warning_seconds)``).

    ``status`` is ``degraded`` when any actionable signal is set: stale
    processing emails, unclaimable pending emails, stale sync runs, dead
    letters, open email-sync incidents, or a poll/acquisition backlog older
    than ``warning_seconds``. ``failed_emails`` never degrades it.
    ``now`` exists for tests; production uses the current time.
    """
    now_text = to_timestamp(now) if now is not None else to_timestamp(utc_now())
    row = db.query_one(_HEALTH_SQL, {"now": now_text, "prefix": EMAIL_SYNC_INCIDENT_PREFIX})

    if row["items_acquiring"] > 0:
        items_stalled = 0
    else:
        items_stalled = _seconds_since(now_text, row["oldest_claimable_item_at"])
    oldest_poll = _seconds_since(now_text, row["oldest_next_poll_at"])

    degraded = (
        row["stale_processing_emails"] > 0
        or row["unclaimable_pending"] > 0
        or row["stale_sync_runs"] > 0
        or row["items_dead_letter"] > 0
        or row["attachments_dead_letter"] > 0
        or row["open_incidents"] > 0
        or (oldest_poll is not None and oldest_poll > warning_seconds)
        or (items_stalled is not None and items_stalled > warning_seconds)
    )
    return {
        "status": "degraded" if degraded else "ok",
        "ready_emails": row["ready_emails"],
        "processing_emails": row["processing_emails"],
        "stale_processing_emails": row["stale_processing_emails"],
        "unclaimable_pending": row["unclaimable_pending"],
        "failed_emails": row["failed_emails"],
        "stale_sync_runs": row["stale_sync_runs"],
        "items_pending": row["items_pending"],
        "items_dead_letter": row["items_dead_letter"],
        "attachments_dead_letter": row["attachments_dead_letter"],
        "items_stalled_seconds": items_stalled,
        "integrations_due": row["integrations_due"],
        "leases_held": row["leases_held"],
        "oldest_next_poll_seconds": oldest_poll,
        "open_incidents": row["open_incidents"],
    }


def pending_email_metrics(db: Database, *, now: Any = None) -> dict[str, int | None]:
    """``/health``'s queue gauges: pending email count and the oldest one's age.

    Content-free: counts and seconds only (replaces the ``emails`` select with
    ``count="exact"`` in ``api/routes/health.py``).
    """
    now_text = to_timestamp(now) if now is not None else to_timestamp(utc_now())
    row = db.query_one(
        "SELECT count(*) AS pending, min(created_at) AS oldest FROM emails "
        "WHERE processing_status = 'pending'"
    )
    return {
        "pending_emails": int(row["pending"]),
        "oldest_pending_age_seconds": _seconds_since(now_text, row["oldest"]),
    }


def ping(db: Database) -> str:
    """The database answers a query (replaces ``SELECT 1`` over asyncpg); the transport name."""
    db.query_one("SELECT 1")
    return "sqlite"


__all__ = [
    "CLAIMABLE_EMAIL_PREDICATE",
    "CLAIMABLE_INGESTION_ITEM_PREDICATE",
    "HEALTH_KEYS",
    "health_work_state",
    "pending_email_metrics",
    "ping",
]
