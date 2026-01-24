"""User management service for Selko.

Provides admin operations for user CRUD using the service role key.
These operations bypass RLS for administrative purposes.
"""

import logging

from supabase import AuthApiError, Client, create_client

from selko.config import Config

logger = logging.getLogger(__name__)


class UserManagementError(Exception):
    """Raised when user management operations fail."""

    pass


def get_admin_client(config: Config) -> Client:
    """Get a Supabase client with service role key for admin operations.

    Args:
        config: Configuration object with Supabase credentials.

    Returns:
        Supabase client with admin privileges.

    Raises:
        UserManagementError: If service role key is not configured.
    """
    if not config.supabase_service_role_key:
        raise UserManagementError(
            "SUPABASE_SERVICE_ROLE_KEY must be configured for admin operations"
        )

    return create_client(config.supabase_url, config.supabase_service_role_key)


def create_user(
    config: Config,
    email: str,
    password: str,
    display_name: str = None,
    auto_confirm: bool = True,
) -> dict:
    """Create a new user in auth.users.

    The database trigger automatically creates the public.users profile.
    By default, users are auto-confirmed for testing purposes.

    Args:
        config: Configuration object.
        email: User's email address.
        password: User's password.
        display_name: Optional display name (defaults to email prefix).
        auto_confirm: Whether to auto-confirm the user (default: True).

    Returns:
        Dict with 'id' and 'email' of the created user.

    Raises:
        UserManagementError: If user creation fails.
    """
    client = get_admin_client(config)

    try:
        response = client.auth.admin.create_user(
            {
                "email": email,
                "password": password,
                "email_confirm": auto_confirm,
            }
        )

        if not response.user:
            raise UserManagementError(f"Failed to create user: {email}")

        if auto_confirm:
            logger.debug(f"Auto-confirmed user {email}")
        else:
            logger.info(f"User {email} created - confirmation email sent")

        return {
            "id": str(response.user.id),
            "email": response.user.email,
        }

    except AuthApiError as e:
        raise UserManagementError(f"Failed to create user: {e.message}") from e


def list_users(config: Config) -> list[dict]:
    """List all users.

    Args:
        config: Configuration object.

    Returns:
        List of dicts with 'id' and 'email' for each user.
    """
    client = get_admin_client(config)

    try:
        response = client.auth.admin.list_users()
        return [
            {"id": str(user.id), "email": user.email}
            for user in response
        ]
    except AuthApiError as e:
        raise UserManagementError(f"Failed to list users: {e.message}") from e


def delete_user(config: Config, user_id: str) -> bool:
    """Delete a user by ID.

    Args:
        config: Configuration object.
        user_id: UUID of the user to delete.

    Returns:
        True if deletion succeeded.

    Raises:
        UserManagementError: If deletion fails.
    """
    client = get_admin_client(config)

    try:
        client.auth.admin.delete_user(user_id)
        logger.info(f"Deleted user {user_id}")
        return True
    except AuthApiError as e:
        raise UserManagementError(f"Failed to delete user: {e.message}") from e


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
    client = get_admin_client(config)

    try:
        response = client.auth.admin.get_user_by_id(user_id)
        if not response.user:
            raise UserManagementError(f"User not found: {user_id}")
        return {
            "id": str(response.user.id),
            "email": response.user.email,
        }
    except AuthApiError as e:
        raise UserManagementError(f"Failed to get user: {e.message}") from e
