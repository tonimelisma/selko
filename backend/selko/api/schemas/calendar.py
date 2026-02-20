"""Calendar event Pydantic schemas for LLM extraction."""

from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, Field


class CalendarEvent(BaseModel):
    """A single calendar event extracted from an email."""

    title: str = Field(description="The event title or name")
    start_datetime: Optional[datetime] = Field(
        None, description="The event start date and time (ISO 8601)"
    )
    end_datetime: Optional[datetime] = Field(
        None, description="The event end date and time (ISO 8601)"
    )
    all_day: bool = Field(False, description="Whether this is an all-day event")
    location: Optional[str] = Field(None, description="The event location or venue")
    description: str = Field(
        description="Detailed description of the event with all relevant information"
    )
    confidence: float = Field(
        description="Confidence score from 0.0 to 1.0 indicating extraction certainty",
        ge=0.0,
        le=1.0,
    )
    importance: Literal["action_required", "fyi"] = Field(
        default="action_required",
        description=(
            "Event importance: 'action_required' for closures, schedule changes, "
            "deadlines the user must act on; 'fyi' for themed days, birthdays, "
            "informational items that are nice to know"
        ),
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
    email_date: datetime = Field(description="The date the email was sent")
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
