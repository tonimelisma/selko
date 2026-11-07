"""What the MCP tools do, separated from how they are registered.

Every read uses the caller's own token through PostgREST, so row-level security
decides what is visible, as it does for the web and mobile apps. Writes go
through the same RPCs and service functions the REST routes use:

- accept / reject a new event → ``set_event_review_status`` (the web app's call)
- accept / reject a change → ``apply_change_proposal`` / ``reject_change_proposal``
  after an ownership check with the caller's token (the REST route's sequence)
- sync now → ``request_email_sync_now``

There is no second implementation of any decision. Outputs are compact and
content-light: an email's subject and sender identify where an event came from,
but bodies never leave the database through this surface.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any, Callable
from zoneinfo import ZoneInfo

from supabase import Client

from selko.services.events import (
    EventsError,
    apply_change_proposal,
    derive_delivery_status,
    get_user_timezone,
    reject_change_proposal,
)

logger = logging.getLogger(__name__)

MAX_DESCRIPTION_CHARS = 1500

_EVENT_COLUMNS = (
    "id, title, start_datetime, end_datetime, all_day, location, description, "
    "importance, review_status, google_calendar_event_id, updated_at, created_at"
)
_WORK_ITEMS = "calendar_work_items(action, generation, status, failure_code)"
_PROPOSALS = "event_change_proposals(id, kind, status, change_set, created_at)"
_SOURCES = (
    "event_sources(source_type, source_origin, created_at, "
    "emails(subject, from_email, from_name, date_sent))"
)


class OperationError(Exception):
    """A request the caller can fix. The message says how."""


# ---------------------------------------------------------------- formatting


def _parse(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _local(value: Any, tz: ZoneInfo) -> str | None:
    parsed = _parse(value)
    return parsed.astimezone(tz).isoformat(timespec="minutes") if parsed else None


def _when(event: dict[str, Any], tz: ZoneInfo) -> dict[str, Any]:
    """Times in the user's own timezone, the way the apps show them."""
    if event.get("all_day"):
        start = _parse(event.get("start_datetime"))
        end = _parse(event.get("end_datetime"))
        start_day = start.astimezone(tz).date() if start else None
        # All-day ends are stored as the last moment of the final day.
        end_day = (end - timedelta(minutes=1)).astimezone(tz).date() if end else None
        return {
            "all_day": True,
            "start_date": start_day.isoformat() if start_day else None,
            "end_date": end_day.isoformat() if end_day and end_day != start_day else None,
        }
    return {
        "all_day": False,
        "start": _local(event.get("start_datetime"), tz),
        "end": _local(event.get("end_datetime"), tz),
    }


def _first_email(event: dict[str, Any]) -> dict[str, Any] | None:
    sources = sorted(
        (s for s in event.get("event_sources") or [] if s.get("emails")),
        key=lambda s: s.get("created_at") or "",
    )
    if not sources:
        return None
    email = sources[0]["emails"]
    return {
        "subject": email.get("subject"),
        "from": email.get("from_name") or email.get("from_email"),
        "from_email": email.get("from_email"),
    }


def _pending_proposal(event: dict[str, Any]) -> dict[str, Any] | None:
    for proposal in event.get("event_change_proposals") or []:
        if proposal.get("status") == "pending":
            return proposal
    return None


def _latest_decided_proposal(event: dict[str, Any]) -> dict[str, Any] | None:
    decided = [
        p for p in event.get("event_change_proposals") or []
        if p.get("status") in ("applied", "rejected")
    ]
    return max(decided, key=lambda p: p.get("created_at") or "", default=None)


def _change_summary(proposal: dict[str, Any], tz: ZoneInfo) -> dict[str, Any]:
    change_set = proposal.get("change_set") or {}
    changes = []
    for change in change_set.get("changes") or []:
        field = change.get("field")
        before, after = change.get("before"), change.get("after")
        if field in {"start_datetime", "end_datetime"}:
            before, after = _local(before, tz), _local(after, tz)
        changes.append({"field": field, "before": before, "after": after})
    return {
        "proposal_id": proposal.get("id"),
        "kind": "cancellation" if proposal.get("kind") == "cancellation" else "update",
        "changes": changes,
    }


def _summary(event: dict[str, Any], tz: ZoneInfo) -> dict[str, Any]:
    proposal = _pending_proposal(event)
    item: dict[str, Any] = {
        "event_id": event["id"],
        "title": event.get("title"),
        **_when(event, tz),
        "location": event.get("location"),
        "status": derive_delivery_status(event),
        "source": _first_email(event),
    }
    if event.get("review_status") == "pending_review":
        item["lane"] = "new"
    elif proposal is not None:
        item["lane"] = "change"
        item["change"] = _change_summary(proposal, tz)
    return item


def _still_relevant(event: dict[str, Any], now: datetime) -> bool:
    """The review queue hides events that are already over, as the apps do."""
    edge = _parse(event.get("end_datetime")) or _parse(event.get("start_datetime"))
    return edge is None or edge >= now


# --------------------------------------------------------------------- reads


class SelkoOperations:
    """The operations available to one authenticated user."""

    def __init__(
        self,
        user_client: Client,
        user_id: str,
        service_client_factory: Callable[[], Client],
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        self._db = user_client
        self._user_id = user_id
        self._service = service_client_factory
        self._now = now
        self._tz: ZoneInfo | None = None

    @property
    def tz(self) -> ZoneInfo:
        if self._tz is None:
            name = get_user_timezone(self._db, self._user_id)
            try:
                self._tz = ZoneInfo(name)
            except Exception:
                self._tz = ZoneInfo("UTC")
        return self._tz

    def review_queue(self, limit: int) -> dict[str, Any]:
        now = self._now()
        rows = (
            self._db.table("events")
            .select(f"{_EVENT_COLUMNS}, {_SOURCES}, {_PROPOSALS}, {_WORK_ITEMS}")
            .in_("review_status", ["pending_review", "active"])
            .order("start_datetime")
            .execute()
            .data
            or []
        )
        waiting = [
            row for row in rows
            if _still_relevant(row, now)
            and (row.get("review_status") == "pending_review" or _pending_proposal(row))
        ]
        items = [_summary(row, self.tz) for row in waiting[:limit]]
        return {
            "timezone": self.tz.key,
            "total_waiting": len(waiting),
            "new_count": sum(1 for r in waiting if r.get("review_status") == "pending_review"),
            "change_count": sum(1 for r in waiting if r.get("review_status") != "pending_review"),
            "shown": len(items),
            "items": items,
        }

    def get_event(self, event_id: str) -> dict[str, Any]:
        result = (
            self._db.table("events")
            .select(f"{_EVENT_COLUMNS}, {_SOURCES}, {_PROPOSALS}, {_WORK_ITEMS}")
            .eq("id", event_id)
            .maybe_single()
            .execute()
        )
        event = result.data if result is not None else None
        if not event:
            raise OperationError(
                f"No event {event_id} in this account. "
                "Use list_review_queue or list_calendar_events to find event ids."
            )
        detail = _summary(event, self.tz)
        description = event.get("description") or ""
        if len(description) > MAX_DESCRIPTION_CHARS:
            description = description[:MAX_DESCRIPTION_CHARS] + " …(truncated)"
        detail["description"] = description or None
        detail["importance"] = event.get("importance")
        detail["review_status"] = event.get("review_status")
        detail["sources"] = [
            {
                "type": source.get("source_type"),
                "origin": source.get("source_origin"),
                "subject": (source.get("emails") or {}).get("subject"),
                "from": (source.get("emails") or {}).get("from_name")
                or (source.get("emails") or {}).get("from_email"),
                "received": _local((source.get("emails") or {}).get("date_sent"), self.tz),
            }
            for source in sorted(
                event.get("event_sources") or [], key=lambda s: s.get("created_at") or ""
            )
        ]
        return detail

    def calendar_events(
        self, start_after: str | None, start_before: str | None, limit: int
    ) -> dict[str, Any]:
        after = _parse_bound(start_after, "start_after") or self._now()
        before = _parse_bound(start_before, "start_before")
        query = (
            self._db.table("events")
            .select(f"{_EVENT_COLUMNS}, {_SOURCES}, {_WORK_ITEMS}")
            .eq("review_status", "active")
            .gte("start_datetime", after.isoformat())
            .order("start_datetime")
            .limit(limit)
        )
        if before is not None:
            query = query.lte("start_datetime", before.isoformat())
        rows = query.execute().data or []
        return {
            "timezone": self.tz.key,
            "shown": len(rows),
            "items": [_summary(row, self.tz) for row in rows],
        }

    def recent_activity(self, since_hours: int, limit: int) -> dict[str, Any]:
        since = self._now() - timedelta(hours=since_hours)
        rows = (
            self._db.table("events")
            .select(f"{_EVENT_COLUMNS}, {_SOURCES}, {_PROPOSALS}, {_WORK_ITEMS}")
            .gte("updated_at", since.isoformat())
            .order("updated_at", desc=True)
            .limit(limit)
            .execute()
            .data
            or []
        )
        items = []
        for row in rows:
            summary = _summary(row, self.tz)
            summary["updated"] = _local(row.get("updated_at"), self.tz)
            summary["found"] = _local(row.get("created_at"), self.tz)
            applied = [
                p for p in row.get("event_change_proposals") or [] if p.get("status") == "applied"
            ]
            if applied:
                latest = max(applied, key=lambda p: p.get("created_at") or "")
                summary["last_applied_change"] = _change_summary(latest, self.tz)
            items.append(summary)
        return {"timezone": self.tz.key, "since_hours": since_hours, "items": items}

    def account_status(self) -> dict[str, Any]:
        # Explicit columns: this table also holds OAuth tokens.
        integrations = (
            self._db.table("integrations")
            .select("provider, provider_email, status, updated_at")
            .neq("provider", "google_photos")
            .execute()
            .data
            or []
        )
        queue = self.review_queue(limit=0)
        return {
            "timezone": self.tz.key,
            "connections": [
                {
                    "provider": row.get("provider"),
                    "account": row.get("provider_email"),
                    "status": row.get("status"),
                    "needs_reconnect": row.get("status") in {"expired", "revoked", "error"},
                }
                for row in integrations
            ],
            "waiting_for_review": {
                "new": queue["new_count"],
                "changes": queue["change_count"],
            },
        }

    # ---------------------------------------------------------------- writes

    def _owned(self, event_id: str) -> dict[str, Any]:
        result = (
            self._db.table("events")
            .select(f"id, title, review_status, {_PROPOSALS}")
            .eq("id", event_id)
            .maybe_single()
            .execute()
        )
        event = result.data if result is not None else None
        if not event:
            raise OperationError(
                f"No event {event_id} in this account. Use list_review_queue to find event ids."
            )
        return event

    def decide_new(self, event_id: str, approve: bool) -> dict[str, Any]:
        event = self._owned(event_id)
        status = event.get("review_status")
        # A widget card is rendered once from a tool result and can be shown
        # again after the decision was made (the chat reloads, or the user
        # decided in the app). Repeating that same decision is not an error:
        # report it as done instead of telling the user something went wrong.
        if (approve and status == "active") or (not approve and status == "rejected"):
            return {
                "event_id": event_id,
                "title": event.get("title"),
                "result": "accepted" if approve else "rejected",
                "already_decided": True,
                "detail": "Already accepted." if approve else "Already rejected.",
            }
        if status in ("active", "rejected"):
            raise OperationError(
                f"'{event.get('title')}' was already "
                f"{'accepted' if status == 'active' else 'rejected'} earlier and is "
                "not waiting for review. Undo that in the Selko app if needed."
            )
        if status != "pending_review":
            raise OperationError(
                f"'{event.get('title')}' is not waiting for review "
                f"(review status: {event.get('review_status')}). Only events in the "
                "New lane of list_review_queue can be accepted or rejected."
            )
        self._db.rpc(
            "set_event_review_status",
            {"p_event_id": event_id, "p_review_status": "active" if approve else "rejected"},
        ).execute()
        if approve:
            return {
                "event_id": event_id,
                "title": event.get("title"),
                "result": "accepted",
                "detail": "Queued for your calendar; it usually appears within a minute.",
            }
        return {
            "event_id": event_id,
            "title": event.get("title"),
            "result": "rejected",
            "detail": "Rejected. Later emails about this event will not bring it back.",
        }

    def decide_change(self, event_id: str, apply: bool) -> dict[str, Any]:
        event = self._owned(event_id)
        proposal = _pending_proposal(event)
        if proposal is None:
            # Same as decide_new: a stale card repeating the decision already
            # on record succeeds; one that contradicts it says what happened.
            latest = _latest_decided_proposal(event)
            if latest is not None:
                done = latest.get("status") == ("applied" if apply else "rejected")
                if done:
                    return {
                        "event_id": event_id,
                        "title": event.get("title"),
                        "result": "accepted" if apply else "rejected",
                        "kind": "cancellation" if latest.get("kind") == "cancellation" else "update",
                        "already_decided": True,
                        "detail": (
                            "Already applied to your calendar." if apply
                            else "Already rejected; the calendar entry stays as it was."
                        ),
                    }
                raise OperationError(
                    f"The change to '{event.get('title')}' was already "
                    f"{'applied' if latest.get('status') == 'applied' else 'rejected'}, "
                    "so there is nothing pending to decide."
                )
            raise OperationError(
                f"'{event.get('title')}' has no pending change. Only events in the "
                "Changes lane of list_review_queue have one."
            )
        service = self._service()
        try:
            if apply:
                apply_change_proposal(service, event_id, proposal["id"])
            else:
                reject_change_proposal(service, event_id, proposal["id"])
        except EventsError as exc:
            raise OperationError(str(exc)) from exc
        _nudge_calendar_worker()
        kind = "cancellation" if proposal.get("kind") == "cancellation" else "update"
        if apply:
            detail = (
                "The event will be removed from your calendar."
                if kind == "cancellation"
                else "Your calendar entry will be updated."
            )
        else:
            detail = "Change rejected; the calendar entry stays as it was."
        return {
            "event_id": event_id,
            "title": event.get("title"),
            "result": "accepted" if apply else "rejected",
            "kind": kind,
            "detail": detail,
        }

    def request_sync(self) -> dict[str, Any]:
        rows = (
            self._db.table("integrations")
            .select("id, provider, provider_email, status")
            .in_("provider", ["gmail", "outlook"])
            .eq("status", "active")
            .execute()
            .data
            or []
        )
        if not rows:
            raise OperationError(
                "No connected mailbox to check. Connect Gmail or Outlook in Selko settings."
            )
        for row in rows:
            self._db.rpc("request_email_sync_now", {"p_integration_id": row["id"]}).execute()
        return {
            "requested": [
                {"provider": row["provider"], "account": row.get("provider_email")} for row in rows
            ],
            "detail": "Selko will check these mailboxes on its next pass, usually within a minute.",
        }


def _parse_bound(value: str | None, name: str) -> datetime | None:
    if value is None or value == "":
        return None
    parsed = _parse(value)
    if parsed is None:
        raise OperationError(f"{name} must be an ISO 8601 date or datetime, got {value!r}.")
    return parsed


def _nudge_calendar_worker() -> None:
    """Wake the calendar worker, as the REST apply-change route does."""
    try:
        from selko.api.app import worker_pool

        if worker_pool is not None:
            worker_pool.nudge()
    except Exception:
        pass
