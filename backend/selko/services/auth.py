"""The process database for service-side code, and the authentication error.

Sign-in, tokens and sessions live in selko.services.accounts; this module
keeps the two names the services and workers import.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from selko.config import Config
    from selko.db.connection import Database


class AuthenticationError(Exception):
    """Raised when authentication fails."""


def get_service_client(config: Config | None = None) -> Database:
    """The process database (service-wide; the caller scopes by user where rows are owned)."""
    from selko.db.runtime import get_database

    return get_database()
