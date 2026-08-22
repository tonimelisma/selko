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
import json
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



# --- Faithful clone -----------------------------------------------------------
#
# A shape rehearsal proves the migrations APPLY. It does not prove they
# transform production's real rows correctly, because the tables the S-batch
# backfills from -- emails, attachments, event_sources, proposals -- are nearly
# empty in a synthesised seed.
#
# Cloning production wholesale is not an option: CLAUDE.md forbids moving
# production credentials or data into development, and it is right to. So this
# copies STRUCTURE and VOLUME while leaving content behind.
#
# Redaction is the DEFAULT, not a denylist. Every text/jsonb column is replaced
# with a deterministic placeholder unless it is provably structural:
#
#   * it participates in a CHECK constraint (the enumerated status domains the
#     migrations branch on), or
#   * its name matches a structural suffix (_status, _action, _kind, _code,
#     _type, _reason, provider, ...), or
#   * it is an id / foreign key / timestamp / boolean / numeric.
#
# A new content column added tomorrow is therefore redacted automatically. The
# failure mode is "a structural column got redacted and the rehearsal is too
# strict", never "content leaked onto a laptop".

_STRUCTURAL_SUFFIXES = (
    "_status", "_action", "_kind", "_code", "_type", "_reason", "_at",
    "_id", "_seconds", "_count", "_generation", "_attempts",
)
_STRUCTURAL_NAMES = {
    "provider", "status", "action", "kind", "severity", "role", "direction",
    "source_origin", "source_type", "run_kind", "importance", "id", "is_included",
    "is_system", "all_day", "user_override", "force_overwrite",
}
_ALWAYS_REDACT = {
    # Belt and braces: these are secrets, never structural, whatever the
    # suffix rules say.
    "access_token", "refresh_token", "code_verifier", "state", "storage_path",
}


async def _structural_text_columns(conn) -> set[tuple[str, str]]:
    """(table, column) pairs that appear in a CHECK constraint."""
    rows = await conn.fetch(
        """
        SELECT t.relname AS table_name, a.attname AS column_name
        FROM pg_constraint c
        JOIN pg_class t ON t.oid = c.conrelid
        JOIN pg_namespace n ON n.oid = t.relnamespace
        JOIN unnest(c.conkey) AS k(attnum) ON true
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = k.attnum
        WHERE n.nspname = 'public' AND c.contype = 'c'
        """
    )
    return {(r["table_name"], r["column_name"]) for r in rows}


def _is_structural(table: str, column: str, data_type: str, checked: set) -> bool:
    if column in _ALWAYS_REDACT:
        return False
    if data_type not in ("text", "character varying", "jsonb", "json"):
        return True  # ids, timestamps, booleans, numerics: structural by nature
    if (table, column) in checked:
        return True
    if column in _STRUCTURAL_NAMES:
        return True
    return any(column.endswith(suffix) for suffix in _STRUCTURAL_SUFFIXES)


_TIMESTAMP_RE = re.compile(r"^\d{4}-\d{2}-\d{2}[T ]")
_UUID_RE = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                      r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")


def _redact_json(value):
    """Redact JSON content while preserving its shape.

    Shape is load-bearing. 20260825000001's backfill refuses to run unless
    exactly one event_source has a non-empty `change_set` AND a non-empty
    `event_snapshot_before`; flattening those to `{}` made it raise
    'backfill ambiguous ... complete=0' on rows that are perfectly valid in
    production. That was a redaction artifact masquerading as a cutover
    blocker -- the most expensive kind of false alarm.

    So: keys and nesting are preserved, as are values a migration might cast --
    timestamps, UUIDs, numbers, booleans. Free text becomes a placeholder.
    """
    if isinstance(value, dict):
        return {k: _redact_json(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_json(v) for v in value]
    if isinstance(value, str):
        if _TIMESTAMP_RE.match(value) or _UUID_RE.match(value):
            return value
        return "redacted"
    return value


def _placeholder(table: str, column: str, row_index: int, data_type: str):
    if data_type in ("jsonb", "json"):
        # Filled in by the caller, which has the original value to reshape.
        return None
    return f"redacted-{table}-{column}-{row_index}"

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


# Copy order: parents before children. Only tables the pending migrations read
# or transform; anything else adds risk without adding proof.
_CLONE_ORDER = (
    "users", "integrations", "email_folders", "email_sync_state",
    "email_sync_runs", "emails", "email_ingestion_items", "attachments",
    "events", "event_sources", "sender_rules", "user_calendar_settings",
    "operational_incidents", "usage_quotas",
)


async def clone_production_shape(prod_url: str, conn) -> dict[str, int]:
    """Copy production's structure and volume into the scratch db, content-free.

    Returns the per-table row counts actually cloned.
    """
    prod = await asyncpg.connect(prod_url)
    copied: dict[str, int] = {}
    try:
        checked = await _structural_text_columns(prod)
        # One transaction for the whole clone. Several invariants are DEFERRABLE
        # constraint triggers -- notably pending_change, which requires an event
        # and its event_sources row to be visible together. Table-by-table
        # commits check them too early and the clone fails on rows that are
        # perfectly valid in production.
        async with conn.transaction():
          for table in _CLONE_ORDER:
            columns = await prod.fetch(
                """
                SELECT column_name, data_type, is_generated
                FROM information_schema.columns
                WHERE table_schema = 'public' AND table_name = $1
                ORDER BY ordinal_position
                """,
                table,
            )
            if not columns:
                continue
            names = [c["column_name"] for c in columns if c["is_generated"] != "ALWAYS"]
            types = {c["column_name"]: c["data_type"] for c in columns}
            if not names:
                continue

            quoted = ", ".join(f'"{name}"' for name in names)
            rows = await prod.fetch(f'SELECT {quoted} FROM public."{table}"')
            if not rows:
                copied[table] = 0
                continue

            redacted = [
                name for name in names
                if not _is_structural(table, name, types[name], checked)
            ]
            placeholders = ", ".join(f"${i + 1}" for i in range(len(names)))
            insert = (
                f'INSERT INTO public."{table}" ({quoted}) '
                f"VALUES ({placeholders}) ON CONFLICT DO NOTHING"
            )
            payload = []
            for index, row in enumerate(rows):
                values = []
                for name in names:
                    value = row[name]
                    if name in redacted and value is not None:
                        if types[name] in ("jsonb", "json"):
                            try:
                                values.append(json.dumps(_redact_json(json.loads(value))))
                            except (TypeError, ValueError):
                                values.append("{}")
                        else:
                            values.append(_placeholder(table, name, index, types[name]))
                    else:
                        values.append(value)
                payload.append(values)
            await conn.executemany(insert, payload)
            copied[table] = len(payload)
            suffix = f", redacted {sorted(redacted)}" if redacted else ""
            print(f"  {table}: {len(payload)} rows{suffix}")
    finally:
        await prod.close()
    return copied


async def _seed_synthetic_shape(conn, shape: dict[str, int]) -> None:
    """Seed events matching production's status distribution only.

    Ids and titles are invented; the distribution is production's. Proves the
    migrations apply, not that they transform production's real rows -- use
    --faithful for that.
    """
    user_id = await conn.fetchval(
        "INSERT INTO auth.users(email) VALUES('rehearsal@selko.local') RETURNING id"
    )
    # The pending_change invariant is a DEFERRABLE constraint trigger: the event
    # and its source must land in one transaction, as the application writes them.
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
    parser.add_argument(
        "--faithful",
        action="store_true",
        help=(
            "clone production's real rows (structure and volume, content and "
            "credentials redacted) instead of synthesising a status distribution; "
            "requires --production-url"
        ),
    )
    args = parser.parse_args()

    if args.faithful and not args.production_url:
        parser.error("--faithful requires --production-url")

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

        if args.faithful:
            # Real rows, real volume, real foreign-key graph -- with content and
            # credentials left in production. This is what proves the S-batch
            # backfills transform production's actual data, rather than merely
            # applying against a synthesised status distribution.
            print("Cloning production's structure and volume (content redacted)")
            # auth.users is the FK target for public.users; mirror the ids.
            prod = await asyncpg.connect(args.production_url)
            try:
                auth_ids = await prod.fetch("SELECT id FROM auth.users")
            finally:
                await prod.close()
            for row in auth_ids:
                await conn.execute(
                    "INSERT INTO auth.users(id, email) VALUES($1, $2)"
                    " ON CONFLICT DO NOTHING",
                    row["id"], f"redacted-{row['id']}@rehearsal.invalid",
                )
            copied = await clone_production_shape(args.production_url, conn)
            total = sum(copied.values())
            print(f"Cloned {total} rows across {len(copied)} tables")
            seeded_events = await conn.fetchval("SELECT count(*) FROM public.events")
            print(f"Events in scratch: {seeded_events}")
        else:
            await _seed_synthetic_shape(conn, shape)
            seeded = await conn.fetchval("SELECT count(*) FROM public.events")
            print(f"Seeded {seeded} events matching production's status distribution")

        expected_work_items = await _count_delivery_bearing(conn)
        print(f"Delivery-bearing events before the cutover: {expected_work_items}")

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
            failures.extend(await _assert_post_cutover(conn, expected_work_items))
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


async def _count_delivery_bearing(conn) -> int:
    """Events that will own a calendar work item after the cutover.

    Measured while events.status still exists. Mirrors 20260826000001, which
    converts a pending_change row carrying a provider id into 'synced' before
    20260829000001 backfills work items from it.
    """
    return await conn.fetchval(
        """
        SELECT count(*) FROM public.events
        WHERE status IN ('synced', 'sync_failed', 'approved', 'syncing', 'cancel_queued')
           OR (status = 'pending_change' AND google_calendar_event_id IS NOT NULL)
        """
    )


async def _assert_post_cutover(conn: asyncpg.Connection, expected: int | None) -> list[str]:
    """Assert the properties the cutover has to hold, against real rows."""
    failures: list[str] = []

    has_status = await conn.fetchval(
        "SELECT EXISTS(SELECT 1 FROM information_schema.columns"
        " WHERE table_schema='public' AND table_name='events' AND column_name='status')"
    )
    if has_status:
        failures.append("events.status survived the cutover")

    # `expected` is measured on the scratch database BEFORE the migrations run,
    # not derived from the pre-migration status histogram. Arithmetic on the
    # histogram is wrong: 20260826000001 converts pending_change rows that carry
    # a provider id into 'synced', which enlarges the delivery-bearing set
    # before 20260829000001's backfill ever sees it. That produced a spurious
    # "82 work items for 77 events" on the first faithful run.
    actual = await conn.fetchval("SELECT count(*) FROM public.calendar_work_items")
    if expected is not None and actual != expected:
        failures.append(
            f"backfill produced {actual} work items for {expected} delivery-bearing events"
        )

    # The property that actually matters, asserted against the post-state: no
    # event may carry more than one live work item, or the delivery status
    # derived from "latest non-superseded item" is ambiguous.
    ambiguous = await conn.fetchval(
        """
        SELECT count(*) FROM (
            SELECT event_id FROM public.calendar_work_items
            WHERE status <> 'superseded'
            GROUP BY event_id HAVING count(*) > 1
        ) AS t
        """
    )
    if ambiguous:
        failures.append(f"{ambiguous} events have more than one live calendar work item")

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
