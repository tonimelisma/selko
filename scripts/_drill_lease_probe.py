"""Report leases and running sync runs held by one worker instance.

Prints "held=<n>" so the drill can wait for a clean drain before stopping the
worker. Content-free: counts only.
"""
import asyncio
import sys

import asyncpg

from selko.config import load_config


async def main() -> int:
    prefix = sys.argv[1]
    config = load_config(env_override="staging")
    conn = await asyncpg.connect(config.supabase_db_url)
    try:
        held = await conn.fetchval(
            """
            SELECT (
                SELECT count(*) FROM public.email_sync_state
                WHERE lease_owner LIKE $1 || '%'
                  AND lease_expires_at IS NOT NULL AND lease_expires_at > now()
            ) + (
                SELECT count(*) FROM public.email_sync_runs r
                JOIN public.email_sync_state s ON s.integration_id = r.integration_id
                WHERE r.status = 'running' AND s.lease_owner LIKE $1 || '%'
            )
            """,
            prefix,
        )
        print(f"held={held}")
    finally:
        await conn.close()
    return 0


sys.exit(asyncio.run(main()))
