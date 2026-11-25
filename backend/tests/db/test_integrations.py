"""selko.db.integrations against a real SQLite database.

Ports the database assertions of integration/test_integration_oauth.py and
integration/test_integration_calendars.py (settings), plus the OAuth-state and
sync-log call sites. Every user-scoped read is checked against a second user.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest
from selko.db import integrations as dbi
from selko.db.errors import CheckViolation, UniqueViolation


@pytest.fixture
def published(db, monkeypatch):
    """Live hints the bus would publish after commit."""
    sent: list[tuple[str, dict]] = []
    monkeypatch.setattr(db.bus, "publish", lambda topic, message: sent.append((topic, message)) or 1)
    return sent


# --- integrations -------------------------------------------------------------


def test_get_integration_returns_the_row_and_none_when_absent(db, factory):
    user = factory.user()
    factory.integration(user, "gmail", scopes=["a", "b"], provider_email="me@gmail.com",
                        refresh_token="r1")
    row = dbi.get_integration(db, user, "gmail")
    assert row["access_token"] == "test-access-token"
    assert row["refresh_token"] == "r1"
    assert row["scopes"] == ["a", "b"], "scopes round-trip as an array"
    assert row["provider_email"] == "me@gmail.com"
    assert dbi.get_integration(db, user, "google_calendar") is None


def test_get_integration_never_returns_another_users_row(db, factory):
    alice, bob = factory.user(), factory.user()
    factory.integration(alice, "gmail")
    assert dbi.get_integration(db, bob, "gmail") is None


def test_one_row_per_user_and_provider(db, factory):
    user = factory.user()
    factory.integration(user, "gmail")
    with pytest.raises(UniqueViolation):
        factory.integration(user, "gmail")
    factory.integration(user, "google_calendar")
    assert {r["provider"] for r in dbi.list_integrations(db, user)} == {"gmail", "google_calendar"}


def test_list_integrations_returns_only_the_four_columns_of_the_users_rows(db, factory):
    alice, bob = factory.user(), factory.user()
    iid = factory.integration(alice, "outlook", status="expired", scopes=["Mail.Read"])
    factory.integration(bob, "gmail")
    assert dbi.list_integrations(db, alice) == [
        {"id": iid, "provider": "outlook", "status": "expired", "scopes": ["Mail.Read"]}
    ]


def test_set_status_updates_and_sends_the_live_hint(db, factory, published):
    user = factory.user()
    factory.integration(user, "google_calendar")
    before = dbi.get_integration(db, user, "google_calendar")
    published.clear()
    assert dbi.set_integration_status(db, user, "google_calendar", "expired") == 1
    after = dbi.get_integration(db, user, "google_calendar")
    assert after["status"] == "expired"
    assert after["updated_at"] > before["updated_at"]
    assert [(t, m["resource"], m["operation"]) for t, m in published] == [
        (f"user:{user}", "integrations", "UPDATE")
    ]


def test_set_status_scopes_by_user(db, factory):
    alice, bob = factory.user(), factory.user()
    factory.integration(alice, "gmail")
    assert dbi.set_integration_status(db, bob, "gmail", "revoked") == 0
    assert dbi.get_integration(db, alice, "gmail")["status"] == "active"


def test_set_status_refuses_an_unknown_status(db, factory):
    user = factory.user()
    factory.integration(user, "gmail")
    with pytest.raises(CheckViolation):
        dbi.set_integration_status(db, user, "gmail", "paused")


def test_reactivating_mail_resumes_its_sync_state(db, factory):
    """The integrations_ensure_email_sync_state trigger runs through this path."""
    user = factory.user()
    iid = factory.integration(user, "gmail")
    with db.write() as tx:
        tx.execute("UPDATE email_sync_state SET consecutive_failures = 3, last_error_code = 'x' "
                   "WHERE integration_id = ?", (iid,))
    dbi.set_integration_status(db, user, "gmail", "expired")
    dbi.set_integration_status(db, user, "gmail", "active")
    state = db.query_one("SELECT consecutive_failures, last_error_code FROM email_sync_state "
                         "WHERE integration_id = ?", (iid,))
    assert tuple(state) == (0, None)


def test_update_tokens_without_refresh_token_keeps_it(db, factory):
    user = factory.user()
    factory.integration(user, "gmail", status="expired", refresh_token="keep-me")
    expiry = datetime(2026, 12, 1, 12, 0, tzinfo=UTC)
    assert dbi.update_integration_tokens(db, user, "gmail", access_token="refreshed",
                                         token_expiry=expiry.isoformat()) == 1
    row = dbi.get_integration(db, user, "gmail")
    assert row["access_token"] == "refreshed"
    assert row["refresh_token"] == "keep-me"
    assert row["status"] == "active"
    assert row["token_expiry"] == "2026-12-01T12:00:00.000000Z"


def test_update_tokens_with_refresh_token_writes_it_even_as_none(db, factory):
    user = factory.user()
    factory.integration(user, "outlook", refresh_token="old")
    dbi.update_integration_tokens(
        db, user, "outlook", access_token="a2", refresh_token=None,
        token_expiry=datetime(2026, 12, 1, 4, 0, tzinfo=timezone(timedelta(hours=-8))),
    )
    row = dbi.get_integration(db, user, "outlook")
    assert row["access_token"] == "a2"
    assert row["refresh_token"] is None
    assert row["token_expiry"] == "2026-12-01T12:00:00.000000Z", "stored in UTC"


def test_update_tokens_reads_a_zoneless_expiry_as_utc(db, factory):
    user = factory.user()
    factory.integration(user, "gmail")
    dbi.update_integration_tokens(db, user, "gmail", access_token="a",
                                  token_expiry="2026-12-01T12:00:00.35908")
    assert dbi.get_integration(db, user, "gmail")["token_expiry"] == "2026-12-01T12:00:00.359080Z"


def test_update_tokens_scopes_by_user(db, factory):
    alice, bob = factory.user(), factory.user()
    factory.integration(alice, "gmail")
    assert dbi.update_integration_tokens(db, bob, "gmail", access_token="x", token_expiry=None) == 0
    assert dbi.get_integration(db, alice, "gmail")["access_token"] == "test-access-token"


def test_delete_integration_cascades_and_scopes_by_user(db, factory):
    alice, bob = factory.user(), factory.user()
    iid = factory.integration(alice, "gmail")
    assert db.query_one("SELECT 1 FROM email_sync_state WHERE integration_id = ?", (iid,))
    assert dbi.delete_integration(db, bob, "gmail") == 0
    assert dbi.delete_integration(db, alice, "gmail") == 1
    assert dbi.get_integration(db, alice, "gmail") is None
    assert db.query_one("SELECT 1 FROM email_sync_state WHERE integration_id = ?", (iid,)) is None


# --- oauth_states -------------------------------------------------------------


def test_oauth_state_is_consumed_once(db, factory):
    user = factory.user()
    dbi.save_oauth_state(db, user, "state-1", "gmail", "https://app/cb", code_verifier="v")
    row = dbi.consume_oauth_state(db, "state-1")
    assert row["user_id"] == user
    assert row["provider"] == "gmail"
    assert row["redirect_uri"] == "https://app/cb"
    assert row["code_verifier"] == "v"
    assert row["expired"] is False
    assert dbi.consume_oauth_state(db, "state-1") is None, "a state is single-use"


def test_oauth_state_expires_after_ten_minutes(db, factory):
    user = factory.user()
    dbi.save_oauth_state(db, user, "s", "gmail", "u")
    row = db.query_one("SELECT created_at, expires_at FROM oauth_states WHERE state = 's'")
    created = datetime.fromisoformat(row["created_at"])
    assert datetime.fromisoformat(row["expires_at"]) - created == timedelta(minutes=10)


def test_expired_oauth_state_is_reported_and_deleted(db, factory):
    user = factory.user()
    dbi.save_oauth_state(db, user, "old", "gmail", "u", ttl_seconds=-1)
    row = dbi.consume_oauth_state(db, "old")
    assert row["expired"] is True
    assert db.query_one("SELECT 1 FROM oauth_states WHERE state = 'old'") is None


def test_unknown_oauth_state_is_none(db):
    assert dbi.consume_oauth_state(db, "nope") is None


def test_delete_expired_oauth_states_keeps_live_ones(db, factory):
    user = factory.user()
    dbi.save_oauth_state(db, user, "live", "gmail", "u")
    dbi.save_oauth_state(db, user, "dead", "gmail", "u", ttl_seconds=-5)
    assert dbi.delete_expired_oauth_states(db) == 1
    assert [r[0] for r in db.query("SELECT state FROM oauth_states")] == ["live"]


# --- user_calendar_settings ---------------------------------------------------


def test_settings_are_none_until_saved(db, factory):
    user = factory.user()
    assert dbi.get_calendar_settings(db, user) is None
    assert dbi.get_all_day_settings(db, user) is None


def test_update_and_get_settings(db, factory):
    user = factory.user()
    dbi.upsert_calendar_settings(db, user, {
        "target_calendar_id": "test-calendar-123",
        "default_invitees": "spouse@example.com, partner@example.com",
    })
    row = dbi.get_calendar_settings(db, user)
    assert row["target_calendar_id"] == "test-calendar-123"
    assert row["default_invitees"] == "spouse@example.com, partner@example.com"
    assert row["timezone"] == "America/New_York", "column default on insert"
    assert row["all_day_display_mode"] == "all_day"


def test_settings_upsert_is_idempotent_and_keeps_unsent_columns(db, factory):
    user = factory.user()
    dbi.upsert_calendar_settings(db, user, {"timezone": "Europe/Helsinki"})
    dbi.upsert_calendar_settings(db, user, {"target_calendar_id": "calendar-1",
                                            "default_invitees": "first@example.com"})
    dbi.upsert_calendar_settings(db, user, {"target_calendar_id": "calendar-2",
                                            "default_invitees": "second@example.com"})
    rows = db.query("SELECT * FROM user_calendar_settings WHERE user_id = ?", (user,))
    assert len(rows) == 1
    assert rows[0]["target_calendar_id"] == "calendar-2"
    assert rows[0]["default_invitees"] == "second@example.com"
    assert rows[0]["timezone"] == "Europe/Helsinki", "a column the upsert did not name is kept"


def test_settings_none_clears_a_column(db, factory):
    user = factory.user()
    dbi.upsert_calendar_settings(db, user, {"target_calendar_id": "c", "default_invitees": "x@y"})
    dbi.upsert_calendar_settings(db, user, {"target_calendar_id": None, "default_invitees": None})
    row = dbi.get_calendar_settings(db, user)
    assert row["target_calendar_id"] is None and row["default_invitees"] is None


def test_custom_all_day_times_are_stored_as_postgres_time_text(db, factory):
    user = factory.user()
    dbi.upsert_calendar_settings(db, user, {
        "all_day_display_mode": "custom", "all_day_custom_start": "09:00", "all_day_custom_end": "17:30",
    })
    assert dbi.get_all_day_settings(db, user) == {
        "timezone": "America/New_York", "all_day_display_mode": "custom",
        "all_day_custom_start": "09:00:00", "all_day_custom_end": "17:30:00",
    }


def test_custom_all_day_window_must_be_ordered(db, factory):
    user = factory.user()
    with pytest.raises(CheckViolation):
        dbi.upsert_calendar_settings(db, user, {
            "all_day_display_mode": "custom", "all_day_custom_start": "17:00", "all_day_custom_end": "09:00",
        })


def test_settings_update_bumps_updated_at(db, factory):
    user = factory.user()
    dbi.upsert_calendar_settings(db, user, {"timezone": "UTC"})
    first = dbi.get_calendar_settings(db, user)["updated_at"]
    dbi.upsert_calendar_settings(db, user, {"timezone": "Europe/Helsinki"})
    assert dbi.get_calendar_settings(db, user)["updated_at"] > first


def test_settings_are_per_user(db, factory):
    alice, bob = factory.user(), factory.user()
    dbi.upsert_calendar_settings(db, alice, {"target_calendar_id": "alice-cal"})
    assert dbi.get_calendar_settings(db, bob) is None
    assert dbi.get_all_day_settings(db, bob) is None
    dbi.upsert_calendar_settings(db, bob, {"target_calendar_id": "bob-cal"})
    assert dbi.get_calendar_settings(db, alice)["target_calendar_id"] == "alice-cal"


def test_settings_refuse_unknown_columns(db, factory):
    user = factory.user()
    with pytest.raises(ValueError):
        dbi.upsert_calendar_settings(db, user, {"colour": "red"})
