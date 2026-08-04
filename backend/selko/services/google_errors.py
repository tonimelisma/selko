"""Shared interpretation of Google API error responses.

Both Gmail (people.googleapis.com/gmail) and Google Calendar return the same
structured error shape:

    {"error": {"errors": [{"reason": "..."}], "status": "..."}}

The helpers here extract that structured reason so callers can branch on type
instead of substring-matching the human-readable message. Two constant sets are
shared by every Google-backed classifier: reasons that mean *insufficient
scope/permissions* (auth, but fixable by re-consent) and reasons that mean
*throttling* (retryable, never auth).
"""

from __future__ import annotations

import json
from typing import Optional

from googleapiclient.errors import HttpError

# Google reasons that mean the token lacks the scopes the call needs. Reconnect
# (re-consent) is the fix, not retry — the same token will keep failing.
INSUFFICIENT_SCOPE_REASONS = {
    "insufficientPermissions",
    "insufficientScopes",
    "ACCESS_TOKEN_SCOPE_INSUFFICIENT",
}

# Google reasons that mean throttle/quota. These retry successfully.
RATE_LIMIT_REASONS = {
    "rateLimitExceeded",
    "userRateLimitExceeded",
    "quotaExceeded",
    "dailyLimitExceeded",
}


def google_error_reason(exc: HttpError) -> Optional[str]:
    """Best-effort extraction of Google's structured error reason.

    Returns None if the response body isn't the expected JSON shape; callers
    fall back to the HTTP status code in that case.
    """
    try:
        content = exc.content
        if isinstance(content, bytes):
            content = content.decode("utf-8")
        body = json.loads(content).get("error", {})
    except Exception:
        return None

    sub_errors = body.get("errors")
    if isinstance(sub_errors, list) and sub_errors:
        reason = sub_errors[0].get("reason")
        if reason:
            return reason
    return body.get("status")