"""GET /live: live invalidation hints over server-sent events (03-api-auth-web.md §C).

The web app reads this with a streaming ``fetch`` and its normal Bearer token
(no token in a URL). Each message tells the client which resource changed; the
client refetches through the API, so a lost or coalesced message costs latency,
never correctness.

The stream carries only the verified token subject's own hints: the data layer
publishes on ``user:<id>`` after commit, and this route subscribes to exactly
that topic.
"""

from __future__ import annotations

import json
import time
from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import StreamingResponse

from selko.api.limits import limiter
from selko.api.routes.auth import require_identity
from selko.services.accounts import Identity

router = APIRouter(tags=["live"])

HEARTBEAT_SECONDS = 25
MAX_STREAMS_PER_USER = 5
MAX_STREAMS = 200
RESOURCES = ("events", "emails", "event_sources", "integrations", "calendar_work_items", "event_change_proposals")

_open: dict[str, int] = {}


def _sse(event: str, data: object | None = None) -> bytes:
    lines = [f"event: {event}"]
    if data is not None:
        lines.append("data: " + json.dumps(data, separators=(",", ":")))
    return ("\n".join(lines) + "\n\n").encode()


def _token_expiry(token: str) -> float:
    import jwt

    return float(jwt.decode(token, options={"verify_signature": False}).get("exp", time.time()))


@router.get("/live")
@limiter.limit("30/minute")
async def live(request: Request, identity: Identity = Depends(require_identity)) -> StreamingResponse:
    bus = request.app.state.bus
    if _open.get(identity.user_id, 0) >= MAX_STREAMS_PER_USER:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, "Too many live streams")
    if sum(_open.values()) >= MAX_STREAMS:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Live updates are busy")

    subscription = bus.subscribe(f"user:{identity.user_id}")
    _open[identity.user_id] = _open.get(identity.user_id, 0) + 1
    ends_at = _token_expiry(identity.token)

    async def stream() -> AsyncIterator[bytes]:
        try:
            yield _sse("ready", {"user_id": identity.user_id, "heartbeat_seconds": HEARTBEAT_SECONDS})
            while True:
                remaining = ends_at - time.time()
                if remaining <= 0:
                    yield _sse("reauth")
                    return
                try:
                    message = await subscription.get(timeout=min(HEARTBEAT_SECONDS, remaining))
                except TimeoutError:
                    yield b": ping\n\n"
                    continue
                batch = [message]
                while not subscription.queue.empty():
                    batch.append(subscription.queue.get_nowait())
                if any(
                    m.get("resource") == "session"
                    and m.get("operation") == "REVOKED"
                    and m.get("session_id") in (None, identity.session_id)
                    for m in batch
                ):
                    yield _sse("revoked")
                    return
                if subscription.lagged:
                    subscription.lagged = False
                    for resource in RESOURCES:
                        yield _sse("invalidate", {"resource": resource, "operation": "CATCHUP"})
                    continue
                seen: dict[str, dict] = {}
                for m in batch:
                    if m.get("resource") in RESOURCES and m["resource"] not in seen:
                        seen[m["resource"]] = m
                for m in seen.values():
                    yield _sse(
                        "invalidate",
                        {"resource": m["resource"], "operation": m["operation"], "occurred_at": m["occurred_at"]},
                    )
        finally:
            bus.unsubscribe(subscription)
            _open[identity.user_id] -= 1
            if _open[identity.user_id] <= 0:
                del _open[identity.user_id]

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache, no-transform", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )

