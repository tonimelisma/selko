"""Authentication service for Selko.

Provides user authentication using Supabase sign_in_with_password.
All operations use the publishable key with RLS enforcement.
"""

import logging

from supabase import AuthApiError, Client, create_client

from selko.config import Config

logger = logging.getLogger(__name__)


class AuthenticationError(Exception):
    """Raised when authentication fails."""

    pass


def get_authenticated_client(config: Config) -> Client:
    """Sign in as configured test user and return an RLS-enforced client.

    Uses TEST_USER_EMAIL and TEST_USER_PASSWORD from config.

    Args:
        config: Configuration object with Supabase and user credentials.

    Returns:
        Authenticated Supabase client with RLS enforced.

    Raises:
        AuthenticationError: If sign-in fails or credentials not configured.
    """
    if not config.test_user_email or not config.test_user_password:
        raise AuthenticationError(
            "TEST_USER_EMAIL and TEST_USER_PASSWORD must be configured in .env"
        )

    client = create_client(config.supabase_url, config.supabase_key)

    try:
        response = client.auth.sign_in_with_password(
            {
                "email": config.test_user_email,
                "password": config.test_user_password,
            }
        )

        if not response.user:
            raise AuthenticationError(
                f"Failed to sign in as {config.test_user_email}"
            )

        logger.info(f"Signed in as {response.user.email}")
        return client

    except AuthApiError as e:
        raise AuthenticationError(f"Sign-in failed: {e.message}") from e


def get_current_user_id(client: Client) -> str:
    """Get the authenticated user's ID from the session.

    Args:
        client: Authenticated Supabase client.

    Returns:
        User ID (UUID) as string.

    Raises:
        AuthenticationError: If no user is signed in.
    """
    session = client.auth.get_session()
    if not session or not session.user:
        raise AuthenticationError("No user signed in")
    return session.user.id


def get_service_client(config: Config) -> Client:
    """Get a Supabase client with service role privileges.

    Used by background workers to bypass RLS and perform admin operations.

    Args:
        config: Configuration object with Supabase URL and service role key.

    Returns:
        Supabase client with service role access (bypasses RLS).

    Raises:
        AuthenticationError: If service role key not configured.
    """
    if not config.supabase_service_role_key:
        raise AuthenticationError(
            "SUPABASE_SERVICE_ROLE_KEY must be configured for background workers"
        )

    # Service role client bypasses RLS and doesn't need session management
    client = create_client(
        config.supabase_url,
        config.supabase_service_role_key,
    )

    logger.debug("Created service role client (bypasses RLS)")
    return client
