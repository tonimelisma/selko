"""Rate limiting: one limiter, keyed by verified user or by client address.

The key used to come from a JWT decoded *without* checking its signature, so a
caller could pick whose budget to spend (03-api-auth-web.md §B.1). Now a
token counts only if it verifies; anything else is keyed by address.
"""

from __future__ import annotations

import os

from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address


def get_user_id_or_ip(request: Request) -> str:
    auth_header = request.headers.get("Authorization", "")
    keys = getattr(request.app.state, "token_keys", None)
    if auth_header.startswith("Bearer ") and keys is not None:
        from selko.services.accounts import AuthError, verify_access_token

        try:
            return f"user:{verify_access_token(keys, auth_header[7:]).user_id}"
        except AuthError:
            pass
    return f"ip:{get_remote_address(request)}"


def client_ip(request: Request) -> str:
    return f"ip:{get_remote_address(request)}"


limiter = Limiter(key_func=get_user_id_or_ip, default_limits=["60/minute"])


class Window:
    """A per-key sliding window for limits a decorator cannot express.

    /auth/token serves password sign-in and refresh, and the grant type is in
    the body, which slowapi's decorator never sees. The route allows the
    refresh rate (several tabs, 401 retries); password attempts are counted
    here at the stricter rate.
    """

    def __init__(self, limit: int, seconds: float) -> None:
        self.limit, self.seconds = limit, seconds
        self._hits: dict[str, list[float]] = {}

    def hit(self, key: str) -> bool:
        """Count one attempt; False when the window is already full."""
        import time

        now = time.monotonic()
        recent = [t for t in self._hits.get(key, []) if now - t < self.seconds]
        if len(recent) >= self.limit:
            self._hits[key] = recent
            return False
        recent.append(now)
        self._hits[key] = recent
        if len(self._hits) > 10_000:  # bounded: drop keys with nothing recent
            self._hits = {k: v for k, v in self._hits.items() if v and now - v[-1] < self.seconds}
        return True

    def reset(self) -> None:
        self._hits.clear()


# Password sign-ins per address per minute. 10 unless the environment says
# otherwise; the local screenshot run raises it (24 sign-ins in a minute).
password_attempts = Window(int(os.environ.get("SELKO_SIGNIN_ATTEMPTS_PER_MINUTE") or 10), 60)
# /auth/token as a whole (refreshes included), per address per minute.
TOKEN_ROUTE_LIMIT = f"{int(os.environ.get('SELKO_TOKEN_REQUESTS_PER_MINUTE') or 30)}/minute"
