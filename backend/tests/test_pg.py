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

def test_create_pool_sets_keepalives_and_timeout(monkeypatch):
    """H3: asyncpg sets no TCP keepalives by default; we must pass them."""
    captured = {}

    async def fake_create_pool(**kwargs):
        captured.update(kwargs)
        return object()

    import asyncpg
    monkeypatch.setattr(asyncpg, "create_pool", fake_create_pool)

    from types import SimpleNamespace
    from selko.services.pg import create_pool

    config = SimpleNamespace(
        supabase_db_url="postgresql://postgres:pw@x.pooler.supabase.com:5432/postgres",
        pg_pool_min_size=1, pg_pool_max_size=4,
        pg_keepalive_seconds=60, pg_connect_timeout_seconds=10,
        pg_command_timeout_seconds=30,
    )
    import asyncio
    asyncio.run(create_pool(config))

    assert captured["statement_cache_size"] == 0
    assert captured["command_timeout"] == 30
    assert captured["server_settings"] == {"application_name": "selko-worker"}
    assert captured["init"] is not None  # keepalives applied via init hook

def test_keepalive_init_hook_sets_socket_options():
    """H3: the pool init hook enables SO_KEEPALIVE with idle/interval/count."""
    import socket
    from selko.services.pg import _enable_tcp_keepalives

    calls = []

    class FakeSock:
        def setsockopt(self, level, opt, val):
            calls.append((level, opt, val))

    class FakeTransport:
        def get_extra_info(self, name):
            assert name == "socket"
            return FakeSock()

    class FakeConn:
        _transport = FakeTransport()

    import asyncio
    asyncio.run(_enable_tcp_keepalives(60)(FakeConn()))

    opts = {opt for _, opt, _ in calls}
    assert socket.SO_KEEPALIVE in opts
    keepidle = getattr(socket, "TCP_KEEPIDLE", None) or getattr(socket, "TCP_KEEPALIVE", None)
    assert keepidle in opts
    if hasattr(socket, "TCP_KEEPINTVL"):
        assert socket.TCP_KEEPINTVL in opts
    if hasattr(socket, "TCP_KEEPCNT"):
        assert socket.TCP_KEEPCNT in opts

def _fake_config():
    from types import SimpleNamespace
    return SimpleNamespace(
        supabase_db_url="postgresql://postgres:pw@x.pooler.supabase.com:5432/postgres",
        pg_connect_timeout_seconds=10,
        pg_listener_heartbeat_seconds=120,
    )

def test_listener_sets_event_for_payload():
    from selko.services.pg import WorkListener
    listener = WorkListener(config=_fake_config())
    event = listener.event_for("email_pending")
    assert not event.is_set()
    listener._on_notify(None, 1, "selko_work", "email_pending")
    assert event.is_set()


def test_heartbeat_payload_does_not_set_work_events():
    from selko.services.pg import WorkListener
    listener = WorkListener(config=_fake_config())
    work = listener.event_for("email_pending")
    listener._on_notify(None, 1, "selko_work", "heartbeat")
    assert listener._heartbeat_seen.is_set()
    assert not work.is_set()


def test_status_is_false_before_start():
    """Regression: the Inc5 stub reported connected=True without a LISTEN."""
    from selko.services.pg import WorkListener
    assert WorkListener(config=_fake_config()).status()["connected"] is False


def test_listener_connection_sets_socket_keepalive(monkeypatch):
    """F1.3 (D3): the listener sits idle for minutes between heartbeats —
    the connection most likely to need keepalives — but _connect() calls
    asyncpg.connect() directly, bypassing the pool's init= hook entirely.
    Fails today (calls is empty).
    """
    import socket
    import asyncio
    from selko.services.pg import WorkListener

    calls = []

    class FakeSock:
        def setsockopt(self, level, opt, val):
            calls.append((level, opt, val))

    class FakeTransport:
        def get_extra_info(self, name):
            assert name == "socket"
            return FakeSock()

    class FakeConn:
        _transport = FakeTransport()

        async def add_listener(self, channel, callback):
            pass

    async def fake_connect(**kwargs):
        return FakeConn()

    import asyncpg
    monkeypatch.setattr(asyncpg, "connect", fake_connect)

    listener = WorkListener(config=_fake_config())
    asyncio.run(listener._connect())

    opts = {opt for _, opt, _ in calls}
    assert socket.SO_KEEPALIVE in opts


def test_listener_connection_sets_command_timeout(monkeypatch):
    """F1.3 (D3): without command_timeout, execute() on a dead-but-open
    socket in _heartbeat_loop can block indefinitely, hanging before it ever
    reaches the wait_for(..., timeout=10.0) meant to detect exactly that.
    Fails today (captured.get("command_timeout") is None).
    """
    import asyncio
    from selko.services.pg import WorkListener

    captured = {}

    class FakeTransport:
        def get_extra_info(self, name):
            return None  # short-circuits keepalive setup; not under test here

    class FakeConn:
        _transport = FakeTransport()

        async def add_listener(self, channel, callback):
            pass

    async def fake_connect(**kwargs):
        captured.update(kwargs)
        return FakeConn()

    import asyncpg
    monkeypatch.setattr(asyncpg, "connect", fake_connect)

    listener = WorkListener(config=_fake_config())
    asyncio.run(listener._connect())

    assert captured.get("command_timeout") is not None


def test_heartbeat_backoff_resets_after_successful_reconnect(monkeypatch):
    """D3 secondary: a failed reconnect used to fall through to the top of
    _heartbeat_loop, which sleeps the full `interval` (default 120s) before
    trying again — behind, not on, the backoff schedule. Fails today:
    WorkListener has no _reconnect_loop method at all.
    """
    import asyncio
    from selko.services.pg import WorkListener

    listener = WorkListener(config=_fake_config())

    sleep_calls = []

    async def fake_sleep(duration):
        sleep_calls.append(duration)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)

    attempts = {"n": 0}

    async def fake_connect():
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ConnectionError("still down")

    monkeypatch.setattr(listener, "_connect", fake_connect)

    result_backoff = asyncio.run(listener._reconnect_loop(1.0))

    # Two failed attempts retry on the backoff schedule (1s, 2s), never the
    # 120s interval; the delay computed for a hypothetical next attempt (4s)
    # is also recorded since it's derived before the successful connect.
    assert sleep_calls == [1.0, 2.0, 4.0]
    assert attempts["n"] == 3
    # Reset to 1.0 for the next *unrelated* failure after success.
    assert result_backoff == 1.0
