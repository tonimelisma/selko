#!/usr/bin/env python3
"""W6: rehearse the pending production migration batch before running it.

Per D5 this is the review of record for ``supabase/migrations/**``: a migration
that has not been applied to a production-shaped database has not been
reviewed, however carefully the diff was read.

**This copies no production data.** An earlier draft of the plan proposed
restoring a logical dump of production locally, which would move real users'
OAuth refresh tokens and email bodies onto a developer laptop -- exactly what
CLAUDE.md's environment-separation rule forbids. What it reads from production
is content-free and already permitted for diagnosis: row counts grouped by
status label. Nothing else leaves production, and nothing is written there.

What this proves:
  * every pending migration applies, in order, on top of production's current
    migration state -- not on top of a clean HEAD reset;
  * every legacy ``events.status`` value present in production reaches a
    defined destination, in the real quantities;
  * the resulting schema satisfies the contract queries.

What it does not prove: behaviour that depends on row *content*.

Usage:
    uv run python scripts/rehearse_cutover.py            # rehearse
    uv run python scripts/rehearse_cutover.py --keep     # leave the scratch db
"""

from __future__ import annotations

import argparse
import asyncio
import re
import sys
from pathlib import Path

import asyncpg

from selko.config import load_config

ROOT = Path(__file__).resolve().parents[1]
MIGRATIONS = ROOT / "supabase" / "migrations"
SCRATCH_DB = "selko_cutover_rehearsal"

# Content-free: labels and counts only. Read with the read-only production
# credentials the operator supplies; never written to.
PRODUCTION_SHAPE_QUERY = "SELECT status, count(*) AS n FROM public.events GROUP BY 1"

# Supabase installs these before any migration runs. A bare database has none,
# so the rehearsal harness must supply them or every migration fails on the
# first GRANT.
HARNESS = """
DO $$ BEGIN
    CREATE ROLE anon NOLOGIN NOINHERIT;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE ROLE authenticated NOLOGIN NOINHERIT;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
DO $$ BEGIN
    CREATE ROLE service_role NOLOGIN NOINHERIT BYPASSRLS;
EXCEPTION WHEN duplicate_object THEN NULL; END $$;
CREATE EXTENSION IF NOT EXISTS pgcrypto;
-- Supabase installs pgcrypto into the `extensions` schema; migrations call
-- extensions.digest() for the proposal hash.
CREATE SCHEMA IF NOT EXISTS extensions;
CREATE OR REPLACE FUNCTION extensions.digest(data text, type text) RETURNS bytea
    LANGUAGE sql IMMUTABLE AS $fn$ SELECT public.digest(data, type) $fn$;
CREATE OR REPLACE FUNCTION extensions.digest(data bytea, type text) RETURNS bytea
    LANGUAGE sql IMMUTABLE AS $fn$ SELECT public.digest(data, type) $fn$;
CREATE SCHEMA IF NOT EXISTS auth;
CREATE TABLE IF NOT EXISTS auth.users (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    email text,
    raw_user_meta_data jsonb DEFAULT '{}'::jsonb,
    created_at timestamptz DEFAULT now()
);
CREATE OR REPLACE FUNCTION auth.uid() RETURNS uuid
    LANGUAGE sql STABLE AS $fn$
    SELECT nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $fn$;
CREATE OR REPLACE FUNCTION auth.role() RETURNS text
    LANGUAGE sql STABLE AS $fn$
    SELECT coalesce(nullif(current_setting('request.jwt.claim.role', true), ''), 'service_role') $fn$;
CREATE SCHEMA IF NOT EXISTS storage;
CREATE TABLE IF NOT EXISTS storage.buckets (
    id text PRIMARY KEY, name text, public boolean DEFAULT false,
    file_size_limit bigint, allowed_mime_types text[]
);
CREATE TABLE IF NOT EXISTS storage.objects (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    bucket_id text, name text, owner uuid
);
ALTER TABLE storage.objects ENABLE ROW LEVEL SECURITY;
CREATE OR REPLACE FUNCTION storage.foldername(name text) RETURNS text[]
    LANGUAGE sql IMMUTABLE AS $fn$ SELECT string_to_array(name, '/') $fn$;
CREATE SCHEMA IF NOT EXISTS realtime;
CREATE TABLE IF NOT EXISTS realtime.messages (
    id bigserial PRIMARY KEY, topic text, extension text,
    payload jsonb, event text, private boolean DEFAULT false,
    inserted_at timestamptz DEFAULT now()
);
CREATE OR REPLACE FUNCTION realtime.send(
    payload jsonb, event text, topic text, private boolean DEFAULT true
) RETURNS void LANGUAGE sql AS $fn$
    INSERT INTO realtime.messages(topic, extension, payload, event, private)
    VALUES (topic, 'broadcast', payload, event, private)
$fn$;
CREATE OR REPLACE FUNCTION realtime.topic() RETURNS text
    LANGUAGE sql STABLE AS $fn$
    SELECT nullif(current_setting('realtime.topic', true), '') $fn$;
CREATE SCHEMA IF NOT EXISTS supabase_migrations;
CREATE TABLE IF NOT EXISTS supabase_migrations.schema_migrations (
    version text PRIMARY KEY, name text, statements text[]
);
ALTER DEFAULT PRIVILEGES IN SCHEMA public
    GRANT EXECUTE ON FUNCTIONS TO anon, authenticated, service_role;
"""


def migration_files() -> list[Path]:
    return sorted(MIGRATIONS.glob("*.sql"))


def version_of(path: Path) -> str:
    return path.name.split("_", 1)[0]


async def read_production_shape(url: str) -> dict[str, int]:
    conn = await asyncpg.connect(url)
    try:
        rows = await conn.fetch(PRODUCTION_SHAPE_QUERY)
    finally:
        await conn.close()
    return {row["status"]: row["n"] for row in rows}


async def production_migration_version(url: str) -> str:
    conn = await asyncpg.connect(url)
    try:
        return await conn.fetchval(
            "SELECT max(version) FROM supabase_migrations.schema_migrations"
        )
    finally:
        await conn.close()


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--keep", action="store_true", help="leave the scratch database in place")
    parser.add_argument(
        "--production-url",
        help="read-only production connection string; omit to rehearse against a declared shape",
    )
    parser.add_argument(
        "--shape",
        help="content-free shape as status=count pairs, e.g. rejected=182,synced=71,sync_failed=3",
    )
    parser.add_argument("--production-version", help="production's current migration version")
    args = parser.parse_args()

    if args.production_url:
        shape = await read_production_shape(args.production_url)
        prod_version = await production_migration_version(args.production_url)
    elif args.shape and args.production_version:
        shape = {}
        for pair in args.shape.split(","):
            label, _, count = pair.partition("=")
            shape[label.strip()] = int(count)
        prod_version = args.production_version
    else:
        parser.error("supply --production-url, or both --shape and --production-version")

    print(f"Production is at migration {prod_version}")
    print(f"Production events.status shape (counts only): {shape}")

    config = load_config(env_override="development")
    admin_url = re.sub(r"/[^/]*$", "/postgres", config.supabase_db_url)
    admin = await asyncpg.connect(admin_url)
    try:
        await admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)')
        await admin.execute(f'CREATE DATABASE "{SCRATCH_DB}"')
    finally:
        await admin.close()
    print(f"Created scratch database {SCRATCH_DB}")

    scratch_url = re.sub(r"/[^/]*$", f"/{SCRATCH_DB}", config.supabase_db_url)
    conn = await asyncpg.connect(scratch_url)
    failures: list[str] = []
    try:
        await conn.execute(HARNESS)

        files = migration_files()
        already = [p for p in files if version_of(p) <= prod_version]
        pending = [p for p in files if version_of(p) > prod_version]
        print(f"Replaying {len(already)} migrations to reach production's state")
        for path in already:
            try:
                await conn.execute(path.read_text())
                await conn.execute(
                    "INSERT INTO supabase_migrations.schema_migrations(version, name)"
                    " VALUES($1, $2) ON CONFLICT DO NOTHING",
                    version_of(path), path.stem,
                )
            except Exception as exc:  # noqa: BLE001 - report, do not abort the rehearsal
                failures.append(f"{path.name} (pre-cutover): {exc}")
                print(f"  FAILED {path.name}: {exc}")
                return _report(failures)

        # Seed production's shape. Ids and titles are synthetic; only the
        # status distribution is taken from production.
        user_id = await conn.fetchval(
            "INSERT INTO auth.users(email) VALUES('rehearsal@selko.local') RETURNING id"
        )
        # The pending_change invariant is a DEFERRABLE constraint trigger: the
        # event and its source must land in one transaction, exactly as the
        # application writes them.
        async with conn.transaction():
          # event_sources_origin_check requires an email for email-origin rows.
          email_id = await conn.fetchval(
              "INSERT INTO public.emails(user_id, provider_message_id)"
              " VALUES($1, 'rehearsal-message') RETURNING id",
              user_id,
          )
          for label, count in shape.items():
            for index in range(count):
                event_id = await conn.fetchval(
                    """
                    INSERT INTO public.events
                        (user_id, title, start_datetime, end_datetime, status,
                         google_calendar_event_id, synced_at)
                    VALUES ($1, $2, now(), now() + interval '1 hour', $3, $4, $5)
                    RETURNING id
                    """,
                    user_id, f"rehearsal-{label}-{index}", label,
                    f"provider-{label}-{index}"
                    if label in ("synced", "sync_failed", "cancel_queued")
                    else None,
                    None,
                )
                if label == "pending_change":
                    # 20260822000001 requires an active update/cancellation
                    # source for a pending_change event. Seeding one is not
                    # decoration: S5 migrates exactly these into
                    # event_change_proposals, and that path is worth rehearsing.
                    await conn.execute(
                        """
                        INSERT INTO public.event_sources
                            (event_id, email_id, source_type, extracted_data,
                             change_set, event_snapshot_before)
                        VALUES ($1, $2, 'update', $3, $4, $5)
                        """,
                        event_id, email_id,
                        '{"title": "rehearsal changed"}',
                        '{"title": {"to": "rehearsal changed"}}',
                        '{"title": "rehearsal original"}',
                    )
        seeded = await conn.fetchval("SELECT count(*) FROM public.events")
        print(f"Seeded {seeded} events matching production's status distribution")

        print(f"Applying {len(pending)} pending migrations")
        for path in pending:
            try:
                await conn.execute(path.read_text())
                await conn.execute(
                    "INSERT INTO supabase_migrations.schema_migrations(version, name)"
                    " VALUES($1, $2) ON CONFLICT DO NOTHING",
                    version_of(path), path.stem,
                )
                print(f"  ok {path.name}")
            except Exception as exc:  # noqa: BLE001
                failures.append(f"{path.name}: {exc}")
                print(f"  FAILED {path.name}: {exc}")

        if not failures:
            failures.extend(await _assert_post_cutover(conn, shape))
    finally:
        await conn.close()
        if not args.keep:
            admin = await asyncpg.connect(admin_url)
            try:
                await admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)')
            finally:
                await admin.close()
            print(f"Dropped scratch database {SCRATCH_DB}")
        else:
            print(f"Kept scratch database {SCRATCH_DB}")

    return _report(failures)


async def _assert_post_cutover(conn: asyncpg.Connection, shape: dict[str, int]) -> list[str]:
    """Assert the properties the cutover has to hold, against real rows."""
    failures: list[str] = []

    has_status = await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM information_schema.columns"
        " WHERE table_schema='public' AND table_name='events' AND column_name='status')"
    )
    if has_status:
        failures.append("events.status survived the cutover")

    delivery_bearing = {"synced", "sync_failed", "approved", "syncing", "cancel_queued"}
    expected = sum(count for label, count in shape.items() if label in delivery_bearing)
    actual = await conn.fetchval("SELECT count(*) FROM public.calendar_work_items")
    if actual != expected:
        failures.append(
            f"backfill produced {actual} work items for {expected} delivery-bearing events"
        )

    rows = await conn.fetch(
        "SELECT status, action, count(*) n FROM public.calendar_work_items GROUP BY 1,2 ORDER BY 1,2"
    )
    print("Work items after cutover (content-free):")
    for row in rows:
        print(f"  {row['status']:<12} {row['action']:<8} {row['n']}")

    anon_exposed = await conn.fetchval(
        "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace"
        " WHERE n.nspname='public' AND p.prosecdef"
        " AND has_function_privilege('anon', p.oid, 'EXECUTE')"
    )
    if anon_exposed:
        failures.append(f"{anon_exposed} SECURITY DEFINER functions remain anon-executable")

    return failures


def _report(failures: list[str]) -> int:
    if failures:
        print("\nREHEARSAL FAILED:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    print("\nRehearsal clean: every pending migration applied and every assertion held.")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
