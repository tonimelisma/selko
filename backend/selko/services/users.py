"""User management service for Selko.

Provides admin operations for user CRUD using the service role key.
These operations bypass RLS for administrative purposes.
"""

from supabase import Client, create_client

from selko.config import Config


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
) -> dict:
    """Create a new user in auth.users.

    The database trigger automatically creates the public.users profile.

    Args:
        config: Configuration object.
        email: User's email address.
        password: User's password.
        display_name: Optional display name (defaults to email prefix).

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
                "email_confirm": True,  # Auto-confirm for dev
            }
        )

        if not response.user:
            raise UserManagementError(f"Failed to create user: {email}")

        return {
            "id": str(response.user.id),
            "email": response.user.email,
        }

    except Exception as e:
        raise UserManagementError(f"Failed to create user: {e}") from e


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
    except Exception as e:
        raise UserManagementError(f"Failed to list users: {e}") from e


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
        return True
    except Exception as e:
        raise UserManagementError(f"Failed to delete user: {e}") from e


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
    except Exception as e:
        raise UserManagementError(f"Failed to get user: {e}") from e
