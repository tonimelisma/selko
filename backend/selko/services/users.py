"""User management service for Selko.

Operator and test-fixture account administration over Selko's own
``accounts`` table (docs/specs/sqlite-single-process/03-api-auth-web.md §B.9).
Passwords are bcrypt-hashed by ``selko.services.accounts``; the profile row in
``users`` is created with the account, in the same transaction.
"""

import logging

from selko.config import Config
from selko.db import accounts as account_rows
from selko.db.connection import Database
from selko.db.errors import DbError
from selko.db.runtime import get_database
from selko.services import accounts

logger = logging.getLogger(__name__)


class UserManagementError(Exception):
    """Raised when user management operations fail."""

    pass


def get_admin_client(config: Config) -> Database:
    """The process database, for account administration.

    Args:
        config: Configuration object (kept for callers; the database path
            comes from the process runtime).

    Returns:
        The process database.
    """
    return get_database()


def _public(account: dict) -> dict:
    return {"id": str(account["id"]), "email": account["email"]}


def create_user(
    config: Config,
    email: str,
    password: str,
    display_name: str = None,
    auto_confirm: bool = False,
) -> dict:
    """Create a new account and its ``users`` profile row.

    The profile's display name is the email's local part, as GoTrue's
    ``handle_new_user`` trigger set it (``display_name`` was never applied
    and still is not). Without ``auto_confirm`` the account is stored
    unconfirmed (``email_confirmed_at`` NULL).

    Args:
        config: Configuration object.
        email: User's email address.
        password: User's password (bcrypt-hashed before it is stored).
        display_name: Unused; kept for callers.
        auto_confirm: Whether the account is confirmed at creation.

    Returns:
        Dict with 'id' and 'email' of the created user.

    Raises:
        UserManagementError: If user creation fails (invalid input, or an
            account with that email already exists).
    """
    db = get_admin_client(config)

    try:
        normalized = accounts.validate_email(email)
        password_hash = accounts.hash_password(password)
        account = account_rows.create_account(
            db, normalized, password_hash, confirmed=auto_confirm
        )
    except accounts.AuthError as e:
        raise UserManagementError(f"Failed to create user: {e}") from e
    except account_rows.AccountExists as e:
        raise UserManagementError(
            f"Failed to create user: A user with this email address has already been registered ({email})"
        ) from e
    except DbError as e:
        raise UserManagementError(f"Failed to create user: {e}") from e

    if auto_confirm:
        logger.debug(f"Auto-confirmed user {normalized}")
    else:
        logger.info(f"User {normalized} created unconfirmed")
    return _public(account)


def list_users(config: Config) -> list[dict]:
    """List all users.

    Args:
        config: Configuration object.

    Returns:
        List of dicts with 'id' and 'email' for each user.
    """
    try:
        return [_public(a) for a in account_rows.list_accounts(get_admin_client(config))]
    except DbError as e:
        raise UserManagementError(f"Failed to list users: {e}") from e


def delete_user(config: Config, user_id: str) -> bool:
    """Delete a user by ID; the profile and every owned row cascade.

    Args:
        config: Configuration object.
        user_id: UUID of the user to delete.

    Returns:
        True if deletion succeeded.

    Raises:
        UserManagementError: If the user does not exist or deletion fails.
    """
    try:
        deleted = account_rows.delete_account(get_admin_client(config), str(user_id))
    except DbError as e:
        raise UserManagementError(f"Failed to delete user: {e}") from e
    if not deleted:
        raise UserManagementError(f"Failed to delete user: User not found: {user_id}")
    logger.info(f"Deleted user {user_id}")
    return True


def get_user(config: Config, user_id: str) -> dict:
    """Get a user by ID.

    Args:
        config: Configuration object.
        user_id: UUID of the user.

    Returns:
        Dict with user info.

    Raises:
        UserManagementError: If user not found or fetch fails.
    """
    try:
        account = account_rows.get_account(get_admin_client(config), str(user_id))
    except DbError as e:
        raise UserManagementError(f"Failed to get user: {e}") from e
    if account is None:
        raise UserManagementError(f"User not found: {user_id}")
    return _public(account)
