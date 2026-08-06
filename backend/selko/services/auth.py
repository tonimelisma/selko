"""Authentication service for Selko.

Provides user authentication using Supabase sign_in_with_password.
All operations use the publishable key with RLS enforcement.
"""

import logging

import httpx
from supabase import AuthApiError, Client, create_client
from supabase.lib.client_options import SyncClientOptions

from selko.config import Config
from selko.services.egress import SUPABASE, operation_from_url, record_egress

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


def _record_supabase_egress(response: "httpx.Response") -> None:
    """Attribute one PostgREST/RPC round trip to the egress meter.

    Attached as an httpx response hook rather than wrapped around individual
    call sites: every query and RPC in the codebase shares this one client, so
    the hook cannot be bypassed and cannot drift as new queries are added.

    Must never raise — an accounting failure breaking a database call would be
    a far worse bug than a missing counter.
    """
    try:
        request = response.request
        request_bytes = _header_bytes(request.headers) + int(
            request.headers.get("content-length") or 0
        )
        response_bytes = _header_bytes(response.headers) + int(
            response.headers.get("content-length") or 0
        )
        record_egress(
            SUPABASE,
            operation_from_url(request.method, str(request.url)),
            request_bytes=request_bytes,
            response_bytes=response_bytes,
        )
    except Exception:  # pragma: no cover - defensive
        logger.debug("Egress accounting failed for a Supabase call", exc_info=True)


def _header_bytes(headers) -> int:
    """Approximate on-the-wire header size.

    Headers are a real cost here, not a rounding error: the service-role JWT is
    sent on every request, and the traffic this meter exists to explain is a
    high-rate stream of small polling calls where headers dominate the body.
    """
    return sum(len(name) + len(value) + 4 for name, value in headers.items())


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

    # postgrest-py enables HTTP/2 by default. The synchronous HTTP/2 transport
    # fails under concurrent production worker threads with EAGAIN reads and
    # terminated streams. HTTP/1.1 uses independent pooled connections and is
    # the stable transport for this shared, thread-safe service client.
    http_client = httpx.Client(
        http2=False,
        timeout=120,
        event_hooks={"response": [_record_supabase_egress]},
    )
    client = create_client(
        config.supabase_url,
        config.supabase_service_role_key,
        options=SyncClientOptions(httpx_client=http_client),
    )

    logger.debug("Created service role client (bypasses RLS)")
    return client
