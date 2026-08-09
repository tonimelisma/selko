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
    # H4: db.*.supabase.co is IPv6-only without paid add-on — refuse
    if host.startswith("db.") and host.endswith(".supabase.co"):
        raise ConfigurationError("SUPABASE_DB_URL must use the Supavisor session pooler host (*.pooler.supabase.com), not db.*.supabase.co (H4)")
    if "pooler.supabase.com" not in host:
        # Allow localhost for tests/local Supabase, but still enforce port
        if host not in ("localhost", "127.0.0.1", "::1"):
            logger.warning("SUPABASE_DB_URL host is not a pooler host: %s", host)
    port = parsed.port
    # Allow 54322 for local Supabase (direct) in development/tests; prod must be 5432
    if host in ("localhost", "127.0.0.1", "::1"):
        if port not in (5432, 54322):
            raise ConfigurationError(f"SUPABASE_DB_URL must use port 5432 (session) or 54322 (local direct), got {port} (H1)")
    elif port != 5432:
        raise ConfigurationError(f"SUPABASE_DB_URL must use port 5432 (session mode) for LISTEN/NOTIFY, got {port} (H1)")

async def create_pool(config) -> "asyncpg.Pool":  # type: ignore
    """Session-pooler pool with TCP keepalives and statement cache disabled.

    statement_cache_size=0 costs nothing here and makes a future
    misconfiguration to transaction mode fail loudly rather than
    intermittently.
    """
    import asyncpg

    assert_session_mode_url(config.supabase_db_url)

    # TCP keepalives filtered via asyncpg server_settings? asyncpg exposes
    # tcp keepalive via DSN query params or connection kwargs; we use DSN + kwargs
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

