"""Integrations, OAuth states and calendar settings.

The calendar sync log lives in ``db/calendar_work.py``.

The SQLite replacement for every supabase-py ``.table(...)`` call on
``integrations``, ``oauth_states``, and ``user_calendar_settings`` (docs/specs/sqlite-single-process/02-data-layer.md
§3.1, §3.4, §3.10). RPCs on these tables (``complete_integration_reauthorization``)
and ``integration_recoveries`` live in ``db/recovery.py``; ``email_sync_*`` and
``email_folders`` in ``db/email_sync.py``.

=========================================  =====================================
Service call site                          db function
=========================================  =====================================
services/integrations.py:148               get_integration
  (get_provider_integration)
services/integrations.py:310               get_integration
  (get_oauth_credentials)
services/integrations.py:374               set_integration_status
  (update_integration_status)
services/integrations.py:457               update_integration_tokens
  (update_oauth_credentials)                 (refresh_token left untouched)
services/integrations.py:489               update_integration_tokens
  (update_provider_tokens)                   (refresh_token=...)
services/integrations.py:600               save_oauth_state
  (_save_oauth_state)
services/integrations.py:629, :645, :649   consume_oauth_state (one transaction)
  (_validate_and_consume_oauth_state)
services/integrations.py:674               delete_expired_oauth_states
  (_clean_expired_oauth_states)
services/integrations.py:910               delete_integration
  (delete_integration)
services/calendars.py:238                  list_integrations
  (_user_integrations)
services/calendars.py:461                  get_calendar_settings
  (get_calendar_settings)
services/calendars.py:511                  get_all_day_settings
  (get_all_day_policy_and_timezone)
services/calendars.py:597                  upsert_calendar_settings
  (update_calendar_settings)
api/routes/integrations.py:400             upsert_calendar_settings
  (google_oauth_callback, timezone)
=========================================  =====================================

``users``: no service makes a ``.table("users")`` call except the health ping
(``api/routes/health.py:120`` -> ``db.health.ping``); the profile row is
written with the account (auth section). Nothing here.

Every function takes ``db`` first and ``user_id`` next when the row is
user-owned; a read never returns another user's row. The OAuth-state
functions are keyed by the unguessable state token, as before.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from selko.db import codec
from selko.db.connection import Database

# Columns stored as timestamps (timestamptz in Postgres).
_TIMESTAMPS = {
    "integrations": {"token_expiry", "last_sync_at", "created_at", "updated_at", "last_photo_sync_at"},
    "oauth_states": {"created_at", "expires_at"},
    "user_calendar_settings": {"updated_at"},
}
_TIMES = {"user_calendar_settings": {"all_day_custom_start", "all_day_custom_end"}}

_SETTINGS_COLUMNS = (
    "target_calendar_id",
    "default_invitees",
    "timezone",
    "all_day_display_mode",
    "all_day_custom_start",
    "all_day_custom_end",
)

_UNSET: Any = object()


def timestamp(value: datetime | str | None) -> str | None:
    """A caller's moment as stored text.

    Postgres read a zone-less value given to a ``timestamptz`` column in the
    session zone, which is UTC on Supabase; this does the same rather than
    refusing it.
    """
    if value is None:
        return None
    if isinstance(value, str):
        value = datetime.fromisoformat(value)
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return codec.to_timestamp(value)


def _encode(db: Database, table: str, values: dict[str, Any]) -> dict[str, Any]:
    out = dict(values)
    for column in _TIMESTAMPS.get(table, ()):
        if column in out:
            out[column] = timestamp(out[column])
    for column in _TIMES.get(table, ()):
        if column in out:
            out[column] = codec.to_time(out[column])
    return db.schema.encode(table, out)


def _decode(db: Database, table: str, row: Any) -> dict[str, Any] | None:
    return db.schema.decode(table, row)


# ---------------------------------------------------------------------------
# integrations
# ---------------------------------------------------------------------------


def get_integration(db: Database, user_id: str, provider: str) -> dict[str, Any] | None:
    """The user's integration row for one provider (``select *``), or None."""
    row = db.query_one(
        "SELECT * FROM integrations WHERE user_id = ? AND provider = ?",
        (codec.to_id(user_id), provider),
    )
    return _decode(db, "integrations", row)


def list_integrations(db: Database, user_id: str) -> list[dict[str, Any]]:
    """``id, provider, status, scopes`` of every integration the user has."""
    rows = db.query(
        "SELECT id, provider, status, scopes FROM integrations WHERE user_id = ?",
        (codec.to_id(user_id),),
    )
    return [_decode(db, "integrations", row) for row in rows]  # type: ignore[misc]


def active_integration_user_ids(db: Database, provider: str) -> set[str]:
    """Users with an active integration for ``provider`` (a scheduler's fan-out).

    Service-wide by design: user ids only, no integration row leaves here.
    """
    rows = db.query(
        "SELECT DISTINCT user_id FROM integrations WHERE provider = ? AND status = 'active'",
        (provider,),
    )
    return {r[0] for r in rows}


def set_last_photo_sync_at(db: Database, user_id: str, provider: str = "google_photos") -> int:
    """Stamp the user's photo integration as synced now. Returns rows changed."""
    with db.write() as tx:
        return tx.execute(
            "UPDATE integrations SET last_photo_sync_at = ?, updated_at = ? "
            "WHERE user_id = ? AND provider = ?",
            (tx.now_text, tx.now_text, codec.to_id(user_id), provider),
        ).rowcount


def count_active_mailboxes(db: Database) -> int:
    """Active Gmail/Outlook integrations, across users (``/health/egress``'s divisor).

    Service-wide by design: a count, no row leaves this function.
    """
    row = db.query_one(
        "SELECT count(*) FROM integrations WHERE provider IN ('gmail', 'outlook') AND status = 'active'"
    )
    return int(row[0])


def set_integration_status(db: Database, user_id: str, provider: str, status: str) -> int:
    """Set an integration's status. Returns the number of rows changed (0 or 1).

    The triggers do what Postgres's did: ``updated_at``, the email sync state
    for an active Gmail/Outlook row, and the ``integrations`` live hint.
    """
    with db.write() as tx:
        cur = tx.execute(
            "UPDATE integrations SET status = ?, updated_at = ? WHERE user_id = ? AND provider = ?",
            (status, tx.now_text, codec.to_id(user_id), provider),
        )
        return cur.rowcount


def update_integration_tokens(
    db: Database,
    user_id: str,
    provider: str,
    *,
    access_token: str,
    token_expiry: datetime | str | None,
    refresh_token: str | None = _UNSET,
) -> int:
    """Store refreshed tokens and mark the integration active.

    ``refresh_token`` is written only when given (``update_provider_tokens``
    writes it, even as None; ``update_oauth_credentials`` never touches it).
    """
    sets = ["access_token = ?", "token_expiry = ?", "status = 'active'", "updated_at = ?"]
    with db.write() as tx:
        params: list[Any] = [access_token, timestamp(token_expiry), tx.now_text]
        if refresh_token is not _UNSET:
            sets.insert(1, "refresh_token = ?")
            params.insert(1, refresh_token)
        params += [codec.to_id(user_id), provider]
        cur = tx.execute(
            f"UPDATE integrations SET {', '.join(sets)} WHERE user_id = ? AND provider = ?",
            params,
        )
        return cur.rowcount


def delete_integration(db: Database, user_id: str, provider: str) -> int:
    """Disconnect: delete the row; its sync state, mirror and recoveries cascade."""
    with db.write() as tx:
        cur = tx.execute(
            "DELETE FROM integrations WHERE user_id = ? AND provider = ?",
            (codec.to_id(user_id), provider),
        )
        return cur.rowcount


# ---------------------------------------------------------------------------
# oauth_states
# ---------------------------------------------------------------------------

OAUTH_STATE_TTL_SECONDS = 600


def save_oauth_state(
    db: Database,
    user_id: str,
    state: str,
    provider: str,
    redirect_uri: str,
    code_verifier: str | None = None,
    *,
    ttl_seconds: float = OAUTH_STATE_TTL_SECONDS,
) -> None:
    """Record a new OAuth flow's state; it expires ``ttl_seconds`` from now (10 min)."""
    with db.write() as tx:
        tx.execute(
            "INSERT INTO oauth_states (state, user_id, provider, redirect_uri, code_verifier, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (state, codec.to_id(user_id), provider, redirect_uri, code_verifier,
             tx.now_text, tx.ts(ttl_seconds)),
        )


def consume_oauth_state(db: Database, state: str) -> dict[str, Any] | None:
    """Read and delete a state in one transaction: it can be used once.

    Returns None for an unknown state. Otherwise the row, plus ``expired``
    (``now > expires_at``, as the service compared). An expired state is
    deleted too, as the service's own cleanup did. Two concurrent callbacks
    with the same state can no longer both pass: the second finds nothing.
    """
    with db.write() as tx:
        row = tx.execute(
            "DELETE FROM oauth_states WHERE state = ? RETURNING *", (state,)
        ).fetchone()
        if row is None:
            return None
        out = _decode(db, "oauth_states", row)
        assert out is not None
        out["expired"] = tx.now_text > out["expires_at"]
        return out


def delete_expired_oauth_states(db: Database) -> int:
    """Delete every state whose ``expires_at`` has passed. Returns how many."""
    with db.write() as tx:
        cur = tx.execute("DELETE FROM oauth_states WHERE expires_at < ?", (tx.now_text,))
        return cur.rowcount


# ---------------------------------------------------------------------------
# user_calendar_settings
# ---------------------------------------------------------------------------


def get_calendar_settings(db: Database, user_id: str) -> dict[str, Any] | None:
    """The user's settings row (``select *``), or None when they have none."""
    row = db.query_one(
        "SELECT * FROM user_calendar_settings WHERE user_id = ?", (codec.to_id(user_id),)
    )
    return _decode(db, "user_calendar_settings", row)


def get_all_day_settings(db: Database, user_id: str) -> dict[str, Any] | None:
    """``timezone, all_day_display_mode, all_day_custom_start, all_day_custom_end``, or None."""
    row = db.query_one(
        "SELECT timezone, all_day_display_mode, all_day_custom_start, all_day_custom_end "
        "FROM user_calendar_settings WHERE user_id = ?",
        (codec.to_id(user_id),),
    )
    return _decode(db, "user_calendar_settings", row)


def upsert_calendar_settings(db: Database, user_id: str, fields: dict[str, Any]) -> None:
    """PostgREST ``upsert``: insert with defaults, or update only the given columns.

    A column given as None is written as NULL (``update_calendar_settings``
    always passes ``target_calendar_id`` and ``default_invitees``, so passing
    None clears them, as today). Times are stored as ``HH:MM:SS``, the text
    Postgres returned for a ``time`` column.
    """
    unknown = set(fields) - set(_SETTINGS_COLUMNS) - {"user_id"}
    if unknown:
        raise ValueError(f"unknown user_calendar_settings columns: {sorted(unknown)}")
    values = _encode(db, "user_calendar_settings", {k: v for k, v in fields.items() if k != "user_id"})
    uid = codec.to_id(user_id)
    with db.write() as tx:
        cols = ["user_id", *values, "updated_at"]
        params = [uid, *values.values(), tx.now_text]
        update = ", ".join(f"{c} = excluded.{c}" for c in values) or "user_id = excluded.user_id"
        tx.execute(
            f"INSERT INTO user_calendar_settings ({', '.join(cols)}) "
            f"VALUES ({', '.join('?' for _ in cols)}) "
            f"ON CONFLICT (user_id) DO UPDATE SET {update}",
            params,
        )


__all__ = [
    "OAUTH_STATE_TTL_SECONDS",
    "active_integration_user_ids",
    "consume_oauth_state",
    "count_active_mailboxes",
    "delete_expired_oauth_states",
    "delete_integration",
    "get_all_day_settings",
    "get_calendar_settings",
    "get_integration",
    "list_integrations",
    "save_oauth_state",
    "set_integration_status",
    "set_last_photo_sync_at",
    "timestamp",
    "update_integration_tokens",
    "upsert_calendar_settings",
]
