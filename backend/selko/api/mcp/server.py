"""Selko's MCP server: the review queue and calendar, for Claude.

Tool design follows Claude's connector review criteria:

- reads and writes are separate tools, each with ``title``, ``readOnlyHint``
  and ``destructiveHint`` annotations, so Claude can run reads without asking
  and asks before anything that changes the user's calendar;
- names and verbs match the apps (Accept / Reject, New / Changes lanes);
- every error says what to do next;
- results are compact JSON with the ids a follow-up call needs.

``list_review_queue`` carries an MCP Apps widget (``ui://selko/review-queue.html``)
that renders the queue as cards with Accept / Reject buttons in hosts that
support it, and plain JSON everywhere else, including scheduled runs.
"""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any, Callable

from mcp.server.apps import Apps
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.settings import AuthSettings
from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError
from mcp.types import ToolAnnotations
from pydantic import Field
from supabase import Client, ClientOptions, create_client

from selko.api.mcp.auth import SupabaseTokenVerifier, supabase_user_validator
from selko.api.mcp.operations import OperationError, SelkoOperations
from selko.config import Config

logger = logging.getLogger(__name__)

REVIEW_WIDGET_URI = "ui://selko/review-queue.html"
_HERE = Path(__file__).parent
_EXT_APPS_BUNDLE = _HERE / "static" / "ext-apps-2.0.4.js"

INSTRUCTIONS = """\
Selko reads the user's email (Gmail or Outlook) and finds events in it: \
invitations, bookings, school notices, tickets. Each one waits in a review \
queue until the user decides.

- New lane: an event Selko found that is not on the calendar yet. \
accept_event puts it on the calendar; reject_event discards it for good.
- Changes lane: a later email changed or cancelled an event already on the \
calendar. accept_change applies it to the calendar entry; reject_change keeps \
the entry as it is.

Times are in the user's own timezone, reported with each result. Selko only \
knows about events it found in email; list_calendar_events is not the user's \
whole calendar.\
"""

EventId = Annotated[
    str,
    Field(
        description="Event id (UUID) from list_review_queue, list_calendar_events or list_recent_activity.",
        pattern=r"^[0-9a-fA-F-]{36}$",
    ),
]

READ = ToolAnnotations(readOnlyHint=True, destructiveHint=False, openWorldHint=False)


def _write(title: str, *, destructive: bool, idempotent: bool = False) -> ToolAnnotations:
    return ToolAnnotations(
        title=title,
        readOnlyHint=False,
        destructiveHint=destructive,
        idempotentHint=idempotent,
        # Writes reach the user's Google or Outlook calendar.
        openWorldHint=True,
    )


def _read(title: str) -> ToolAnnotations:
    return READ.model_copy(update={"title": title})


@lru_cache(maxsize=1)
def _widget_html() -> str:
    """The widget with the ext-apps runtime inlined.

    The iframe's CSP blocks CDN imports, so the runtime ships inside the page.
    The vendored bundle is minified ESM ending in ``export{a as B,...}``; an
    inline module cannot export, so the statement becomes a global.
    """
    bundle = _EXT_APPS_BUNDLE.read_text(encoding="utf-8")
    match = re.search(r"export\{([^}]+)\};?\s*$", bundle)
    if match is None:
        raise RuntimeError("ext-apps bundle has no trailing export statement")
    pairs = []
    for pair in match.group(1).split(","):
        local, _, exported = (part.strip() for part in pair.partition(" as "))
        pairs.append(f"{exported or local}:{local}")
    bundle = bundle[: match.start()] + "globalThis.ExtApps={" + ",".join(pairs) + "};"
    html = (_HERE / "review_queue.html").read_text(encoding="utf-8")
    if "/*__EXT_APPS_BUNDLE__*/" not in html:
        raise RuntimeError("review widget is missing its bundle placeholder")
    return html.replace("/*__EXT_APPS_BUNDLE__*/", bundle, 1)


def mcp_resource_url(config: Config) -> str:
    return f"{config.api_public_url}/mcp"


def mcp_issuer_url(config: Config) -> str:
    """Supabase Auth's OAuth 2.1 server is the authorization server."""
    return f"{config.supabase_url.rstrip('/')}/auth/v1"


def create_mcp_server(
    config: Config,
    *,
    token_verifier: Any | None = None,
    user_client_factory: Callable[[str], Client] | None = None,
    service_client_factory: Callable[[], Client] | None = None,
) -> MCPServer:
    """Build the server. Factories are injectable so tests can run it in-process."""

    def default_user_client(token: str) -> Client:
        return create_client(
            config.supabase_url,
            config.supabase_key,
            options=ClientOptions(headers={"Authorization": f"Bearer {token}"}),
        )

    def default_service_client() -> Client:
        from selko.services.auth import get_service_client

        return get_service_client(config)

    make_user_client = user_client_factory or default_user_client
    make_service_client = service_client_factory or default_service_client

    verifier = token_verifier or SupabaseTokenVerifier(
        supabase_user_validator(config.supabase_url, config.supabase_key),
        frozenset(config.mcp_oauth_client_ids),
    )

    def ops() -> SelkoOperations:
        access = get_access_token()
        if access is None or not access.subject:
            # The transport refuses unauthenticated requests before this point.
            raise ToolError("Not signed in to Selko. Reconnect the Selko connector.")
        return SelkoOperations(make_user_client(access.token), access.subject, make_service_client)

    def run(fn: Callable[[SelkoOperations], dict[str, Any]]) -> dict[str, Any]:
        try:
            return fn(ops())
        except OperationError as exc:
            raise ToolError(str(exc)) from exc
        except ToolError:
            raise
        except Exception as exc:
            logger.exception("mcp_tool_failed")
            raise ToolError(
                "Selko could not complete this request right now. Try again in a minute."
            ) from exc

    apps = Apps()

    @apps.tool(
        resource_uri=REVIEW_WIDGET_URI,
        name="list_review_queue",
        title="List events waiting for review",
        annotations=_read("List events waiting for review"),
        description=(
            "List upcoming events Selko found in email that are waiting for the user's "
            "decision: New-lane events not yet on the calendar, and Changes-lane updates "
            "or cancellations to events already on it. Returns counts, and for each item "
            "the event_id, lane, title, time, location, the email it came from and, for "
            "changes, each changed field before and after. Past events are left out. "
            "Use get_event for an event's full description and sources."
        ),
    )
    def list_review_queue(
        limit: Annotated[int, Field(ge=1, le=50, description="Maximum items to return.")] = 20,
    ) -> dict[str, Any]:
        def go(o: SelkoOperations) -> dict[str, Any]:
            result = o.review_queue(limit)
            result["app_url"] = f"{config.frontend_url}/app"
            return result

        return run(go)

    apps.add_html_resource(
        REVIEW_WIDGET_URI,
        _widget_html(),
        name="Selko review queue",
        description="Cards for events waiting for review, with Accept and Reject buttons.",
    )

    server = MCPServer(
        name="selko",
        title="Selko",
        description="Events from your email, reviewed onto your calendar.",
        instructions=INSTRUCTIONS,
        website_url=config.frontend_url,
        version="1.0.0",
        token_verifier=verifier,
        auth=AuthSettings(
            issuer_url=mcp_issuer_url(config),
            resource_server_url=mcp_resource_url(config),
            # Supabase ignores RFC 8707 resource indicators; the verifier
            # checks the OAuth client_id claim instead (see auth.py).
            validate_token_resource=False,
        ),
        extensions=[apps],
    )

    @server.tool(
        name="get_event",
        title="Get event details",
        annotations=_read("Get event details"),
        description=(
            "Get one event Selko knows about: time, location, description (truncated at "
            "1,500 characters), review and calendar status, any pending change, and every "
            "email that contributed to it (subject, sender, received time). Email bodies "
            "are not returned."
        ),
    )
    def get_event(event_id: EventId) -> dict[str, Any]:
        return run(lambda o: o.get_event(event_id))

    @server.tool(
        name="list_calendar_events",
        title="List accepted events",
        annotations=_read("List accepted events"),
        description=(
            "List events the user accepted from email, which Selko keeps on their "
            "calendar, in start-time order, with calendar delivery status (approved, "
            "syncing, synced, sync_failed). Only Selko's events, not the whole calendar. "
            "Defaults to events starting from now."
        ),
    )
    def list_calendar_events(
        start_after: Annotated[
            str | None, Field(description="ISO 8601 date or datetime; defaults to now.")
        ] = None,
        start_before: Annotated[
            str | None, Field(description="ISO 8601 date or datetime; no upper bound if omitted.")
        ] = None,
        limit: Annotated[int, Field(ge=1, le=100, description="Maximum events to return.")] = 25,
    ) -> dict[str, Any]:
        return run(lambda o: o.calendar_events(start_after, start_before, limit))

    @server.tool(
        name="list_recent_activity",
        title="List recent activity",
        annotations=_read("List recent activity"),
        description=(
            "List events Selko found or changed recently, newest first, including updates "
            "it applied to the calendar automatically. Each item has its current lane or "
            "status and, where one was applied, the last change. Use this for a 'what "
            "happened since yesterday' summary; use list_review_queue for what still "
            "needs a decision."
        ),
    )
    def list_recent_activity(
        since_hours: Annotated[
            int, Field(ge=1, le=336, description="Look back this many hours.")
        ] = 24,
        limit: Annotated[int, Field(ge=1, le=100, description="Maximum events to return.")] = 30,
    ) -> dict[str, Any]:
        return run(lambda o: o.recent_activity(since_hours, limit))

    @server.tool(
        name="get_account_status",
        title="Get Selko account status",
        annotations=_read("Get Selko account status"),
        description=(
            "Report which mail and calendar accounts are connected and whether any needs "
            "reconnecting, plus how many events wait in the New and Changes lanes."
        ),
    )
    def get_account_status() -> dict[str, Any]:
        return run(lambda o: o.account_status())

    @server.tool(
        name="accept_event",
        title="Accept event onto calendar",
        annotations=_write("Accept event onto calendar", destructive=False),
        description=(
            "Accept a New-lane event from list_review_queue: Selko adds it to the user's "
            "calendar within about a minute. Only works on events waiting in the New lane; "
            "for a changed event use accept_change."
        ),
    )
    def accept_event(event_id: EventId) -> dict[str, Any]:
        return run(lambda o: o.decide_new(event_id, approve=True))

    @server.tool(
        name="reject_event",
        title="Reject event",
        annotations=_write("Reject event", destructive=True),
        description=(
            "Reject a New-lane event from list_review_queue. It is discarded for good: "
            "later emails about the same event will not bring it back. For a changed "
            "event use reject_change."
        ),
    )
    def reject_event(event_id: EventId) -> dict[str, Any]:
        return run(lambda o: o.decide_new(event_id, approve=False))

    @server.tool(
        name="accept_change",
        title="Accept change to calendar event",
        annotations=_write("Accept change to calendar event", destructive=True),
        description=(
            "Accept a Changes-lane item from list_review_queue: Selko rewrites the "
            "calendar entry with the new details, or removes it if the change is a "
            "cancellation."
        ),
    )
    def accept_change(event_id: EventId) -> dict[str, Any]:
        return run(lambda o: o.decide_change(event_id, apply=True))

    @server.tool(
        name="reject_change",
        title="Reject change",
        annotations=_write("Reject change", destructive=False),
        description=(
            "Reject a Changes-lane item from list_review_queue. The calendar entry stays "
            "as it is."
        ),
    )
    def reject_change(event_id: EventId) -> dict[str, Any]:
        return run(lambda o: o.decide_change(event_id, apply=False))

    @server.tool(
        name="check_email_now",
        title="Check email now",
        annotations=_write("Check email now", destructive=False, idempotent=True),
        description=(
            "Ask Selko to check the user's connected mailboxes on its next pass instead of "
            "waiting for the regular schedule. New events show up in list_review_queue "
            "a minute or two later."
        ),
    )
    def check_email_now() -> dict[str, Any]:
        return run(lambda o: o.request_sync())

    @server.prompt(
        name="daily_digest",
        title="Daily Selko digest",
        description="Summarize what Selko found since yesterday and what is waiting for review.",
    )
    def daily_digest(since_hours: str = "24") -> str:
        return (
            f"Using the Selko tools, write a short digest of the last {since_hours} hours. "
            "Call list_recent_activity and list_review_queue. List what is waiting for a "
            "decision first (title, when, where it came from, and for changes what "
            "changed), then what Selko already put on the calendar or updated. Call "
            "get_account_status and mention any account that needs reconnecting. Do not "
            "accept or reject anything."
        )

    return server
