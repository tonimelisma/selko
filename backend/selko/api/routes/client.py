"""The web app's data API (03-api-auth-web.md §A, E1-E19, and E25).

Each handler takes the verified user from the token and passes its id to the
data layer; another user's row and a missing row both answer 404, so ids
cannot be probed.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from selko.api.deps import CurrentUser, get_current_user, get_db
from selko.api.limits import limiter
from selko.db import client as data
from selko.db.codec import to_timestamp
from selko.db.connection import Database
from selko.db.errors import InvalidArgument, NotOwned

router = APIRouter(tags=["client"])


def _not_found(what: str = "Not found") -> HTTPException:
    return HTTPException(status.HTTP_404_NOT_FOUND, what)


def _uuid(value: str) -> str:
    try:
        return str(uuid.UUID(value))
    except ValueError as exc:
        raise _not_found() from exc


def _with_status(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    from selko.services.events import derive_delivery_status

    for event in events:
        event["status"] = derive_delivery_status(event)
    return events


async def _one_event(db: Database, user_id: str, event_id: str) -> dict[str, Any]:
    found = await db.run(data.events_with_relations, db, user_id, [event_id])
    if not found:
        raise _not_found("Event not found")
    return _with_status(found)[0]


# --- events (E1-E6) -------------------------------------------------------


@router.get("/events/review")
async def review_queue(user: CurrentUser = Depends(get_current_user), db: Database = Depends(get_db)) -> list[dict[str, Any]]:
    now = to_timestamp(datetime.now(timezone.utc))
    ids = await db.run(data.review_event_ids, db, user.id, now)
    return _with_status(await db.run(data.events_with_relations, db, user.id, ids))


@router.get("/events/activity")
async def activity(
    limit: int = Query(20, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(get_current_user),
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    ids, total = await db.run(data.activity_page, db, user.id, limit, offset)
    items = await db.run(data.events_with_relations, db, user.id, ids, exclude_pending_proposals=True)
    return {"items": _with_status(items), "total": total, "offset": offset, "limit": limit}


@router.get("/events/{event_id}")
async def get_event(event_id: str, user: CurrentUser = Depends(get_current_user), db: Database = Depends(get_db)) -> dict[str, Any]:
    return await _one_event(db, user.id, _uuid(event_id))


class EventPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str | None = Field(None, min_length=1, max_length=500)
    start_datetime: str | None = None
    end_datetime: str | None = None
    all_day: bool | None = None
    location: str | None = Field(None, max_length=1000)
    description: str | None = Field(None, max_length=20000)

    @field_validator("title")
    @classmethod
    def _title(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("title must not be blank")
        return v.strip() if v is not None else v

    @field_validator("start_datetime", "end_datetime")
    @classmethod
    def _iso(cls, v: str | None) -> str | None:
        if v is None:
            return v
        try:
            moment = datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError("expected ISO 8601 with an offset") from exc
        if moment.tzinfo is None:
            raise ValueError("expected ISO 8601 with an offset")
        return v


@router.patch("/events/{event_id}")
async def update_event(
    event_id: str, body: EventPatch, user: CurrentUser = Depends(get_current_user), db: Database = Depends(get_db)
) -> dict[str, Any]:
    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Nothing to update")
    event_id = _uuid(event_id)
    if not await db.run(data.update_event, db, user.id, event_id, fields):
        raise _not_found("Event not found")
    return await _one_event(db, user.id, event_id)


async def _decide(request: Request, event_id: str, review_status: str, user: CurrentUser, db: Database) -> dict[str, Any]:
    from selko.db import events as event_rows

    try:
        result = await db.run(event_rows.set_event_review_status, db, user.id, _uuid(event_id), review_status)
    except NotOwned as exc:
        raise _not_found("Event not found") from exc
    except InvalidArgument as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    if review_status == "active":
        from selko.api import app as app_module

        pool = getattr(app_module, "worker_pool", None)
        if pool is not None:
            pool.nudge()
    return result


@router.post("/events/{event_id}/accept")
async def accept_event(request: Request, event_id: str, user: CurrentUser = Depends(get_current_user), db: Database = Depends(get_db)) -> dict[str, Any]:
    return await _decide(request, event_id, "active", user, db)


@router.post("/events/{event_id}/reject")
async def reject_event(request: Request, event_id: str, user: CurrentUser = Depends(get_current_user), db: Database = Depends(get_db)) -> dict[str, Any]:
    return await _decide(request, event_id, "rejected", user, db)


# --- emails (E7-E10) ------------------------------------------------------


@router.get("/emails/history")
async def email_history(
    limit: int = Query(20, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: CurrentUser = Depends(get_current_user),
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    items, total = await db.run(data.email_history, db, user.id, limit, offset)
    return {"items": items, "total": total, "offset": offset, "limit": limit}


@router.get("/emails/{email_id}")
async def get_email(email_id: str, user: CurrentUser = Depends(get_current_user), db: Database = Depends(get_db)) -> dict[str, Any]:
    found = await db.run(data.email_summary, db, user.id, _uuid(email_id))
    if found is None:
        raise _not_found("Email not found")
    return found


@router.get("/emails/{email_id}/processing-state")
async def email_processing_state(email_id: str, user: CurrentUser = Depends(get_current_user), db: Database = Depends(get_db)) -> dict[str, Any]:
    found = await db.run(data.email_processing_state, db, user.id, _uuid(email_id))
    if found is None:
        raise _not_found("Email not found")
    return found


@router.get("/emails/{email_id}/attachments")
async def email_attachments(email_id: str, user: CurrentUser = Depends(get_current_user), db: Database = Depends(get_db)) -> list[dict[str, Any]]:
    found = await db.run(data.email_attachments, db, user.id, _uuid(email_id))
    if found is None:
        raise _not_found("Email not found")
    return found


# --- attachment download (E25) --------------------------------------------


@router.get("/attachments/{attachment_id}/content")
async def attachment_content(attachment_id: str, user: CurrentUser = Depends(get_current_user), db: Database = Depends(get_db)) -> FileResponse:
    from selko.db.runtime import attachments_dir

    found = await db.run(data.attachment_for_download, db, user.id, _uuid(attachment_id))
    if found is None:
        raise _not_found("Attachment not found")
    root = attachments_dir().resolve()
    stored = found.get("storage_path")
    path = (root / stored).resolve() if stored else None
    if path is None or root not in path.parents or not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment is not stored")
    return FileResponse(
        path,
        media_type=found.get("mime_type") or "application/octet-stream",
        filename=os.path.basename(found.get("filename") or path.name),
        headers={"Cache-Control": "private, max-age=0, no-store", "X-Content-Type-Options": "nosniff"},
    )


# --- integrations (E11-E13) -----------------------------------------------


@router.get("/integrations")
async def list_integrations(user: CurrentUser = Depends(get_current_user), db: Database = Depends(get_db)) -> list[dict[str, Any]]:
    return await db.run(data.list_integrations, db, user.id)


class DisconnectBody(BaseModel):
    integration_ids: list[str] = Field(min_length=1, max_length=10)


@router.post("/integrations/disconnect")
@limiter.limit("10/minute")
async def disconnect_integrations(
    request: Request, body: DisconnectBody, user: CurrentUser = Depends(get_current_user), db: Database = Depends(get_db)
) -> dict[str, int]:
    ids = [_uuid(i) for i in body.integration_ids]
    deleted = await db.run(data.delete_integrations, db, user.id, ids)
    if deleted == 0:
        raise _not_found("Integration not found")
    return {"deleted": deleted}


@router.get("/integrations/recovery")
@limiter.limit("30/minute")
async def integration_recovery(
    request: Request,
    provider: str = Query("google_calendar", pattern="^(google_calendar|gmail|outlook)$"),
    user: CurrentUser = Depends(get_current_user),
    db: Database = Depends(get_db),
) -> dict[str, Any]:
    from selko.db import recovery

    return {"recovery": await db.run(recovery.latest_recovery, db, user.id, provider)}


# --- sender rules (E14-E17) -------------------------------------------------


@router.get("/sender-rules")
async def list_sender_rules(user: CurrentUser = Depends(get_current_user), db: Database = Depends(get_db)) -> list[dict[str, Any]]:
    return await db.run(data.list_sender_rules, db, user.id)


class SenderRuleBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sender_email: str | None = None
    sender_domain: str | None = None
    action: Literal["auto_approve", "ignore"]

    @model_validator(mode="after")
    def _one_target(self) -> SenderRuleBody:
        if not (self.sender_email or self.sender_domain):
            raise ValueError("sender_email or sender_domain is required")
        return self


@router.post("/sender-rules", status_code=status.HTTP_201_CREATED)
@limiter.limit("20/minute")
async def create_sender_rule(
    request: Request, body: SenderRuleBody, user: CurrentUser = Depends(get_current_user), db: Database = Depends(get_db)
) -> dict[str, Any]:
    try:
        return await db.run(
            data.create_sender_rule, db, user.id, str(uuid.uuid4()), body.sender_email, body.sender_domain, body.action
        )
    except data.DuplicateRule as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, "A record with this information already exists.") from exc


@router.delete("/sender-rules/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
@limiter.limit("20/minute")
async def delete_sender_rule(
    request: Request, rule_id: str, user: CurrentUser = Depends(get_current_user), db: Database = Depends(get_db)
) -> Response:
    from selko.db import sender_rules

    if not await db.run(sender_rules.delete_rule, db, user.id, _uuid(rule_id)):
        raise _not_found("Rule not found")
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class IgnoreSenderBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sender_email: str | None = None
    sender_domain: str | None = None

    @model_validator(mode="after")
    def _exactly_one(self) -> IgnoreSenderBody:
        if bool(self.sender_email) == bool(self.sender_domain):
            raise ValueError("give exactly one of sender_email and sender_domain")
        return self


@router.post("/sender-rules/ignore-sender")
@limiter.limit("20/minute")
async def ignore_sender(
    request: Request, body: IgnoreSenderBody, user: CurrentUser = Depends(get_current_user), db: Database = Depends(get_db)
) -> dict[str, Any]:
    from selko.db import sender_rules

    return await db.run(
        sender_rules.ignore_sender_and_reject_pending, db, user.id, body.sender_email, body.sender_domain
    )


# --- calendar settings (E18-E19) --------------------------------------------


@router.get("/settings/calendar")
async def get_calendar_settings(user: CurrentUser = Depends(get_current_user), db: Database = Depends(get_db)) -> dict[str, Any]:
    from selko.db import integrations

    return {"settings": await db.run(integrations.get_calendar_settings, db, user.id)}


class CalendarSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target_calendar_id: str | None = None
    default_invitees: str | None = None
    timezone: str | None = None
    all_day_display_mode: Literal["all_day", "day_9_to_5", "morning_8_to_9", "custom"] | None = None
    all_day_custom_start: str | None = None
    all_day_custom_end: str | None = None

    @field_validator("timezone")
    @classmethod
    def _zone(cls, v: str | None) -> str | None:
        if v is not None:
            try:
                ZoneInfo(v)
            except (ZoneInfoNotFoundError, ValueError) as exc:
                raise ValueError("unknown time zone") from exc
        return v

    @field_validator("all_day_custom_start", "all_day_custom_end")
    @classmethod
    def _time(cls, v: str | None) -> str | None:
        if v is not None:
            parts = v.split(":")
            if len(parts) not in (2, 3) or not all(p.isdigit() and len(p) == 2 for p in parts):
                raise ValueError("expected HH:MM or HH:MM:SS")
        return v


@router.patch("/settings/calendar")
@limiter.limit("20/minute")
async def update_calendar_settings(
    request: Request, body: CalendarSettingsPatch, user: CurrentUser = Depends(get_current_user), db: Database = Depends(get_db)
) -> dict[str, Any]:
    from selko.db import integrations

    fields = body.model_dump(exclude_unset=True)
    if not fields:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Nothing to update")
    current = await db.run(integrations.get_calendar_settings, db, user.id) or {}
    merged = {**current, **fields}
    if merged.get("all_day_display_mode") == "custom":
        start, end = merged.get("all_day_custom_start"), merged.get("all_day_custom_end")
        if not start or not end or end[:5] <= start[:5]:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "A custom all-day time needs a start before its end")
    await db.run(integrations.upsert_calendar_settings, db, user.id, fields)
    return {"settings": await db.run(integrations.get_calendar_settings, db, user.id)}
