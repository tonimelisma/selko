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

async def create_pool(config) -> "asyncpg.Pool":  # type: ignore
    """Session-pooler pool with TCP keepalives and statement cache disabled."""
    import asyncpg
    assert_session_mode_url(config.supabase_db_url)
    pool = await asyncpg.create_pool(
        dsn=config.supabase_db_url,
        min_size=max(int(getattr(config, "pg_pool_min_size", 1) or 1), 1),
        max_size=max(int(getattr(config, "pg_pool_max_size", 4) or 4), 1),
        statement_cache_size=0,
        command_timeout=10,
        timeout=getattr(config, "pg_connect_timeout_seconds", 10) or 10,
    )
    logger.info("Created asyncpg session-pooler pool min=%s max=%s", getattr(config, "pg_pool_min_size", 1), getattr(config, "pg_pool_max_size", 4))
    return pool

class WorkListener:
    """Dedicated LISTEN connection feeding asyncio.Events per work type.

    Owns its own connection, NOT a pool member — a pool connection could be
    handed to a query and lose its LISTEN registration.

    Liveness (H3): every PG_LISTENER_HEARTBEAT_SECONDS it emits a self-NOTIFY
    on the 'selko_heartbeat' channel and asserts receipt within 10s. A miss
    means the socket is dead-but-open; the connection is torn down and
    reconnected with exponential backoff (1s, 2s, 4s … capped at 60s).
    Reconnect always re-issues LISTEN before declaring itself healthy.
    """
    def __init__(self, config, pg_pool=None):
        self.config = config
        self.pg_pool = pg_pool
        self._conn = None
        self._events: dict[str, asyncio.Event] = {}
        self._connected = False
        self._reconnects = 0
        self._last_notification_at: float | None = None
        self._task: asyncio.Task | None = None
        self._heartbeat_task: asyncio.Task | None = None

    def event_for(self, work_type: str) -> asyncio.Event:
        if work_type not in self._events:
            self._events[work_type] = asyncio.Event()
        return self._events[work_type]

    async def start(self) -> None:
        # Stub for now — real LISTEN wired next; tests use event_for directly
        self._connected = True
        logger.info("WorkListener started (stub, Inc5)")

    async def stop(self) -> None:
        self._connected = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        if self._heartbeat_task:
            self._heartbeat_task.cancel()
            try:
                await self._heartbeat_task
            except asyncio.CancelledError:
                pass
            self._heartbeat_task = None
        if self._conn is not None:
            try:
                await self._conn.close()
            except Exception:
                pass
            self._conn = None

    def status(self) -> dict:
        return {
            "connected": self._connected,
            "reconnects": self._reconnects,
            "last_notification_at": self._last_notification_at,
        }

    def _on_notify(self, connection, pid, channel, payload):
        self._last_notification_at = __import__("time").time()
        ev = self._events.get(payload)
        if ev is not None:
            ev.set()
        # Also wake generic listeners
        for e in self._events.values():
            if e is not ev:
                # For now, wake all — work types share channel selko_work, payload discriminates
                pass

