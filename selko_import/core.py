"""The importer: export from Postgres, load into SQLite, verify both sides."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sqlite3
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

COLUMNS: dict[str, list[list[str]]] = json.loads(
    (Path(__file__).parent / "columns.json").read_text(encoding="utf-8")
)

# Postgres expression rendering each type as the text SQLite stores (04 §A.1).
CONVERT: dict[str, str] = {
    "U": "{c}::text",
    "T": "to_char({c} AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"')",
    "D": "to_char({c}, 'YYYY-MM-DD')",
    "H": "{c}::text",
    "X": "{c}::text",
    "I": "{c}::text",
    "B": "CASE WHEN {c} THEN '1' ELSE '0' END",
    "J": "{c}::text",
    "A": "to_json({c})::text",
    "E": "{c}::text",
    "M": "round({c}, 6)::text",
    "R": "{c}::text",
}
INTEGER_KINDS = {"I", "B"}
REAL_KINDS = {"M", "R"}
TIMESTAMP = re.compile(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d\.\d{6}Z")
BATCH = 500
# Not carried: short-lived OAuth CSRF/PKCE state (04 §A.3).
SKIPPED = {"oauth_states", "photos", "scheduled_tasks"}
# Source columns Selko no longer has (Google Photos ingestion, removed
# 2026-11-25). The drift check still pins them: they are the source's.
DROPPED_COLUMNS: dict[str, set[str]] = {"integrations": {"last_photo_sync_at"}}
# Data the removed feature could have left. The import refuses rather than
# silently discard any of it (exit 3, before anything is written).
REMOVED_FEATURE_DATA = {
    "photos rows": 'SELECT count(*) FROM public."photos"',
    "scheduled_tasks rows": 'SELECT count(*) FROM public."scheduled_tasks"',
    "google_photos integrations": "SELECT count(*) FROM public.integrations WHERE provider::text = 'google_photos'",
    "integrations with last_photo_sync_at": "SELECT count(*) FROM public.integrations WHERE last_photo_sync_at IS NOT NULL",
    "google_photos integration recoveries": "SELECT count(*) FROM public.integration_recoveries WHERE provider = 'google_photos'",
    "google_photos event sources": "SELECT count(*) FROM public.event_sources WHERE source_origin = 'google_photos'",
}


def carried_columns(table: str) -> list[list[str]]:
    """The pinned source columns of ``table`` that the target keeps."""
    dropped = DROPPED_COLUMNS.get(table, set())
    return [c for c in COLUMNS[table] if c[0] not in dropped]
ACCOUNT_SOURCE = (
    "SELECT id::text, lower(email), encrypted_password,"
    " to_char(email_confirmed_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'),"
    " to_char(created_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'),"
    " to_char(coalesce(updated_at, created_at) AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"'),"
    " to_char(last_sign_in_at AT TIME ZONE 'UTC', 'YYYY-MM-DD\"T\"HH24:MI:SS.US\"Z\"')"
    " FROM auth.users WHERE deleted_at IS NULL AND encrypted_password IS NOT NULL AND encrypted_password <> ''"
    " ORDER BY id"
)
ACCOUNT_COLUMNS = ["id", "email", "password_hash", "email_confirmed_at", "created_at", "updated_at", "last_sign_in_at"]


class ImportError_(RuntimeError):
    """A refused import, with an exit code (04 §B.10)."""

    def __init__(self, message: str, exit_code: int) -> None:
        super().__init__(message)
        self.exit_code = exit_code


@dataclass
class TableReport:
    table: str
    rows: int
    source: tuple[int, int, int]
    target: tuple[int, int, int]

    @property
    def ok(self) -> bool:
        return self.source == self.target


@dataclass
class Report:
    tables: list[TableReport] = field(default_factory=list)
    accounts: int = 0
    problems: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.problems and all(t.ok for t in self.tables)


# --- hashing (both sides, 04 §A.2) -------------------------------------------


def _cell(value: str | None) -> str:
    return "N" if value is None else f"S{len(value)}:{value}"


def row_hash(cells: list[str | None]) -> int:
    digest = hashlib.sha256("".join(_cell(c) for c in cells).encode("utf-8")).hexdigest()
    return int(digest[:15], 16)


def fold(hashes: list[int]) -> tuple[int, int, int]:
    total, xor = 0, 0
    for h in hashes:
        total = (total + h) % (1 << 64)
        xor ^= h
    return len(hashes), total, xor


def _pg_hash_sql(table: str, columns: list[list[str]]) -> str:
    parts = []
    for name, kind in columns:
        expr = CONVERT[kind].format(c=f'"{name}"')
        parts.append(f"CASE WHEN \"{name}\" IS NULL THEN 'N' ELSE 'S'||length({expr})||':'||{expr} END")
    return (
        "SELECT count(*)::bigint, coalesce((sum(h::numeric) % 18446744073709551616), 0)::text, coalesce(bit_xor(h), 0)::bigint FROM ("
        f" SELECT ('x'||substr(encode(sha256(convert_to({' || '.join(parts)},'UTF8')),'hex'),1,15))::bit(60)::bigint AS h"
        f" FROM public.\"{table}\") t"
    )


def _sqlite_cell(kind: str) -> Callable[[Any], str | None]:
    if kind == "M":
        return lambda v: None if v is None else f"{v:.6f}"
    if kind in INTEGER_KINDS:
        return lambda v: None if v is None else str(int(v))
    if kind == "R":
        return lambda v: None if v is None else repr(v)
    return lambda v: v


# --- the import ---------------------------------------------------------------


async def _export(conn: Any, table: str, columns: list[list[str]]):
    select = ", ".join(CONVERT[k].format(c=f'"{n}"') for n, k in columns)
    async with conn.transaction(isolation="repeatable_read", readonly=True):
        cursor = conn.cursor(f'SELECT {select} FROM public."{table}"', prefetch=BATCH)
        batch = []
        async for record in cursor:
            batch.append(tuple(record))
            if len(batch) >= BATCH:
                yield batch
                batch = []
        if batch:
            yield batch


def _typed(row: tuple, kinds: list[str]) -> tuple:
    out = []
    for value, kind in zip(row, kinds, strict=True):
        if value is None:
            out.append(None)
        elif kind in INTEGER_KINDS:
            out.append(int(value))
        elif kind in REAL_KINDS:
            out.append(float(value))
        else:
            out.append(value)
    return tuple(out)


async def run_import(source_url: str, target: Path, progress: Callable[[str], None] = print) -> Report:
    from selko.db.migrate import migrate

    tmp = target.with_name(target.name + ".importing")
    for leftover in (tmp, Path(str(tmp) + "-wal"), Path(str(tmp) + "-shm")):
        if leftover.exists():
            leftover.unlink()
    migrate(tmp)
    lite = sqlite3.connect(str(tmp), isolation_level=None)
    lite.execute("PRAGMA foreign_keys = OFF")
    triggers = lite.execute("SELECT name, sql FROM sqlite_master WHERE type = 'trigger'").fetchall()
    for name, _sql in triggers:
        lite.execute(f'DROP TRIGGER "{name}"')
    # Rows the migrations seed (global_limits) come from the source instead.
    for (table,) in lite.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall():
        if table in COLUMNS:
            lite.execute(f'DELETE FROM "{table}"')

    report = Report()
    try:
        await _load(source_url, lite, report, progress)
    except BaseException:
        lite.close()
        for leftover in (tmp, Path(str(tmp) + "-wal"), Path(str(tmp) + "-shm")):
            leftover.unlink(missing_ok=True)
        raise
    for _name, sql in triggers:
        lite.execute(sql)
    lite.execute("PRAGMA foreign_keys = ON")
    _structural_checks(lite, report)
    lite.close()
    if not report.ok:
        tmp.unlink(missing_ok=True)
        raise ImportError_("verification failed: " + "; ".join(
            report.problems + [f"{t.table} checksum" for t in report.tables if not t.ok]), 5)
    os.replace(tmp, target)
    return report


async def _load(source_url: str, lite: sqlite3.Connection, report: Report, progress: Callable[[str], None]) -> None:
    import asyncpg  # only the importer needs a Postgres driver

    conn = await asyncpg.connect(source_url, statement_cache_size=0)
    try:
        await conn.execute("SET TIME ZONE 'UTC'")
        # Schema drift fails closed: the pinned map must match the source exactly.
        live = await conn.fetch(
            "SELECT table_name, column_name FROM information_schema.columns WHERE table_schema = 'public'"
            " AND table_name IN (SELECT tablename FROM pg_tables WHERE schemaname = 'public')"
            " ORDER BY table_name, ordinal_position"
        )
        live_map: dict[str, list[str]] = {}
        for r in live:
            live_map.setdefault(r["table_name"], []).append(r["column_name"])
        pinned = {t: [c[0] for c in cols] for t, cols in COLUMNS.items()}
        if live_map != pinned:
            drift = sorted(set(live_map) ^ set(pinned)) or sorted(t for t in pinned if live_map.get(t) != pinned[t])
            raise ImportError_(f"source schema differs from the pinned map in: {drift}", 3)
        left = []
        for what, sql in REMOVED_FEATURE_DATA.items():
            n = int(await conn.fetchval(sql))
            if n:
                left.append(f"{n} {what}")
        if left:
            raise ImportError_(
                "the source holds data of the removed Google Photos ingestion, which the target"
                " cannot keep: " + ", ".join(left) + ". Remove it at the source (or keep the"
                " old deployment) before importing.", 3)

        # Accounts first: users.id references them.
        rows = await conn.fetch(ACCOUNT_SOURCE)
        lite.execute("BEGIN")
        lite.executemany(
            f"INSERT INTO accounts ({', '.join(ACCOUNT_COLUMNS)}) VALUES ({', '.join('?' * len(ACCOUNT_COLUMNS))})",
            [tuple(r) for r in rows],
        )
        lite.execute("COMMIT")
        report.accounts = len(rows)
        progress(f"accounts: {len(rows)}")

        for table in sorted(COLUMNS):
            if table in SKIPPED:
                progress(f"{table}: skipped")
                continue
            columns = carried_columns(table)
            kinds = [k for _, k in columns]
            marks = ", ".join("?" * len(columns))
            names = ", ".join(f'"{n}"' for n, _ in columns)
            count = 0
            lite.execute("BEGIN")
            try:
                async for batch in _export(conn, table, columns):
                    lite.executemany(f'INSERT INTO "{table}" ({names}) VALUES ({marks})',
                                     [_typed(r, kinds) for r in batch])
                    count += len(batch)
            except sqlite3.Error as exc:
                # A source row the target's constraints refuse: nothing is replaced.
                lite.execute("ROLLBACK")
                raise ImportError_(f"{table}: a source row violates the target schema ({exc})", 5) from exc
            lite.execute("COMMIT")

            src = await conn.fetchrow(_pg_hash_sql(table, columns))
            source = (int(src[0]), int(src[1]), int(src[2]))
            cells = [_sqlite_cell(k) for k in kinds]
            hashes = [
                row_hash([cell(v) for cell, v in zip(cells, row, strict=True)])
                for row in lite.execute(f'SELECT {names} FROM "{table}"')
            ]
            target_sum = fold(hashes)
            report.tables.append(TableReport(table, count, source, target_sum))
            progress(f"{table}: {count} rows, checksum {'ok' if source == target_sum else 'MISMATCH'}")
    finally:
        await conn.close()


def _structural_checks(lite: sqlite3.Connection, report: Report) -> None:
    if lite.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
        report.problems.append("integrity_check failed")
    fk = lite.execute("PRAGMA foreign_key_check").fetchall()
    if fk:
        report.problems.append(f"{len(fk)} foreign key violations (first table: {fk[0][0]})")
    for table in COLUMNS:
        if table in SKIPPED:
            continue
        columns = carried_columns(table)
        for name, kind in columns:
            if kind != "T":
                continue
            bad = lite.execute(
                f'SELECT count(*) FROM "{table}" WHERE "{name}" IS NOT NULL AND "{name}" NOT GLOB'
                " '[0-9][0-9][0-9][0-9]-[0-9][0-9]-[0-9][0-9]T[0-9][0-9]:[0-9][0-9]:[0-9][0-9].[0-9][0-9][0-9][0-9][0-9][0-9]Z'"
            ).fetchone()[0]
            if bad:
                report.problems.append(f"{table}.{name}: {bad} timestamps not in the 27-character form")


def import_sync(source_url: str, target: Path, progress: Callable[[str], None] = print) -> Report:
    return asyncio.run(run_import(source_url, target, progress))
