"""Apply Selko's SQLite migrations at startup, before anything is served.

Files in ``selko/db/migrations/`` named ``NNNN_description.sql`` are applied in
order, each in its own transaction, and recorded with their SHA-256 in
``schema_migrations``. Rules:

- An applied migration whose file has changed since is refused: the database
  and the code would disagree about the schema, silently.
- Before the first pending migration, the database is copied with
  ``VACUUM INTO`` to ``<data dir>/backups/pre-<NNNN>.db`` -- a consistent copy
  to go back to if the new version has to be rolled back.
- A migration that fails rolls back whole; the error propagates and the process
  must not start serving (the previous image keeps running).
"""

from __future__ import annotations

import hashlib
import logging
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path

from selko.db.codec import now_text

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_NAME = re.compile(r"^(\d{4})_[a-z0-9_]+\.sql$")
_BACKUP = re.compile(r"^pre-(\d{4})\.db$")
# Each migration first copies the whole database (VACUUM INTO), ~300 MB in
# production, and nothing removed the old copies. Keep the newest few: the one
# taken before the latest migration, and one before that.
BACKUPS_KEPT = 2


class MigrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    sql: str
    sha256: str


def available(directory: Path = MIGRATIONS_DIR) -> list[Migration]:
    found: list[Migration] = []
    for path in sorted(directory.glob("*.sql")):
        match = _NAME.match(path.name)
        if not match:
            raise MigrationError(f"migration file name must be NNNN_name.sql: {path.name}")
        sql = path.read_text(encoding="utf-8")
        found.append(
            Migration(int(match.group(1)), path.name, sql, hashlib.sha256(sql.encode()).hexdigest())
        )
    versions = [m.version for m in found]
    if versions != list(range(1, len(found) + 1)):
        raise MigrationError(f"migration versions must be 1..n with no gaps: {versions}")
    return found


def _ensure_ledger(conn: sqlite3.Connection) -> None:
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version INTEGER PRIMARY KEY, name TEXT NOT NULL, sha256 TEXT NOT NULL,"
        " applied_at TEXT NOT NULL) STRICT"
    )


def applied(conn: sqlite3.Connection) -> dict[int, tuple[str, str]]:
    _ensure_ledger(conn)
    return {v: (n, h) for v, n, h in conn.execute("SELECT version, name, sha256 FROM schema_migrations")}


def _register_trigger_functions(conn: sqlite3.Connection) -> None:
    """The functions the triggers call, for writes a migration makes.

    Migrations run before anything subscribes, so live hints and work signals
    have no audience; the timestamp is fixed for the whole run.
    """
    from datetime import timedelta

    from selko.db.codec import to_timestamp, utc_now

    started = utc_now()
    conn.create_function("selko_now", 0, lambda: to_timestamp(started))
    conn.create_function("selko_ts", 1, lambda s: to_timestamp(started + timedelta(seconds=s)))
    conn.create_function("selko_emit_live", 3, lambda *_: None)
    conn.create_function("selko_emit_work", 1, lambda *_: None)
    conn.create_function("selko_touch_event", 1, lambda *_: None)


def migrate(
    db_path: Path | str,
    directory: Path = MIGRATIONS_DIR,
    backup_dir: Path | None = None,
) -> list[str]:
    """Bring the database at ``db_path`` up to date. Returns the names applied."""
    db_path = Path(db_path)
    migrations = available(directory)
    conn = sqlite3.connect(str(db_path), isolation_level=None)
    try:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        _register_trigger_functions(conn)
        done = applied(conn)
        for version, (name, sha) in done.items():
            match = next((m for m in migrations if m.version == version), None)
            if match is None:
                raise MigrationError(f"database has migration {name} that this build does not know")
            if match.sha256 != sha:
                raise MigrationError(f"applied migration {name} has changed since it was applied")
        pending = [m for m in migrations if m.version not in done]
        if not pending:
            return []
        if done:
            backup_dir = backup_dir or db_path.parent / "backups"
            backup_dir.mkdir(parents=True, exist_ok=True)
            target = backup_dir / f"pre-{pending[0].version:04d}.db"
            if target.exists():
                target.unlink()
            conn.execute("VACUUM INTO ?", (str(target),))
            logger.info("migrate: copied the database to %s before migrating", target)
        names: list[str] = []
        for migration in pending:
            try:
                # executescript commits any open transaction before it starts,
                # never after: the script opens the transaction and leaves it
                # open, so the foreign keys are checked before anything commits.
                conn.executescript(
                    "BEGIN IMMEDIATE;\n"
                    + migration.sql
                    + "\nINSERT INTO schema_migrations (version, name, sha256, applied_at) VALUES "
                    + f"({migration.version}, '{migration.name}', '{migration.sha256}', '{now_text()}');\n"
                    + f"PRAGMA user_version = {migration.version};\n"
                )
                problems = conn.execute("PRAGMA foreign_key_check").fetchall()
                if problems:
                    raise MigrationError(f"{migration.name} left foreign key violations: {problems[:5]}")
                conn.execute("COMMIT")
            except (sqlite3.Error, MigrationError) as exc:
                if conn.in_transaction:
                    conn.execute("ROLLBACK")
                if isinstance(exc, MigrationError):
                    raise
                raise MigrationError(f"{migration.name} failed and was rolled back: {exc}") from exc
            logger.info("migrate: applied %s", migration.name)
            names.append(migration.name)
        if done:
            prune_backups(backup_dir)
        return names
    finally:
        conn.close()


def prune_backups(backup_dir: Path, keep: int = BACKUPS_KEPT) -> list[str]:
    """Remove all but the ``keep`` newest ``pre-NNNN.db`` copies; returns the names removed.

    Runs only after every pending migration applied, so the copy just taken is
    always kept. Files of any other name are never touched.
    """
    copies = sorted(
        (int(m.group(1)), path)
        for path in backup_dir.iterdir()
        if path.is_file() and (m := _BACKUP.match(path.name))
    )
    removed = []
    for _version, path in copies[: max(len(copies) - keep, 0)]:
        path.unlink()
        logger.info("migrate: removed the old backup %s", path.name)
        removed.append(path.name)
    return removed


def current_version(conn: sqlite3.Connection) -> int:
    return int(conn.execute("PRAGMA user_version").fetchone()[0])
