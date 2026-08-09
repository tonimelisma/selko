"""Inc3: pg pool session mode guard and pool creation."""
import pytest

from selko.services.pg import ConfigurationError, assert_session_mode_url

def test_assert_accepts_5432_pooler():
    assert_session_mode_url("postgresql://postgres:secret@db.pooler.supabase.com:5432/postgres")
    assert_session_mode_url("postgresql://postgres:secret@localhost:5432/postgres")
    # Local direct for tests allowed
    assert_session_mode_url("postgresql://postgres:postgres@localhost:54322/postgres")

def test_assert_rejects_6543_transaction_mode():
    with pytest.raises(ConfigurationError) as exc:
        assert_session_mode_url("postgresql://postgres:secret@db.pooler.supabase.com:6543/postgres")
    assert "5432" in str(exc.value)
    assert "secret" not in str(exc.value)

def test_assert_rejects_direct_host():
    with pytest.raises(ConfigurationError) as exc:
        assert_session_mode_url("postgresql://postgres:secret@db.abcdefgh.supabase.co:5432/postgres")
    assert "pooler" in str(exc.value).lower()
    assert "secret" not in str(exc.value)

def test_assert_password_never_in_message():
    bad_url = "postgresql://postgres:mySuperSecret123@db.pooler.supabase.com:6543/postgres"
    try:
        assert_session_mode_url(bad_url)
        assert False, "should have raised"
    except ConfigurationError as e:
        assert "mySuperSecret123" not in str(e)
        assert "mySuperSecret123" not in repr(e)

def test_assert_rejects_missing_url():
    with pytest.raises(ConfigurationError):
        assert_session_mode_url("")
    with pytest.raises(ConfigurationError):
        assert_session_mode_url(None)
