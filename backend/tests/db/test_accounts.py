"""Accounts and sessions (03-api-auth-web.md §B), against a real SQLite database."""

from __future__ import annotations

import time

import bcrypt
import jwt
import pytest

from selko.db import accounts as account_rows
from selko.services import accounts
from selko.services.accounts import AuthError, TokenKeys

KEYS = TokenKeys(current="k" * 40, previous="p" * 40)


def _sign_in(db, email="sam@example.test", password="secret-pw"):
    return accounts.sign_in(db, KEYS, email, password, user_agent="pytest")


@pytest.fixture
def account(db):
    return accounts.sign_up(db, "Sam@Example.TEST ", "secret-pw")


# --- sign-up ----------------------------------------------------------------


# Validates: SEL-400
def test_sign_up_creates_the_account_and_its_profile(db, account):
    assert account["email"] == "sam@example.test"
    profile = db.query_one("SELECT email, display_name FROM users WHERE id = ?", (account["id"],))
    assert tuple(profile) == ("sam@example.test", "sam")


# Validates: SEL-401
def test_sign_up_twice_is_refused(db, account):
    with pytest.raises(AuthError) as exc:
        accounts.sign_up(db, "sam@example.test", "another-pw")
    assert (exc.value.code, exc.value.status) == ("USER_ALREADY_EXISTS", 409)


# Validates: SEL-402
@pytest.mark.parametrize("password", ["short", "x" * 73, "ä" * 37])
def test_passwords_outside_the_limits_are_refused(db, password):
    with pytest.raises(AuthError) as exc:
        accounts.sign_up(db, "new@example.test", password)
    assert exc.value.code == "WEAK_PASSWORD"


# Validates: SEL-402
def test_invalid_email_is_refused(db):
    with pytest.raises(AuthError) as exc:
        accounts.sign_up(db, "not-an-email", "secret-pw")
    assert exc.value.code == "INVALID_REQUEST"


# --- sign-in ----------------------------------------------------------------


# Validates: SEL-403
def test_a_password_hashed_by_gotrue_still_signs_in(db):
    """Hashes carried from Supabase Auth are bcrypt $2a$10$: no one resets a password."""
    gotrue_hash = bcrypt.hashpw(b"carried-pw", bcrypt.gensalt(10, prefix=b"2a")).decode()
    assert gotrue_hash.startswith("$2a$10$")
    account_rows.create_account(db, "old@example.test", gotrue_hash)
    signed = _sign_in(db, "old@example.test", "carried-pw")
    assert signed.user["email"] == "old@example.test"


# Validates: SEL-404
@pytest.mark.parametrize(
    ("email", "password"), [("sam@example.test", "wrong-pw"), ("nobody@example.test", "secret-pw")]
)
def test_wrong_password_and_unknown_email_get_the_same_answer(db, account, email, password):
    with pytest.raises(AuthError) as exc:
        _sign_in(db, email, password)
    assert (exc.value.code, exc.value.message) == ("INVALID_CREDENTIALS", "Invalid login credentials")


# Validates: SEL-404
def test_disabled_account_cannot_sign_in(db, account):
    with db.write() as tx:
        tx.execute("UPDATE accounts SET disabled_at = ? WHERE id = ?", (tx.now_text, account["id"]))
    with pytest.raises(AuthError):
        _sign_in(db)


# Validates: SEL-410, SEL-420
def test_sign_in_issues_a_verifiable_access_token(db, account):
    signed = _sign_in(db)
    identity = accounts.verify_access_token(KEYS, signed.access_token)
    assert identity.user_id == account["id"]
    assert account_rows.session_is_active(db, identity.session_id)
    assert signed.refresh_token and len(signed.refresh_token) >= 40
    stored = db.query_one("SELECT token_hash FROM auth_refresh_tokens")[0]
    assert stored == accounts.hash_refresh_token(signed.refresh_token) != signed.refresh_token
    assert db.query_one("SELECT last_sign_in_at FROM accounts")[0] is not None


# --- access tokens ----------------------------------------------------------


# Validates: SEL-411
def test_tokens_signed_with_the_previous_key_still_verify(db, account):
    old = TokenKeys(current="p" * 40)
    token = jwt.encode(
        {"iss": "selko", "aud": "selko", "sub": account["id"], "sid": "s", "iat": int(time.time()),
         "exp": int(time.time()) + 60, "typ": "access"},
        old.current, algorithm="HS256", headers={"kid": "0"},
    )
    assert accounts.verify_access_token(KEYS, token).user_id == account["id"]


# Validates: SEL-412
@pytest.mark.parametrize(
    "mutate",
    [
        lambda c: {**c, "exp": int(time.time()) - 120},
        lambda c: {**c, "aud": "authenticated"},  # a Supabase token
        lambda c: {**c, "typ": "refresh"},
        lambda c: {k: v for k, v in c.items() if k != "sid"},
    ],
)
def test_invalid_access_tokens_are_refused(mutate):
    claims = {"iss": "selko", "aud": "selko", "sub": "u", "sid": "s", "iat": int(time.time()),
              "exp": int(time.time()) + 60, "typ": "access"}
    token = jwt.encode(mutate(claims), KEYS.current, algorithm="HS256", headers={"kid": "1"})
    with pytest.raises(AuthError) as exc:
        accounts.verify_access_token(KEYS, token)
    assert exc.value.status == 401


# Validates: SEL-412
def test_a_token_signed_with_another_secret_is_refused():
    token, _ = accounts.issue_access_token(TokenKeys(current="z" * 40), "u", "e", "s")
    with pytest.raises(AuthError):
        accounts.verify_access_token(KEYS, token)


# --- refresh ----------------------------------------------------------------


def _age_rotation(db, seconds):
    with db.write() as tx:
        tx.execute("UPDATE auth_refresh_tokens SET rotated_at = ? WHERE rotated_at IS NOT NULL", (tx.ts(-seconds),))


# Validates: SEL-421
def test_refresh_rotates_the_token(db, account):
    first = _sign_in(db)
    second = accounts.refresh(db, KEYS, first.refresh_token)
    assert second.refresh_token and second.refresh_token != first.refresh_token
    third = accounts.refresh(db, KEYS, second.refresh_token)
    assert third.refresh_token != second.refresh_token


# Validates: SEL-422
def test_a_concurrent_refresh_within_ten_seconds_answers_without_rotating(db, account):
    first = _sign_in(db)
    accounts.refresh(db, KEYS, first.refresh_token)
    again = accounts.refresh(db, KEYS, first.refresh_token)
    assert again.refresh_token is None  # leave the cookie: the other response set it
    assert accounts.verify_access_token(KEYS, again.access_token).user_id == account["id"]


# Validates: SEL-423
def test_reusing_a_spent_token_later_revokes_the_session(db, account):
    first = _sign_in(db)
    second = accounts.refresh(db, KEYS, first.refresh_token)
    _age_rotation(db, 11)
    with pytest.raises(AuthError) as exc:
        accounts.refresh(db, KEYS, first.refresh_token)
    assert exc.value.code == "INVALID_GRANT"
    # The stolen token's whole session is gone, including the legitimate successor.
    with pytest.raises(AuthError):
        accounts.refresh(db, KEYS, second.refresh_token)
    assert db.query_one("SELECT revoked_reason FROM auth_sessions")[0] == "reuse_detected"


# Validates: SEL-424
def test_an_idle_session_expires(db, account):
    first = _sign_in(db)
    with db.write() as tx:
        tx.execute("UPDATE auth_sessions SET refreshed_at = ?", (tx.ts(-31 * 86400),))
    with pytest.raises(AuthError):
        accounts.refresh(db, KEYS, first.refresh_token)
    assert db.query_one("SELECT revoked_reason FROM auth_sessions")[0] == "expired"


# Validates: SEL-425
@pytest.mark.parametrize("token", [None, "", "not-a-real-token"])
def test_refresh_without_a_valid_token_is_refused(db, token):
    with pytest.raises(AuthError) as exc:
        accounts.refresh(db, KEYS, token)
    assert exc.value.status == 401


# --- sign-out ---------------------------------------------------------------


# Validates: SEL-426
def test_global_sign_out_ends_every_session(db, account):
    phone, laptop = _sign_in(db), _sign_in(db)
    sid = accounts.verify_access_token(KEYS, phone.access_token).session_id
    assert accounts.sign_out(db, account["id"], sid, "global") == 2
    for signed in (phone, laptop):
        with pytest.raises(AuthError):
            accounts.refresh(db, KEYS, signed.refresh_token)


# Validates: SEL-426
def test_local_sign_out_ends_only_this_session(db, account):
    phone, laptop = _sign_in(db), _sign_in(db)
    sid = accounts.verify_access_token(KEYS, phone.access_token).session_id
    assert accounts.sign_out(db, account["id"], sid, "local") == 1
    with pytest.raises(AuthError):
        accounts.refresh(db, KEYS, phone.refresh_token)
    assert accounts.refresh(db, KEYS, laptop.refresh_token).user["id"] == account["id"]


# Validates: SEL-426
def test_another_users_session_cannot_be_signed_out(db, account):
    other = accounts.sign_up(db, "other@example.test", "secret-pw")
    mine = _sign_in(db)
    sid = accounts.verify_access_token(KEYS, mine.access_token).session_id
    assert accounts.sign_out(db, other["id"], sid, "local") == 0
    assert account_rows.session_is_active(db, sid)


# Validates: SEL-470
def test_deleting_an_account_removes_everything_it_owns(db, account, factory):
    _sign_in(db)
    event = factory.event(account["id"])
    assert account_rows.delete_account(db, account["id"])
    for table in ("users", "auth_sessions", "auth_refresh_tokens", "events"):
        assert db.query_one(f"SELECT count(*) FROM {table}")[0] == 0, table
    assert factory.row("events", event) is None
