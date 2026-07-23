"""Event-related Pydantic schemas for API responses."""

from datetime import datetime
from typing import Literal, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class EventResponse(BaseModel):
    """Event for list views."""

    id: UUID
    title: str
    start_datetime: Optional[datetime] = None
    end_datetime: Optional[datetime] = None
    all_day: bool
    location: Optional[str] = None
    status: str  # pending_review, approved, syncing, synced, sync_failed, cancelled, rejected
    source_count: int  # Number of emails contributing to this event
    primary_sender: str  # Sender of the original event email (for grouping)
    created_at: datetime
    updated_at: datetime


class EventSourceResponse(BaseModel):
    """Per-email contribution info."""

    id: UUID
    email_id: UUID
    email_subject: str
    email_sender: str
    email_sender_name: Optional[str] = None
    email_date: datetime
    source_type: str  # new_invitation, update, cancellation, reminder
    source_quote: str  # Verbatim quote from email (collapsible in UI)
    is_undone: bool
    created_at: datetime


class EventWithSources(EventResponse):
    """Full event detail with all source emails."""

    description: str
    source_attribution: str  # Natural English: "Created from email from X on Y..."
    google_calendar_event_id: Optional[str] = None
    synced_at: Optional[datetime] = None
    sources: list[EventSourceResponse] = Field(
        default_factory=list
    )  # All contributing emails


class SenderRuleRequest(BaseModel):
    """Create/update sender rule."""

    sender_domain: Optional[str] = None
    sender_email: Optional[str] = None
    action: Literal["auto_approve", "ignore"]


class SenderRuleResponse(BaseModel):
    """Sender rule details."""

    id: UUID
    sender_domain: Optional[str] = None
    sender_email: Optional[str] = None
    action: str
    created_at: datetime


class CalendarListResponse(BaseModel):
    """Available Google Calendar."""

    id: str
    name: str
    is_primary: bool
    is_selected: bool  # True if this is the target calendar


class CalendarSettingsRequest(BaseModel):
    """Update calendar settings."""

    target_calendar_id: Optional[str] = None
    default_invitees: Optional[str] = None  # Comma-separated emails
    all_day_display_mode: Optional[str] = None
    all_day_custom_start: Optional[str] = None  # HH:MM[:SS]
    all_day_custom_end: Optional[str] = None


class CalendarSettingsResponse(BaseModel):
    """Current calendar settings."""

    target_calendar_id: Optional[str] = None
    target_calendar_name: Optional[str] = None
    default_invitees: Optional[str] = None
    timezone: Optional[str] = None
    all_day_display_mode: str = "all_day"
    all_day_custom_start: Optional[str] = None
    all_day_custom_end: Optional[str] = None


class CalendarSyncResponse(BaseModel):
    """Calendar sync result."""

    event_id: str
    google_calendar_event_id: str
    synced_at: datetime
    status: Literal["synced"]


class EventUnsyncResponse(BaseModel):
    """Calendar unsync result."""

    event_id: str
    status: Literal["pending_review"]


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
    status: Literal["pending_review", "pending_change"]


class EventActionResponse(BaseModel):
    """Result of approve/reject/undo for review or history."""

    event_id: str
    status: str
    deleted: bool = False
