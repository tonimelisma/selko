"""Bearer-token verification for the MCP endpoint.

Selko does not run its own authorization server. Supabase Auth's OAuth 2.1
server issues the tokens: Claude registers itself as an OAuth client,
sends the user through the consent page at ``/oauth/consent`` on the web app,
and receives an ordinary Supabase access token for that user. The MCP server is
only a resource server.

Clients register themselves (dynamic client registration), as every MCP
client expects, so there is no client allowlist: what grants access is the
user signing in and choosing Allow on the consent page, which names the app.
Two properties keep that safe:

1. **The token is validated by Supabase itself** (``auth.get_user``), exactly as
   the REST API's ``get_current_user`` does, so signing-key rotation and session
   revocation behave identically on both surfaces.
2. **Only OAuth-minted tokens are accepted.** Supabase sets
   ``aud = "authenticated"`` on every token and ignores the RFC 8707
   ``resource`` parameter, so the audience cannot tell a token minted through
   the consent flow from a browser session token. The ``client_id`` claim can:
   Supabase mints it only through the OAuth server. A web-app session token,
   valid for the REST API, is refused here.

Validated tokens are cached for a short interval so one conversation turn that
makes several tool calls costs one Supabase round-trip, not one per call.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
from collections import OrderedDict
from typing import Any, Callable

from jose import jwt
from mcp.server.auth.provider import AccessToken

logger = logging.getLogger(__name__)

# A revoked grant stops working within this many seconds.
_CACHE_TTL_SECONDS = 60.0
_CACHE_MAX_ENTRIES = 256


class SupabaseTokenVerifier:
    """``TokenVerifier`` for Supabase OAuth 2.1 server access tokens."""

    def __init__(
        self,
        validate_with_supabase: Callable[[str], str | None],
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        """
        Args:
            validate_with_supabase: Returns the user id if Supabase accepts the
                token, else ``None``. Blocking; run off the event loop.
            clock: Monotonic clock, injectable for tests.
        """
        self._validate = validate_with_supabase
        self._clock = clock
        self._cache: OrderedDict[str, tuple[float, AccessToken]] = OrderedDict()

    async def verify_token(self, token: str) -> AccessToken | None:
        claims = _unverified_claims(token)
        if claims is None:
            return None
        client_id = claims.get("client_id")
        if not client_id:
            # A browser session token, or a token from some other issuer path.
            # Valid for the REST API, never for MCP.
            logger.info("mcp_auth_rejected reason=no_client_id")
            return None
        key = hashlib.sha256(token.encode()).hexdigest()
        now = self._clock()
        cached = self._cache.get(key)
        if cached is not None and cached[0] > now:
            self._cache.move_to_end(key)
            return cached[1]

        user_id = await asyncio.to_thread(self._validate, token)
        if not user_id or user_id != claims.get("sub"):
            logger.info("mcp_auth_rejected reason=supabase_rejected")
            return None

        scope = claims.get("scope") or ""
        access = AccessToken(
            token=token,
            client_id=str(client_id),
            scopes=[s for s in str(scope).split() if s],
            expires_at=int(claims["exp"]) if claims.get("exp") else None,
            subject=user_id,
            claims={"iss": claims.get("iss")},
        )
        self._cache[key] = (now + _CACHE_TTL_SECONDS, access)
        self._cache.move_to_end(key)
        while len(self._cache) > _CACHE_MAX_ENTRIES:
            self._cache.popitem(last=False)
        return access


def _unverified_claims(token: str) -> dict[str, Any] | None:
    """Read claims to route the check. Never trusted until Supabase agrees."""
    try:
        return jwt.get_unverified_claims(token)
    except Exception:
        return None


def supabase_user_validator(supabase_url: str, supabase_key: str) -> Callable[[str], str | None]:
    """Build the blocking validator used in production."""
    from supabase import create_client

    client = create_client(supabase_url, supabase_key)

    def validate(token: str) -> str | None:
        try:
            response = client.auth.get_user(token)
        except Exception as exc:  # expired, revoked, malformed
            logger.info("mcp_auth_get_user_failed error=%s", type(exc).__name__)
            return None
        if not response or not response.user:
            return None
        return str(response.user.id)

    return validate
