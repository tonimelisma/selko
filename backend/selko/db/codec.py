"""How Python values are stored in Selko's SQLite database, and read back.

One implementation for the whole data layer (the schema's conventions,
`migrations/0001_initial.sql`):

- ids: TEXT, canonical lowercase UUID
- timestamps: TEXT, UTC, ``YYYY-MM-DDTHH:MM:SS.ffffffZ`` -- fixed width, so
  comparing the text compares the time, and indexes order correctly
- booleans: INTEGER 0/1
- JSON and arrays: TEXT holding canonical JSON

Which columns are booleans or JSON is read from the schema itself (their CHECK
constraints), so the codec cannot drift from the tables.
"""

from __future__ import annotations

import json
import re
import sqlite3
import uuid
from datetime import date, datetime, time, timezone
from typing import Any

TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S.%fZ"


def new_id() -> str:
    """A new row id."""
    return str(uuid.uuid4())


def to_id(value: Any) -> str | None:
    """Canonical text for an id given as str or UUID; None stays None."""
    if value is None:
        return None
    return str(uuid.UUID(str(value)))


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def to_timestamp(value: datetime | str | None) -> str | None:
    """Store a moment as UTC text. Naive datetimes are refused: their zone is unknown."""
    if value is None:
        return None
    if isinstance(value, str):
        value = parse_timestamp(value)
    if value.tzinfo is None:
        raise ValueError(f"naive datetime has no zone: {value!r}")
    return value.astimezone(timezone.utc).strftime(TIMESTAMP_FORMAT)


def now_text() -> str:
    return to_timestamp(utc_now())  # type: ignore[return-value]


def parse_timestamp(value: str) -> datetime:
    """Read a stored or ISO 8601 timestamp (with ``Z`` or an offset) as an aware datetime."""
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00") if value.endswith("Z") else value)
    if parsed.tzinfo is None:
        raise ValueError(f"timestamp has no zone: {value!r}")
    return parsed


def to_date(value: date | str | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        raise ValueError("a datetime is not a date")
    return value.isoformat() if isinstance(value, date) else date.fromisoformat(value).isoformat()


def to_time(value: time | str | None) -> str | None:
    if value is None:
        return None
    return value.strftime("%H:%M:%S") if isinstance(value, time) else time.fromisoformat(value).strftime("%H:%M:%S")


def to_json(value: Any) -> str | None:
    """Canonical JSON: sorted keys, no spaces, UTF-8 kept. Two equal values store equal text."""
    if value is None:
        return None
    return json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def to_bool(value: Any) -> int | None:
    if value is None:
        return None
    if not isinstance(value, bool):
        raise TypeError(f"expected bool, got {type(value).__name__}")
    return int(value)


# ---------------------------------------------------------------------------
# Reading rows back
# ---------------------------------------------------------------------------

_BOOL_CHECK = re.compile(r"CHECK \((\w+) IN \(0,1\)\)")
_JSON_COLUMN = re.compile(r"json_valid\((\w+)\)")


class Schema:
    """Per-table column kinds, read from the live database's own CREATE TABLE text."""

    def __init__(self, conn: sqlite3.Connection) -> None:
        self.bool_columns: dict[str, frozenset[str]] = {}
        self.json_columns: dict[str, frozenset[str]] = {}
        for name, sql in conn.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'table' AND sql IS NOT NULL"
        ):
            self.bool_columns[name] = frozenset(_BOOL_CHECK.findall(sql))
            self.json_columns[name] = frozenset(_JSON_COLUMN.findall(sql))

    def decode(self, table: str, row: sqlite3.Row | dict[str, Any] | None) -> dict[str, Any] | None:
        """A row as the dict the services expect: booleans as bool, JSON parsed."""
        if row is None:
            return None
        out = dict(row)
        for column in self.bool_columns.get(table, ()):
            if column in out and out[column] is not None:
                out[column] = bool(out[column])
        for column in self.json_columns.get(table, ()):
            if column in out and isinstance(out[column], str):
                out[column] = json.loads(out[column])
        return out

    def encode(self, table: str, values: dict[str, Any]) -> dict[str, Any]:
        """Column values ready to bind: booleans to 0/1, JSON columns to canonical text."""
        out = dict(values)
        for column in self.bool_columns.get(table, ()):
            if column in out and out[column] is not None:
                out[column] = to_bool(out[column])
        for column in self.json_columns.get(table, ()):
            if column in out and out[column] is not None and not isinstance(out[column], str):
                out[column] = to_json(out[column])
        for column, value in out.items():
            if isinstance(value, datetime):
                out[column] = to_timestamp(value)
            elif isinstance(value, uuid.UUID):
                out[column] = str(value)
        return out
