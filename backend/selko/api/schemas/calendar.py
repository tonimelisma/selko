"""Calendar event Pydantic schemas for LLM extraction."""

import re
from datetime import datetime, timedelta
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator


class CalendarEvent(BaseModel):
    """A single calendar event extracted from an email."""

    title: str = Field(description="The event title or name")
    start_datetime: Optional[datetime] = Field(
        None,
        description=(
            "Local wall-clock start in the user's timezone as naive ISO 8601 "
            "(e.g. 2026-09-13T10:00:00). Do not include Z or numeric offsets."
        ),
    )
    end_datetime: Optional[datetime] = Field(
        None,
        description=(
            "Local wall-clock end in the user's timezone as naive ISO 8601 "
            "(e.g. 2026-09-13T14:00:00). Do not include Z or numeric offsets."
        ),
    )

    @field_validator("start_datetime", "end_datetime", mode="before")
    @classmethod
    def sanitize_t24_datetime(cls, v: object) -> object:
        """Fix T24:XX:XX datetimes that some LLMs produce.

        ISO 8601 allows T24:00:00 to mean midnight ending the day, but
        pydantic's datetime parser rejects hour=24. Convert to T00 + 1 day.
        """
        if not isinstance(v, str):
            return v
        m = re.match(r"^(\d{4}-\d{2}-\d{2})T24:(\d{2}:\d{2}.*)$", v)
        if not m:
            return v
        base_date = datetime.strptime(m.group(1), "%Y-%m-%d")
        next_day = base_date + timedelta(days=1)
        return f"{next_day.strftime('%Y-%m-%d')}T00:{m.group(2)}"
    all_day: bool = Field(False, description="Whether this is an all-day event")
    location: Optional[str] = Field(None, description="The event location or venue")
    description: str = Field(
        description="Detailed description of the event with all relevant information"
    )
    # NOTE: This app intentionally has no confidence scoring.
    # LLMs cannot meaningfully self-assess extraction certainty.
    # All extracted events are treated equally.
    importance: Literal["action_required", "fyi"] = Field(
        default="action_required",
        description=(
            "Event importance: 'action_required' for closures, schedule changes, "
            "deadlines the user must act on; 'fyi' for themed days, birthdays, "
            "informational items that are nice to know"
        ),
    )
    recurrence_rule: Optional[str] = Field(
        None,
        description="RFC 5545 RRULE for recurring events (e.g., 'RRULE:FREQ=WEEKLY;BYDAY=MO'). Null for one-time events.",
    )


class EventExtractionResponse(BaseModel):
    """LLM response containing extracted events."""

    events_found: bool = Field(
        description="Whether any calendar events were found in the email"
    )
    events: list[CalendarEvent] = Field(
        default_factory=list, description="List of extracted calendar events"
    )

    model_config = {"json_schema_extra": {"title": "EventExtractionResponse"}}


class CalendarEventExtraction(BaseModel):
    """Complete extraction result from an email analysis.
    
    This combines email metadata (that we already have) with LLM extracted events.
    """

    email_message_id: str = Field(description="The Gmail message ID")
    email_date: Optional[datetime] = Field(
        None, description="The date the email was sent (null if unknown)"
    )
    sender_name: Optional[str] = Field(None, description="Name of the email sender")
    sender_email: str = Field(description="Email address of the sender")
    events_found: bool = Field(
        description="Whether any calendar events were found in the email"
    )
    events: list[CalendarEvent] = Field(
        default_factory=list, description="List of extracted calendar events"
    )
    raw_reasoning: Optional[str] = Field(
        None, description="Optional LLM reasoning process (for debugging)"
    )

    model_config = {"json_schema_extra": {"title": "CalendarEventExtraction"}}
