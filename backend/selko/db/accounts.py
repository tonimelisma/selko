"""Accounts, sessions and refresh tokens (replaces Supabase Auth's tables).

docs/specs/sqlite-single-process/03-api-auth-web.md §B. Passwords are hashed by
the caller (bcrypt, off the event loop); this module stores and compares only
what it is given. Refresh tokens are stored as SHA-256 hashes.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from selko.db.codec import new_id
from selko.db.connection import Database
from selko.db.errors import UniqueViolation

SESSION_IDLE_DAYS = 30
REUSE_WINDOW_SECONDS = 10


class AccountExists(Exception):
    pass


def normalize_email(email: str) -> str:
    return email.strip().lower()


def _account(row: Any) -> dict[str, Any] | None:
    return dict(row) if row is not None else None


def create_account(
    db: Database,
    email: str,
    password_hash: str,
    *,
    account_id: str | None = None,
    confirmed: bool = True,
) -> dict[str, Any]:
    """Insert the account and its profile row in one transaction.

    The profile row (``users``) is what GoTrue's ``handle_new_user`` trigger
    inserted: display name = the email's local part.
    """
    email = normalize_email(email)
    account_id = account_id or new_id()
    try:
        with db.write() as tx:
            tx.execute(
                "INSERT INTO accounts (id, email, password_hash, email_confirmed_at, created_at, updated_at)"
                " VALUES (?, ?, ?, ?, ?, ?)",
                (account_id, email, password_hash, tx.now_text if confirmed else None, tx.now_text, tx.now_text),
            )
            tx.execute(
                "INSERT INTO users (id, email, display_name) VALUES (?, ?, ?)",
                (account_id, email, email.split("@", 1)[0]),
            )
    except UniqueViolation as exc:
        raise AccountExists(email) from exc
    found = get_account(db, account_id)
    assert found is not None
    return found


def get_account(db: Database, account_id: str) -> dict[str, Any] | None:
    return _account(db.query_one("SELECT * FROM accounts WHERE id = ?", (account_id,)))


def get_account_by_email(db: Database, email: str) -> dict[str, Any] | None:
    return _account(
        db.query_one("SELECT * FROM accounts WHERE email = ?", (normalize_email(email),))
    )


def delete_account(db: Database, account_id: str) -> bool:
    """Delete the account; cascades to the profile, every owned row, and sessions."""
    with db.write() as tx:
        cur = tx.execute("DELETE FROM accounts WHERE id = ?", (account_id,))
        return cur.rowcount == 1


# --- sessions ---------------------------------------------------------------


def start_session(
    db: Database, account_id: str, refresh_token_hash: str, user_agent: str | None = None
) -> str:
    """Sign-in: a new session with its first refresh token. Returns the session id."""
    session_id = new_id()
    with db.write() as tx:
        tx.execute(
            "INSERT INTO auth_sessions (id, user_id, created_at, refreshed_at, user_agent) VALUES (?, ?, ?, ?, ?)",
            (session_id, account_id, tx.now_text, tx.now_text, (user_agent or "")[:200] or None),
        )
        tx.execute(
            "INSERT INTO auth_refresh_tokens (id, session_id, token_hash, created_at) VALUES (?, ?, ?, ?)",
            (new_id(), session_id, refresh_token_hash, tx.now_text),
        )
        tx.execute(
            "UPDATE accounts SET last_sign_in_at = ?, updated_at = ? WHERE id = ?",
            (tx.now_text, tx.now_text, account_id),
        )
    return session_id


@dataclass(frozen=True)
class RefreshResult:
    """What a refresh decided. ``new_token_hash`` is None when the cookie stays as it is."""

    ok: bool
    account_id: str | None = None
    session_id: str | None = None
    rotated: bool = False
    reason: str | None = None


def rotate_refresh_token(db: Database, token_hash: str, new_token_hash: str) -> RefreshResult:
    """Spend a refresh token, following 03 §B.4 steps 1-5 in one transaction."""
    with db.write() as tx:
        row = tx.execute(
            "SELECT t.id, t.rotated_at, s.id AS session_id, s.user_id, s.revoked_at, s.refreshed_at, a.disabled_at"
            " FROM auth_refresh_tokens t JOIN auth_sessions s ON s.id = t.session_id"
            " JOIN accounts a ON a.id = s.user_id WHERE t.token_hash = ?",
            (token_hash,),
        ).fetchone()
        if row is None:
            return RefreshResult(ok=False, reason="unknown_token")
        if row["revoked_at"] is not None or row["disabled_at"] is not None:
            return RefreshResult(ok=False, reason="session_revoked")
        if row["refreshed_at"] < tx.ts(-SESSION_IDLE_DAYS * 86400):
            tx.execute(
                "UPDATE auth_sessions SET revoked_at = ?, revoked_reason = 'expired' WHERE id = ?",
                (tx.now_text, row["session_id"]),
            )
            return RefreshResult(ok=False, reason="session_expired")
        if row["rotated_at"] is None:
            tx.execute("UPDATE auth_refresh_tokens SET rotated_at = ? WHERE id = ?", (tx.now_text, row["id"]))
            tx.execute(
                "INSERT INTO auth_refresh_tokens (id, session_id, token_hash, parent_id, created_at) VALUES (?, ?, ?, ?, ?)",
                (new_id(), row["session_id"], new_token_hash, row["id"], tx.now_text),
            )
            tx.execute(
                "UPDATE auth_sessions SET refreshed_at = ? WHERE id = ?", (tx.now_text, row["session_id"])
            )
            return RefreshResult(True, row["user_id"], row["session_id"], rotated=True)
        if row["rotated_at"] >= tx.ts(-REUSE_WINDOW_SECONDS):
            # A concurrent refresh already rotated it: answer, leave the cookie.
            return RefreshResult(True, row["user_id"], row["session_id"], rotated=False)
        tx.execute(
            "UPDATE auth_sessions SET revoked_at = ?, revoked_reason = 'reuse_detected' WHERE id = ?",
            (tx.now_text, row["session_id"]),
        )
        return RefreshResult(ok=False, session_id=row["session_id"], reason="reuse_detected")


def session_for_refresh_token(db: Database, token_hash: str) -> dict[str, Any] | None:
    row = db.query_one(
        "SELECT s.* FROM auth_refresh_tokens t JOIN auth_sessions s ON s.id = t.session_id WHERE t.token_hash = ?",
        (token_hash,),
    )
    return dict(row) if row is not None else None


def revoke_sessions(db: Database, account_id: str, session_id: str | None, reason: str) -> int:
    """Revoke one session (``session_id``) or every active session of the account (None)."""
    with db.write() as tx:
        if session_id is None:
            cur = tx.execute(
                "UPDATE auth_sessions SET revoked_at = ?, revoked_reason = ? WHERE user_id = ? AND revoked_at IS NULL",
                (tx.now_text, reason, account_id),
            )
        else:
            cur = tx.execute(
                "UPDATE auth_sessions SET revoked_at = ?, revoked_reason = ?"
                " WHERE id = ? AND user_id = ? AND revoked_at IS NULL",
                (tx.now_text, reason, session_id, account_id),
            )
        return cur.rowcount


def session_is_active(db: Database, session_id: str) -> bool:
    row = db.query_one("SELECT revoked_at FROM auth_sessions WHERE id = ?", (session_id,))
    return row is not None and row["revoked_at"] is None
