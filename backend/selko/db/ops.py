"""Operational records: incidents, the LLM call log and the Graph failure ledger.

The table calls of ``services/email_sync_health.py`` (operational_incidents),
``services/llm_logging.py`` (llm_call_log) and ``services/msgraph.py``
(graph_api_failures), docs/specs/sqlite-single-process/02-data-layer.md §3.6
and §3.11. Each insert takes the row the service builds today; columns are
taken from a whitelist, never from the payload alone, and timestamps go
through the codec.
"""

from __future__ import annotations

from typing import Any

from selko.db import errors
from selko.db.codec import new_id, to_timestamp
from selko.db.connection import Database, Tx

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _insert(tx: Tx, table: str, allowed: frozenset[str], timestamps: frozenset[str],
            row: dict[str, Any], defaults: dict[str, Any]) -> dict[str, Any]:
    unknown = set(row) - allowed
    if unknown:
        raise errors.InvalidArgument(f"unknown {table} columns: {sorted(unknown)}")
    values = {**defaults, **{k: v for k, v in row.items()}}
    for column in timestamps:
        if values.get(column) is not None:
            values[column] = to_timestamp(values[column])
    values = tx.schema.encode(table, values)
    cols = ", ".join(values)
    marks = ", ".join(f":{c}" for c in values)
    created = tx.execute(f"INSERT INTO {table} ({cols}) VALUES ({marks}) RETURNING *", values).fetchone()
    return tx.schema.decode(table, created)  # type: ignore[return-value]


def _set_clause(table: str, allowed: frozenset[str], timestamps: frozenset[str],
                fields: dict[str, Any], tx: Tx) -> tuple[str, dict[str, Any]]:
    unknown = set(fields) - allowed
    if unknown:
        raise errors.InvalidArgument(f"cannot update {table} columns: {sorted(unknown)}")
    if not fields:
        raise errors.InvalidArgument(f"no {table} columns to update")
    values = dict(fields)
    for column in timestamps:
        if values.get(column) is not None:
            values[column] = to_timestamp(values[column])
    values = tx.schema.encode(table, values)
    return ", ".join(f"{c} = :{c}" for c in values), values


# ---------------------------------------------------------------------------
# llm_call_log (services/llm_logging.py:168)
# ---------------------------------------------------------------------------

LLM_CALL_COLUMNS = frozenset({
    "operation_type", "model", "email_id", "prompt_text", "response_text",
    "prompt_tokens", "completion_tokens", "total_tokens", "started_at", "completed_at",
    "latency_ms", "success", "error_message", "error_type", "estimated_cost_usd", "provider",
})
_LLM_TIMESTAMPS = frozenset({"started_at", "completed_at"})


def log_llm_call(db: Database, user_id: str, row: dict[str, Any]) -> str:
    """Insert one LLM call record for ``user_id``; returns its id.

    ``row`` is the dict ``LLMLoggingService.log_call`` builds, without
    ``user_id``. An unknown user or email raises ``ForeignKeyViolation`` (the
    service logs it and carries on, as it did with Postgres).
    """
    row = {k: v for k, v in row.items() if k != "user_id"}
    with db.write() as tx:
        created = _insert(
            tx, "llm_call_log", LLM_CALL_COLUMNS, _LLM_TIMESTAMPS, row,
            {"id": new_id(), "user_id": user_id, "started_at": tx.now_text,
             "success": True, "created_at": tx.now_text},
        )
    return created["id"]


# ---------------------------------------------------------------------------
# graph_api_failures (services/msgraph.py:108)
# ---------------------------------------------------------------------------

GRAPH_FAILURE_COLUMNS = frozenset({
    "occurred_at", "environment", "integration_id", "graph_surface", "operation",
    "http_method", "safe_url_template", "http_status", "graph_error_code", "request_id",
    "client_request_id", "retry_after_seconds", "failure_class", "response_summary",
    "run_id", "attempt", "will_retry", "resolved_at",
})
_GRAPH_TIMESTAMPS = frozenset({"occurred_at", "resolved_at"})


def record_graph_failure(db: Database, row: dict[str, Any]) -> str:
    """Append one redacted Graph failure (the payload ``record_graph_failure`` builds); its id."""
    with db.write() as tx:
        created = _insert(
            tx, "graph_api_failures", GRAPH_FAILURE_COLUMNS, _GRAPH_TIMESTAMPS, row,
            {"id": new_id(), "occurred_at": tx.now_text, "attempt": 1, "will_retry": False},
        )
    return created["id"]


# ---------------------------------------------------------------------------
# operational_incidents (services/email_sync_health.py:270-325)
# ---------------------------------------------------------------------------

INCIDENT_INSERT_COLUMNS = frozenset({
    "incident_key", "integration_id", "user_id", "incident_type", "severity", "status",
    "safe_summary", "first_seen_at", "last_seen_at", "resolved_at",
    "opened_notification_sent_at", "resolved_notification_sent_at",
})
INCIDENT_UPDATE_COLUMNS = frozenset({
    "status", "severity", "safe_summary", "last_seen_at", "resolved_at",
    "opened_notification_sent_at", "resolved_notification_sent_at",
})
_INCIDENT_TIMESTAMPS = frozenset({
    "first_seen_at", "last_seen_at", "resolved_at",
    "opened_notification_sent_at", "resolved_notification_sent_at",
})


def raise_incident(
    db: Database,
    *,
    incident_key: str,
    integration_id: str | None,
    user_id: str | None,
    incident_type: str,
    severity: str,
    safe_summary: str,
) -> tuple[dict[str, Any], str | None]:
    """The evaluator's read-then-insert-or-reopen, as one transaction.

    Returns ``(incident, previous_status)``: ``previous_status`` is None when
    the incident was just created, else the status it had (``'resolved'``
    means it was re-opened, so the caller sends an opened notification again).
    A re-opened incident gets its notification stamps cleared, so it can
    notify both opening and recovery a second time; an incident that stayed
    open keeps them.
    """
    with db.write() as tx:
        existing = tx.execute(
            "SELECT * FROM operational_incidents WHERE incident_key = ?", (incident_key,)
        ).fetchone()
        if existing is None:
            created = _insert(
                tx, "operational_incidents", INCIDENT_INSERT_COLUMNS, _INCIDENT_TIMESTAMPS,
                {"incident_key": incident_key, "integration_id": integration_id,
                 "user_id": user_id, "incident_type": incident_type, "severity": severity,
                 "status": "open", "safe_summary": safe_summary},
                {"id": new_id(), "first_seen_at": tx.now_text, "last_seen_at": tx.now_text},
            )
            return created, None
        reopened = existing["status"] == "resolved"
        row = tx.execute(
            """
            UPDATE operational_incidents SET
                status = 'open', severity = ?, safe_summary = ?, last_seen_at = ?, resolved_at = NULL,
                opened_notification_sent_at = ?, resolved_notification_sent_at = ?
            WHERE incident_key = ?
            RETURNING *
            """,
            (
                severity, safe_summary, tx.now_text,
                None if reopened else existing["opened_notification_sent_at"],
                None if reopened else existing["resolved_notification_sent_at"],
                incident_key,
            ),
        ).fetchone()
        return tx.schema.decode("operational_incidents", row), existing["status"]  # type: ignore[return-value]


def update_incident(db: Database, incident_key: str, fields: dict[str, Any]) -> int:
    """Update an incident by key; the number of rows changed (0 or 1)."""
    with db.write() as tx:
        clause, values = _set_clause("operational_incidents", INCIDENT_UPDATE_COLUMNS,
                                     _INCIDENT_TIMESTAMPS, fields, tx)
        return tx.execute(
            f"UPDATE operational_incidents SET {clause} WHERE incident_key = :_key",
            {**values, "_key": incident_key},
        ).rowcount


def update_incident_by_id(db: Database, incident_id: str, fields: dict[str, Any]) -> int:
    """Update an incident by id; the number of rows changed (0 or 1)."""
    with db.write() as tx:
        clause, values = _set_clause("operational_incidents", INCIDENT_UPDATE_COLUMNS,
                                     _INCIDENT_TIMESTAMPS, fields, tx)
        return tx.execute(
            f"UPDATE operational_incidents SET {clause} WHERE id = :_id",
            {**values, "_id": incident_id},
        ).rowcount


def open_incidents(db: Database, key_prefix: str) -> list[dict[str, Any]]:
    """Open incidents whose key starts with ``key_prefix`` (case-sensitive, as Postgres LIKE).

    PostgREST returned these unordered; they come oldest first here.
    """
    rows = db.query(
        "SELECT * FROM operational_incidents WHERE status = 'open' "
        "AND substr(incident_key, 1, ?) = ? ORDER BY first_seen_at, rowid",
        (len(key_prefix), key_prefix),
    )
    return [db.schema.decode("operational_incidents", r) for r in rows]  # type: ignore[misc]


def get_llm_call(db: Database, user_id: str, log_id: str) -> dict[str, Any] | None:
    """One of the user's LLM call records, or None (another user's is None too)."""
    row = db.query_one("SELECT * FROM llm_call_log WHERE id = ? AND user_id = ?", (log_id, user_id))
    return db.schema.decode("llm_call_log", row)


def get_incident(db: Database, incident_key: str) -> dict[str, Any] | None:
    row = db.query_one("SELECT * FROM operational_incidents WHERE incident_key = ?", (incident_key,))
    return db.schema.decode("operational_incidents", row)


def open_incident(db: Database, row: dict[str, Any]) -> dict[str, Any]:
    """Insert an incident (the evaluator's insert); a duplicate key raises UniqueViolation."""
    with db.write() as tx:
        return _insert(
            tx, "operational_incidents", INCIDENT_INSERT_COLUMNS, _INCIDENT_TIMESTAMPS, row,
            {"id": new_id(), "first_seen_at": tx.now_text, "last_seen_at": tx.now_text},
        )


def graph_failures_for_run(db: Database, run_id: str) -> list[dict[str, Any]]:
    """The ledger rows of one sync run, oldest first."""
    rows = db.query(
        "SELECT * FROM graph_api_failures WHERE run_id = ? ORDER BY occurred_at, rowid", (run_id,)
    )
    return [db.schema.decode("graph_api_failures", r) for r in rows]  # type: ignore[misc]


__all__ = [
    "graph_failures_for_run",
    "open_incident",
    "get_incident",
    "get_llm_call",
    "log_llm_call",
    "open_incidents",
    "raise_incident",
    "record_graph_failure",
    "update_incident",
    "update_incident_by_id",
]
