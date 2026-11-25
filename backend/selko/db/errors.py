"""Typed data-layer errors: what the Postgres functions raised, by meaning.

Callers catch these instead of matching PostgREST error codes and message
substrings (docs/specs/sqlite-single-process/02-data-layer.md §1.3).
"""

from __future__ import annotations

import sqlite3


class DbError(Exception):
    """Any data-layer failure."""


class NotFound(DbError):
    pass


class NotOwned(DbError):
    """The row exists but belongs to someone else (Postgres 42501)."""


class InvalidArgument(DbError):
    """Bad input to a data-layer function (Postgres 22023 / plain RAISE)."""


class StaleProposal(DbError):
    """A proposal changed between reading and deciding (Postgres 40001)."""


class ProposalStateError(DbError):
    pass


class InvariantViolation(DbError):
    """A cross-row rule failed (Postgres 23514)."""


class EmailActivelyLeased(DbError):
    pass


class UniqueViolation(DbError):
    pass


class CheckViolation(DbError):
    pass


class ForeignKeyViolation(DbError):
    pass


class NotNullViolation(DbError):
    pass


class DbBusy(DbError):
    """The database stayed locked past busy_timeout: the one transient failure."""


def translate(exc: sqlite3.Error) -> DbError:
    """Map a sqlite3 error to its typed equivalent, keeping the message."""
    message = str(exc)
    if isinstance(exc, sqlite3.IntegrityError):
        if message.startswith("UNIQUE constraint failed"):
            return UniqueViolation(message)
        if message.startswith("FOREIGN KEY constraint failed"):
            return ForeignKeyViolation(message)
        if message.startswith("CHECK constraint failed"):
            return CheckViolation(message)
        if message.startswith("NOT NULL constraint failed"):
            return NotNullViolation(message)
        # RAISE(ABORT, ...) from a trigger: the cross-row rules.
        return InvariantViolation(message)
    if isinstance(exc, sqlite3.OperationalError) and "database is locked" in message:
        return DbBusy(message)
    return DbError(message)
