"""Selko's data layer: one SQLite file, written by one process.

`selko.db` replaces Postgres, PostgREST and Supabase Auth. Every read and write
the services make goes through functions in this package; nothing else opens
the database.
"""

from selko.db.connection import Database, Transaction
from selko.db.migrate import MigrationError, migrate

__all__ = ["Database", "MigrationError", "Transaction", "migrate"]
