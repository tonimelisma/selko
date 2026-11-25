"""Sign-up, sign-in, refresh and sign-out (replaces Supabase Auth).

docs/specs/sqlite-single-process/03-api-auth-web.md §B:

- passwords: bcrypt, cost 10 (GoTrue's), so carried ``$2a$10$`` hashes verify
  unchanged; at most 72 UTF-8 bytes, at least 6 characters;
- access token: JWT HS256 signed with ``SELKO_JWT_SECRET`` (``kid`` "1"; the
  previous secret, ``kid`` "0", still verifies so the secret can rotate), one
  hour, verified locally with no database read;
- refresh token: 32 random bytes in an HttpOnly cookie; only its SHA-256 is
  stored, and it rotates on every use (`selko.db.accounts.rotate_refresh_token`).
"""

from __future__ import annotations

import hashlib
import re
import secrets
import time
from dataclasses import dataclass
from typing import Any

import bcrypt
import jwt

from selko.db import accounts as account_rows
from selko.db.connection import Database

ACCESS_TOKEN_SECONDS = 3600
ISSUER = "selko"
AUDIENCE = "selko"
BCRYPT_COST = 10
MIN_PASSWORD_LENGTH = 6
MAX_PASSWORD_BYTES = 72
_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Verified against on an unknown email, so a miss costs as much as a hit.
_DUMMY_HASH = bcrypt.hashpw(b"selko-dummy-password", bcrypt.gensalt(BCRYPT_COST))

INVALID_CREDENTIALS = "Invalid login credentials"


class AuthError(Exception):
    """A refused auth request: ``code`` for clients, ``message`` for people."""

    def __init__(self, code: str, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status


@dataclass(frozen=True)
class TokenKeys:
    current: str
    previous: str | None = None

    def __post_init__(self) -> None:
        if len(self.current.encode()) < 32:
            raise ValueError("SELKO_JWT_SECRET must be at least 32 bytes")


@dataclass(frozen=True)
class Identity:
    user_id: str
    email: str
    session_id: str
    token: str


@dataclass(frozen=True)
class SignedIn:
    access_token: str
    expires_at: int
    refresh_token: str | None  # None: leave the cookie as it is
    user: dict[str, Any]


# --- validation -------------------------------------------------------------


def validate_email(email: str) -> str:
    normalized = account_rows.normalize_email(email or "")
    if len(normalized) > 254 or not _EMAIL.match(normalized):
        raise AuthError("INVALID_REQUEST", "Enter a valid email address", 422)
    return normalized


def validate_password(password: str) -> bytes:
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise AuthError("WEAK_PASSWORD", f"Password should be at least {MIN_PASSWORD_LENGTH} characters", 422)
    encoded = password.encode("utf-8")
    if len(encoded) > MAX_PASSWORD_BYTES:
        raise AuthError("WEAK_PASSWORD", f"Password must be at most {MAX_PASSWORD_BYTES} bytes", 422)
    return encoded


def hash_password(password: str) -> str:
    return bcrypt.hashpw(validate_password(password), bcrypt.gensalt(BCRYPT_COST)).decode()


def password_matches(password: str, password_hash: str | None) -> bool:
    encoded = (password or "").encode("utf-8")[:MAX_PASSWORD_BYTES]
    try:
        return bcrypt.checkpw(encoded, (password_hash or "").encode() or _DUMMY_HASH)
    except ValueError:
        return False


# --- tokens -----------------------------------------------------------------


def hash_refresh_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def new_refresh_token() -> str:
    return secrets.token_urlsafe(32)


def issue_access_token(keys: TokenKeys, user_id: str, email: str, session_id: str, now: float | None = None) -> tuple[str, int]:
    issued = int(now if now is not None else time.time())
    expires = issued + ACCESS_TOKEN_SECONDS
    token = jwt.encode(
        {"iss": ISSUER, "aud": AUDIENCE, "sub": user_id, "sid": session_id, "email": email,
         "iat": issued, "exp": expires, "typ": "access"},
        keys.current,
        algorithm="HS256",
        headers={"kid": "1"},
    )
    return token, expires


def verify_access_token(keys: TokenKeys, token: str) -> Identity:
    """The token's identity, or AuthError. No database read."""
    try:
        kid = jwt.get_unverified_header(token).get("kid")
        secret = keys.current if kid == "1" else keys.previous if kid == "0" else None
        if secret is None:
            raise jwt.InvalidTokenError("unknown key id")
        claims = jwt.decode(
            token, secret, algorithms=["HS256"], audience=AUDIENCE, issuer=ISSUER, leeway=30,
            options={"require": ["exp", "iat", "sub", "sid", "iss", "aud"]},
        )
    except jwt.PyJWTError as exc:
        raise AuthError("UNAUTHORIZED", "Invalid or expired token", 401) from exc
    if claims.get("typ") != "access":
        raise AuthError("UNAUTHORIZED", "Invalid or expired token", 401)
    return Identity(claims["sub"], claims.get("email", ""), claims["sid"], token)


# --- flows ------------------------------------------------------------------


def _public_user(account: dict[str, Any]) -> dict[str, Any]:
    return {"id": account["id"], "email": account["email"], "created_at": account["created_at"],
            "last_sign_in_at": account.get("last_sign_in_at")}


def sign_up(db: Database, email: str, password: str) -> dict[str, Any]:
    normalized = validate_email(email)
    password_hash = hash_password(password)
    try:
        account = account_rows.create_account(db, normalized, password_hash)
    except account_rows.AccountExists as exc:
        raise AuthError("USER_ALREADY_EXISTS", "User already registered", 409) from exc
    return _public_user(account)


def sign_in(db: Database, keys: TokenKeys, email: str, password: str, user_agent: str | None = None) -> SignedIn:
    account = account_rows.get_account_by_email(db, email or "")
    ok = password_matches(password, account["password_hash"] if account else None)
    if account is None or not ok or account.get("disabled_at") is not None:
        raise AuthError("INVALID_CREDENTIALS", INVALID_CREDENTIALS, 400)
    refresh = new_refresh_token()
    session_id = account_rows.start_session(db, account["id"], hash_refresh_token(refresh), user_agent)
    access, expires = issue_access_token(keys, account["id"], account["email"], session_id)
    fresh = account_rows.get_account(db, account["id"]) or account
    return SignedIn(access, expires, refresh, _public_user(fresh))


def refresh(db: Database, keys: TokenKeys, refresh_token: str | None) -> SignedIn:
    if not refresh_token:
        raise AuthError("INVALID_GRANT", "Session expired", 401)
    successor = new_refresh_token()
    result = account_rows.rotate_refresh_token(db, hash_refresh_token(refresh_token), hash_refresh_token(successor))
    if not result.ok or result.account_id is None or result.session_id is None:
        raise AuthError("INVALID_GRANT", "Session expired", 401)
    account = account_rows.get_account(db, result.account_id)
    if account is None:
        raise AuthError("INVALID_GRANT", "Session expired", 401)
    access, expires = issue_access_token(keys, account["id"], account["email"], result.session_id)
    return SignedIn(access, expires, successor if result.rotated else None, _public_user(account))


def sign_out(db: Database, account_id: str, session_id: str | None, scope: str = "global") -> int:
    if scope not in ("local", "global"):
        raise AuthError("INVALID_REQUEST", "scope must be local or global", 422)
    if scope == "global":
        return account_rows.revoke_sessions(db, account_id, None, "logout_global")
    return account_rows.revoke_sessions(db, account_id, session_id, "logout")
