"""Trusted-worker Postgres transport via Supavisor session pooler.

The backend holds the service-role key and bypasses RLS; it pays the full
PostgREST envelope (JWT twice, HTTP headers) for every claim. This module
provides a direct asyncpg path over the session pooler (port 5432) for the
trusted-worker claim/complete/heartbeat calls. Web/iOS/Android and all
RLS-scoped API routes stay on PostgREST.

RLS is bypassed on this pool (postgres role) — same posture as service-role
key today. No new exposure.

Hazards H1/H4: assert_session_mode_url refuses anything that cannot carry
LISTEN/NOTIFY (port 6543 transaction mode) or that is IPv6-only direct host.
H3: TCP keepalives at 60s plus app heartbeat.
"""
from __future__ import annotations

import asyncio
import logging
import time
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

class ConfigurationError(RuntimeError):
    pass

def assert_session_mode_url(url: str) -> None:
    """Refuse anything that cannot carry LISTEN/NOTIFY (H1, H4).

    Raises ConfigurationError when the port is not 5432 or the host is a
    direct db.*.supabase.co endpoint. Never includes the password in the
    message.
    """
    if not url or not isinstance(url, str):
        raise ConfigurationError("SUPABASE_DB_URL is required when background processing is enabled")
    try:
        parsed = urlparse(url)
    except Exception as exc:
        raise ConfigurationError("Invalid SUPABASE_DB_URL format") from exc
    host = (parsed.hostname or "").lower()
    if host.startswith("db.") and host.endswith(".supabase.co"):
        raise ConfigurationError("SUPABASE_DB_URL must use the Supavisor session pooler host (*.pooler.supabase.com), not db.*.supabase.co (H4)")
    if "pooler.supabase.com" not in host:
        if host not in ("localhost", "127.0.0.1", "::1"):
            logger.warning("SUPABASE_DB_URL host is not a pooler host: %s", host)
    port = parsed.port
    if host in ("localhost", "127.0.0.1", "::1"):
        if port not in (5432, 54322):
            raise ConfigurationError(f"SUPABASE_DB_URL must use port 5432 (session) or 54322 (local direct), got {port} (H1)")
    elif port != 5432:
        raise ConfigurationError(f"SUPABASE_DB_URL must use port 5432 (session mode) for LISTEN/NOTIFY, got {port} (H1)")

def _enable_tcp_keepalives(idle_seconds: int):
    """Pool init hook: set SO_KEEPALIVE and TCP keepalive timers (H3).

    asyncpg 0.31 has no keepalive parameter — both `connect_kwargs` and
    top-level `keepalives` kwargs are rejected with TypeError at connect time.
    The socket is only reachable through the pool's documented `init` callback,
    which runs on every new pooled connection.
    """
    import socket

    keepidle = getattr(socket, "TCP_KEEPIDLE", None) or getattr(socket, "TCP_KEEPALIVE", None)
    keepintvl = getattr(socket, "TCP_KEEPINTVL", None)
    keepcnt = getattr(socket, "TCP_KEEPCNT", None)

    async def _init(connection) -> None:
        sock = connection._transport.get_extra_info("socket")
        if sock is None:
            return
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        if keepidle is not None:
            sock.setsockopt(socket.IPPROTO_TCP, keepidle, idle_seconds)
        if keepintvl is not None:
            sock.setsockopt(socket.IPPROTO_TCP, keepintvl, 10)
        if keepcnt is not None:
            sock.setsockopt(socket.IPPROTO_TCP, keepcnt, 3)

    return _init

async def create_pool(config) -> "asyncpg.Pool":  # type: ignore
    """Session-pooler pool with TCP keepalives and statement cache disabled.

    statement_cache_size=0 is set even though session mode supports prepared
    statements: it costs nothing here and makes a future misconfiguration to
    transaction mode fail loudly rather than intermittently.

    TCP keepalives (H3) are set below any known NAT/LB idle timeout so a
    silently dropped socket surfaces as a connection error rather than as a
    listener that never fires again.
    """
    import asyncpg
    assert_session_mode_url(config.supabase_db_url)
    keepalive = max(int(getattr(config, "pg_keepalive_seconds", 60) or 60), 10)
    pool = await asyncpg.create_pool(
        dsn=config.supabase_db_url,
        min_size=max(int(getattr(config, "pg_pool_min_size", 1) or 1), 1),
        max_size=max(int(getattr(config, "pg_pool_max_size", 4) or 4), 1),
        statement_cache_size=0,
        command_timeout=float(getattr(config, "pg_command_timeout_seconds", 30) or 30),
        timeout=getattr(config, "pg_connect_timeout_seconds", 10) or 10,
        server_settings={"application_name": "selko-worker"},
        init=_enable_tcp_keepalives(keepalive),
    )
    logger.info(
        "Created asyncpg session-pooler pool min=%s max=%s keepalive_idle=%ss",
        getattr(config, "pg_pool_min_size", 1),
        getattr(config, "pg_pool_max_size", 4),
        keepalive,
    )
    return pool

class WorkListener:
    """Dedicated LISTEN connection feeding asyncio.Events per work type.

    Owns its own connection, NOT a pool member — a pool connection could be
    handed to a query and lose its LISTEN registration.

    Liveness (H3): every PG_LISTENER_HEARTBEAT_SECONDS it emits a self-NOTIFY
    on 'selko_work' with payload 'heartbeat' and asserts receipt within 10s. A
    miss means the socket is dead-but-open; the connection is torn down and
    reconnected with exponential backoff (1s, 2s, 4s … capped at 60s).
    Reconnect always re-issues LISTEN before declaring itself healthy.
    """

    CHANNEL = "selko_work"
    HEARTBEAT_PAYLOAD = "heartbeat"
    WORK_TYPES = ("email_pending", "event_approved", "item_pending", "attachment_pending")

    def __init__(self, config):
        self.config = config
        self._conn = None
        self._events: dict[str, asyncio.Event] = {}
        self._connected = False
        self._reconnects = 0
        self._last_notification_at: float | None = None
        self._heartbeat_seen = asyncio.Event()
        self._heartbeat_task: asyncio.Task | None = None
        self._stopping = False

    def event_for(self, work_type: str) -> asyncio.Event:
        if work_type not in self._events:
            self._events[work_type] = asyncio.Event()
        return self._events[work_type]

    def _on_notify(self, connection, pid, channel, payload):
        self._last_notification_at = time.time()
        if payload == self.HEARTBEAT_PAYLOAD:
            self._heartbeat_seen.set()
            return
        event = self._events.get(payload)
        if event is not None:
            event.set()
        else:
            logger.debug("WorkListener: unknown payload %r on %s", payload, channel)

    async def _connect(self) -> None:
        import asyncpg

        assert_session_mode_url(self.config.supabase_db_url)
        self._conn = await asyncpg.connect(
            dsn=self.config.supabase_db_url,
            statement_cache_size=0,
            timeout=getattr(self.config, "pg_connect_timeout_seconds", 10) or 10,
            # H3: without this, an execute() on a dead-but-open socket in
            # _heartbeat_loop can block indefinitely, hanging before it ever
            # reaches the wait_for(..., timeout=10.0) meant to detect exactly
            # that — the detector was behind the hang it exists to catch.
            command_timeout=getattr(self.config, "pg_command_timeout_seconds", 30) or 30,
            # Identifiable for the H3 dead-socket drill: the spec terminates
            # the listener backend via pg_stat_activity.application_name.
            server_settings={"application_name": "selko-worker"},
        )
        # H3: this connection sits idle for minutes between heartbeats — the
        # one most likely to need keepalives — but plain connect() has no
        # init= hook like the pool does, so it must be applied by hand.
        keepalive = max(int(getattr(self.config, "pg_keepalive_seconds", 60) or 60), 10)
        await _enable_tcp_keepalives(keepalive)(self._conn)
        await self._conn.add_listener(self.CHANNEL, self._on_notify)
        self._connected = True
        logger.info("WorkListener: LISTEN %s established", self.CHANNEL)

    async def start(self) -> None:
        self._stopping = False
        for work_type in self.WORK_TYPES:
            self.event_for(work_type)
        await self._connect()
        self._heartbeat_task = asyncio.create_task(
            self._heartbeat_loop(), name="pg-work-listener-heartbeat"
        )

    async def _heartbeat_loop(self) -> None:
        interval = max(int(getattr(self.config, "pg_listener_heartbeat_seconds", 120) or 120), 30)
        backoff = 1.0
        while not self._stopping:
            try:
                await asyncio.sleep(interval)
                if self._stopping:
                    return
                self._heartbeat_seen.clear()
                await self._conn.execute(
                    "SELECT pg_notify($1, $2)", self.CHANNEL, self.HEARTBEAT_PAYLOAD
                )
                try:
                    await asyncio.wait_for(self._heartbeat_seen.wait(), timeout=10.0)
                    backoff = 1.0
                except asyncio.TimeoutError:
                    raise ConnectionError("listener heartbeat not received within 10s")
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._connected = False
                self._reconnects += 1
                logger.warning(
                    "WorkListener: reconnecting after %s (reconnect #%d, backoff %.0fs)",
                    exc, self._reconnects, backoff,
                )
                await self._teardown_connection()
                backoff = await self._reconnect_loop(backoff)

    async def _reconnect_loop(self, backoff: float) -> float:
        """Retry _connect() on the backoff schedule until it succeeds or the
        listener is stopping. Returns the backoff to use for the next
        unrelated failure — 1.0 (reset) on success, or the last computed
        value if stopped mid-retry.

        D3 secondary: a failed reconnect used to fall through to the top of
        _heartbeat_loop, which waits the full `interval` (default 120s)
        before trying again — behind, not on, the backoff schedule. Retrying
        here keeps a failed reconnect on the same 1s/2s/4s.../60s schedule as
        every other failure.
        """
        while not self._stopping:
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 60.0)
            try:
                await self._connect()
                # A dropped socket may have lost notifications. Wake every
                # work type so the next drain reconciles from the database,
                # which is the durable source of truth.
                for event in self._events.values():
                    event.set()
                return 1.0
            except Exception as reconnect_exc:
                self._reconnects += 1
                logger.error(
                    "WorkListener: reconnect failed (reconnect #%d, next backoff %.0fs): %s",
                    self._reconnects, backoff, reconnect_exc,
                )
        return backoff

    async def _teardown_connection(self) -> None:
        if self._conn is not None:
            try:
                await self._conn.remove_listener(self.CHANNEL, self._on_notify)
            except Exception:
                pass
            try:
                await self._conn.close()
            except Exception as exc:
                logger.warning("WorkListener: error closing connection: %s", exc)
            self._conn = None

    async def stop(self) -> None:
        self._stopping = True
        self._connected = False
        if self._heartbeat_task is not None:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None
        await self._teardown_connection()

    def status(self) -> dict:
        return {
            "connected": self._connected,
            "reconnects": self._reconnects,
            "last_notification_at": self._last_notification_at,
        }
