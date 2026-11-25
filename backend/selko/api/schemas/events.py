"""Event-related Pydantic schemas for API responses."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel


class CalendarListResponse(BaseModel):
    """A calendar Selko can write to, from any connected provider."""

    # Opaque: Outlook ids are qualified ("outlook:<id>"). Clients store it
    # unchanged in user_calendar_settings.target_calendar_id.
    id: str
    name: str
    is_primary: bool
    is_selected: bool  # True if this is the target calendar
    provider: Literal["google_calendar", "outlook"] = "google_calendar"


class CalendarSyncResponse(BaseModel):
    """Current state after an idempotent calendar sync request."""

    event_id: str
    google_calendar_event_id: Optional[str] = None
    synced_at: Optional[datetime] = None
    status: Literal["approved", "syncing", "synced"]


class EventChangeResponse(BaseModel):
    """Result of applying or rejecting a pending change."""

    event_id: str
    status: str


class EventUndoRequest(BaseModel):
    """Optional body for History Undo (force overwrite of diverged GCal edits)."""

    force: bool = False


class EventUndoResponse(BaseModel):
    """Result of undoing a History action back to a review lane."""

    event_id: str
    status: Literal["pending_review", "active"]

