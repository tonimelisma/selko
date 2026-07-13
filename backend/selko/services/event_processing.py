"""LLM service for AI-powered calendar event extraction.

Uses the LLMProvider abstraction to analyze email content and attachments,
extracting structured calendar event data. Supports multiple LLM backends.

All LLM calls go through the LLMGateway for unified logging, rate limiting,
and retry handling.
"""

import json
import logging
from datetime import datetime
from typing import Any, Optional
from zoneinfo import ZoneInfo

from supabase import Client

from selko.api.schemas.calendar import CalendarEventExtraction, EventExtractionResponse
from selko.config import Config
from selko.services.event_diff import EventChangeSet, FieldChange, gate_change_set
from selko.services.llm_gateway import LLMGateway, LLMGatewayError
from selko.services.llm_logging import LLMOperationType
from selko.services.llm_provider import ContentPart, ImageContent

logger = logging.getLogger(__name__)


def looks_like_json_schema(parsed: Any) -> bool:
    """Return True if parsed JSON looks like a schema echo, not extraction data.

    Some models (especially without native json_schema support) echo the
    request schema (`$defs`, `properties`, …) instead of returning events.
    """
    if not isinstance(parsed, dict):
        return False
    if "$defs" in parsed or "$schema" in parsed:
        return True
    # Schema-shaped object without the actual response fields
    if (
        "properties" in parsed
        and "events_found" not in parsed
        and "events" not in parsed
    ):
        return True
    return False



def _build_prompt(email_metadata: dict[str, Any], current_date: str) -> str:
    """Build the system prompt for calendar event extraction.

    Args:
        email_metadata: Dict with email metadata (subject, from, date, etc).
        current_date: Current date in YYYY-MM-DD format for relative date parsing.

    Returns:
        Formatted prompt string.
    """
    subject = email_metadata.get("subject", "(no subject)")
    from_name = email_metadata.get("from_name", "")
    from_email = email_metadata.get("from_email", "unknown")
    date_sent = email_metadata.get("date_sent", "")
    user_timezone = email_metadata.get("user_timezone", "America/New_York")

    prompt = f"""You are an expert at extracting calendar events from emails.

**Current Date:** {current_date}
**User timezone (local wall clock):** {user_timezone}

**Email Metadata:**
- Subject: {subject}
- From: {from_name} <{from_email}>
- Date Sent: {date_sent}

**Instructions:**
1. Analyze the email content and any attachments (including PDFs, images, calendars)
2. Extract ALL calendar events mentioned — meetings, appointments, parties, closures, themed days, deadlines, etc.
3. For each event, extract:
   - Title: clear, descriptive event name
   - Start date/time as a LOCAL wall-clock time in {user_timezone}
   - End date/time as a LOCAL wall-clock time in {user_timezone} (if mentioned)
   - Location: physical address, room, venue, or virtual meeting link. If no specific location is mentioned in the email, set to null. Do NOT infer or guess locations from the organization name or event type.
   - Full description with all relevant details
   - Whether it's an all-day event (true/false)
   - Importance: "action_required" or "fyi" (see classification below)
   - Recurrence rule: for recurring events (weekly meetings, monthly reviews, etc.), provide an RFC 5545 RRULE string (e.g., "RRULE:FREQ=WEEKLY;BYDAY=MO"). Null for one-time events.

**Time rules (critical):**
- Emit start_datetime / end_datetime as naive local ISO strings like 2026-09-13T10:00:00
- Do NOT include Z, +00:00, or any numeric timezone offset — the system applies {user_timezone}
- When an email lists both an Event Time (or doors / show time) AND setup / vendor / cleanup windows, use the Event Time for start/end. Put setup and cleanup only in the description.
- Example: "Event Time: 10:00 AM – 2:00 PM" with "Vendor Set-Up: 7:00 AM – 9:00 AM" → start 10:00, end 14:00 (not 7:00–15:00)

**Importance Classification:**
- **action_required**: Events that require the recipient to take action or change their schedule.
  Examples: closures (school closed, office closed), early dismissals, half days, deadlines,
  appointments, meetings, conferences, registration deadlines, performances to attend.
- **fyi**: Informational events that are nice to know but don't require action.
  Examples: themed dress-up days (pajama day, hat day), staff birthdays, spirit weeks,
  movie days, classroom activities the child participates in without parent involvement.

**Important:**
- If NO calendar events are found, set events_found=false and return empty events list
- Parse dates carefully using the current date as context
- Extract ALL events including themed days and informational items — classify them as "fyi"
- For PDFs: extract events from calendar grids, flyers, and schedules

**Examples of events:**
✓ Birthday party invitations (action_required)
✓ Doctor/dentist appointments (action_required)
✓ Meeting requests (action_required)
✓ School closures (action_required)
✓ Themed dress-up days at school (fyi)
✓ Staff birthdays (fyi)
✓ Conference registrations (action_required)

**NOT events — do NOT extract these:**
An event is something the recipient would put on their personal calendar to attend, participate in, or prepare for.
If the email is purely transactional (receipts, shipping, payments) or administrative (password resets, terms updates, account statements) with no event the recipient needs to attend or prepare for, set events_found=false.

**Extraction rules:**
- Multi-day events (e.g., 3-day conference) should be ONE event with start/end spanning the full duration, not separate per-day events
- Do NOT create separate events for RSVP deadlines, early bird deadlines, or registration cutoffs — note them in the main event's description instead
- Only extract events with explicitly stated dates — do NOT infer dates from holidays, context, or subject lines
"""
    return prompt


def _get_attachment_size_limit(mime_type: str, config: Optional[Config] = None) -> int:
    """Get the size limit for an attachment based on its MIME type.

    PDFs use page-based limits (handled separately via format_conversion),
    so they have no byte-size limit here.

    Args:
        mime_type: MIME type of the attachment.
        config: Optional Config with per-type limits.

    Returns:
        Maximum allowed size in bytes.
    """
    if config is None:
        return 20 * 1024 * 1024  # fallback
    if mime_type == "application/pdf":
        # PDFs use page-based limit via format_conversion, not byte size
        return 100 * 1024 * 1024  # effectively unlimited (100 MB)
    elif mime_type.startswith("image/"):
        return config.max_image_size_for_llm
    else:
        return config.max_other_size_for_llm


def _build_content_parts(
    prompt: str,
    email_text: str,
    attachments: Optional[list[dict[str, Any]]] = None,
    config: Optional[Config] = None,
) -> list[ContentPart]:
    """Build multimodal content parts for LLM.

    Args:
        prompt: The system prompt.
        email_text: Email body text.
        attachments: Optional list of attachment dicts with data, mime_type, filename.
        config: Optional Config for per-type attachment size limits.

    Returns:
        List of ContentPart for the LLM provider.
    """
    content_parts: list[ContentPart] = [
        prompt,
        f"\n**Email Body:**\n{email_text}",
    ]

    # Add attachments if provided
    if attachments:
        for att in attachments:
            data = att.get("data")
            mime_type = att.get("mime_type", "application/octet-stream")
            filename = att.get("filename", "attachment")

            # Skip .ics attachments — raw iCalendar bytes aren't useful to the LLM
            if mime_type == "text/calendar" or filename.lower().endswith(".ics"):
                logger.debug(f"Skipping .ics attachment from LLM: {filename}")
                continue
            size_limit = _get_attachment_size_limit(mime_type, config)

            if data and len(data) <= size_limit:
                try:
                    content_parts.append(ImageContent(
                        data=data,
                        mime_type=mime_type,
                    ))
                    logger.debug(f"Added attachment: {filename} ({mime_type})")
                except Exception as e:
                    logger.warning(f"Failed to add attachment {filename}: {e}")
            else:
                logger.warning(
                    f"Skipping oversized attachment: {filename} "
                    f"({mime_type}, {len(data) if data else 0} bytes, "
                    f"limit {size_limit} bytes)"
                )

    return content_parts


def extract_calendar_events(
    gateway: LLMGateway,
    email_text: str,
    email_metadata: dict[str, Any],
    attachments: Optional[list[dict[str, Any]]] = None,
    max_retries: int = 3,
    config: Optional[Config] = None,
) -> CalendarEventExtraction:
    """Extract calendar events from email using LLM.

    Args:
        gateway: LLMGateway instance (with user/email context already set).
        email_text: Email body text (plain text or HTML).
        email_metadata: Dict with keys: provider_message_id, subject, from_name, from_email, date_sent.
        attachments: Optional list of attachment dicts with keys: data (bytes), mime_type.
        max_retries: Maximum retries for rate-limited requests.
        config: Optional Config for per-type attachment size limits.

    Returns:
        CalendarEventExtraction with structured event data.

    Raises:
        LLMGatewayError: If extraction fails after retries.
    """
    user_tz_name = email_metadata.get("user_timezone", "America/New_York")
    try:
        user_tz = ZoneInfo(user_tz_name)
    except (KeyError, ValueError):
        logger.warning(f"Invalid timezone '{user_tz_name}', falling back to America/New_York")
        user_tz = ZoneInfo("America/New_York")
    current_date = email_metadata.get("current_date_override") or datetime.now(user_tz).strftime("%Y-%m-%d")
    prompt = _build_prompt(email_metadata, current_date)
    content_parts = _build_content_parts(prompt, email_text, attachments, config=config)

    # Use JSON schema for structured output
    json_schema = EventExtractionResponse.model_json_schema()

    try:
        response = gateway.call(
            operation=LLMOperationType.EXTRACT_EVENTS,
            contents=content_parts,
            json_schema=json_schema,
            max_retries=max_retries,
        )

        # Parse response JSON
        parsed = json.loads(response.text, strict=False)
        if looks_like_json_schema(parsed):
            raise LLMGatewayError(
                "LLM returned JSON schema instead of extraction data"
            )
        llm_result = EventExtractionResponse.model_validate(parsed)

        logger.info(
            f"Extraction complete: {len(llm_result.events)} events found "
            f"(events_found={llm_result.events_found})"
        )

        # Wrap with email metadata to create full extraction result
        result = CalendarEventExtraction(
            email_message_id=email_metadata.get("provider_message_id", ""),
            email_date=email_metadata.get("date_sent") or None,
            sender_name=email_metadata.get("from_name"),
            sender_email=email_metadata.get("from_email", ""),
            events_found=llm_result.events_found,
            events=llm_result.events,
        )
        return result

    except LLMGatewayError:
        raise
    except Exception as e:
        raise LLMGatewayError(f"Failed to extract events: {e}") from e


def fetch_email_with_attachments(
    supabase_client: Client,
    email_id: str,
) -> tuple[dict[str, Any], str, list[dict[str, Any]]]:
    """Fetch email and its attachments from Supabase.

    Args:
        supabase_client: Authenticated Supabase client.
        email_id: UUID of email record in database.

    Returns:
        Tuple of (email_metadata, email_text, attachments_list).
        - email_metadata: Dict with provider_message_id, subject, from_name, from_email, date_sent
        - email_text: Email body text (full body_text if available, else snippet)
        - attachments_list: List of dicts with keys: data (bytes), mime_type, filename

    Raises:
        LLMGatewayError: If email not found or attachment fetch fails.
    """
    try:
        # Fetch email record
        email_result = (
            supabase_client.table("emails")
            .select("*")
            .eq("id", email_id)
            .single()
            .execute()
        )

        if not email_result.data:
            raise LLMGatewayError(f"Email not found: {email_id}")

        email = email_result.data
        logger.debug(f"Fetched email: {email.get('subject', '(no subject)')}")

        # Build metadata
        email_metadata = {
            "provider_message_id": email.get("provider_message_id", ""),
            "subject": email.get("subject", ""),
            "from_name": email.get("from_name", ""),
            "from_email": email.get("from_email", ""),
            "date_sent": email.get("date_sent", ""),
            "is_calendar_invite": email.get("is_calendar_invite", False),
        }

        # Use full body text if available, otherwise fall back to snippet
        email_text = email.get("body_text") or email.get("snippet", "")

        # Fetch attachments from storage (all image types are stored at sync time)
        attachments: list[dict[str, Any]] = []
        att_result = (
            supabase_client.table("attachments")
            .select("*")
            .eq("email_id", email_id)
            .execute()
        )

        for att_record in att_result.data:
            storage_path = att_record.get("storage_path")
            if storage_path:
                try:
                    # Download from Supabase Storage
                    data = supabase_client.storage.from_("attachments").download(
                        storage_path
                    )
                    attachments.append(
                        {
                            "data": data,
                            "mime_type": att_record.get("mime_type"),
                            "filename": att_record.get("filename"),
                        }
                    )
                    logger.debug(
                        f"Loaded attachment: {att_record.get('filename')}"
                    )
                except Exception as e:
                    logger.warning(
                        f"Failed to download attachment {storage_path}: {e}"
                    )

        return email_metadata, email_text, attachments

    except Exception as e:
        error_str = str(e)
        # Handle Supabase "no rows" error
        if "PGRST116" in error_str or "0 rows" in error_str:
            raise LLMGatewayError(f"Email not found: {email_id}") from e
        if "Email not found" in error_str:
            raise
        raise LLMGatewayError(f"Failed to fetch email data: {e}") from e


def compare_events(
    gateway: LLMGateway,
    new_event: dict[str, Any],
    candidate_events: list[dict[str, Any]],
) -> Optional[str]:
    """Ask LLM if new_event matches any candidate events.

    Uses LLM to determine if a newly extracted event is the same as any
    existing events (for deduplication). This handles cases where the same
    event is mentioned in multiple emails.

    Args:
        gateway: LLMGateway instance (with user context set).
        new_event: Dict with event details (title, start_datetime, location, etc).
        candidate_events: List of existing event dicts from DB with same date.

    Returns:
        Event ID of matched event, or None if no match found.

    Raises:
        LLMGatewayError: If comparison fails.
    """
    if not candidate_events:
        return None

    prompt = f"""You are comparing calendar events to detect duplicates.

**New Event:**
- Title: {new_event.get('title')}
- Start: {new_event.get('start_datetime')}
- End: {new_event.get('end_datetime')}
- Location: {new_event.get('location', 'Not specified')}
- Description: {new_event.get('description', '')}

**Existing Events (same date):**
"""

    for idx, candidate in enumerate(candidate_events):
        prompt += f"""
{idx + 1}. Event ID: {candidate.get('id')}
   - Title: {candidate.get('title')}
   - Start: {candidate.get('start_datetime')}
   - End: {candidate.get('end_datetime')}
   - Location: {candidate.get('location', 'Not specified')}
   - Description: {candidate.get('description', '')}
"""

    prompt += """
**Question:** Is the new event the same as any of the existing events?

Consider events the same if they refer to the same real-world event, even if:
- Wording is slightly different
- One has more details than the other
- Time changed slightly (updates)

Return the matching Event ID (or null if no match) and brief reasoning.
"""

    compare_schema = {
        "type": "object",
        "properties": {
            "matched_event_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "reasoning": {"type": "string"},
        },
        "required": ["matched_event_id", "reasoning"],
    }

    try:
        response = gateway.call(
            operation=LLMOperationType.COMPARE_EVENTS,
            contents=[prompt],
            json_schema=compare_schema,
        )

        parsed = json.loads(response.text, strict=False)
        matched_id = parsed.get("matched_event_id")
        reasoning = parsed.get("reasoning", "")
        logger.info(f"Event comparison result: {matched_id} ({reasoning})")

        if matched_id is None:
            return None

        # Validate the returned ID exists in candidates
        matched_id_str = str(matched_id)
        for candidate in candidate_events:
            if str(candidate.get("id")) == matched_id_str:
                return matched_id_str

        logger.warning(f"LLM returned unknown event ID: {matched_id_str}")
        return None

    except LLMGatewayError:
        raise
    except Exception as e:
        raise LLMGatewayError(f"Event comparison failed: {e}") from e


def propose_event_update(
    gateway: LLMGateway,
    baseline: dict[str, Any],
    extracted_event: dict[str, Any],
    *,
    email_subject: Optional[str] = None,
    email_snippet: Optional[str] = None,
    user_timezone: Optional[str] = None,
    email_date_sent: Optional[str] = None,
    baseline_info_date: Optional[str] = None,
) -> EventChangeSet:
    """Ask LLM what fields to update on a matched existing event.

    Returns a structured changeset (kind + field changes). Callers should run
    ``gate_change_set`` to drop no-op / equivalent diffs.

    Calendar response notifications (Accepted/Declined/Tentative) that merely
    restate the existing event should return kind=noop with empty changes.
    """
    from selko.services.civil_time import to_civil_iso

    tz = user_timezone or "America/New_York"

    def _civil(value: Any) -> Any:
        if value is None or value == "":
            return value
        civil = to_civil_iso(value, tz)
        return civil if civil is not None else value

    prompt = f"""You are proposing updates to an existing calendar event based on a new email.

All times below are local wall-clock times in {tz} (no timezone offsets).
Compare civil clock times only — do not convert timezones.

**Existing event (baseline — already on the user's calendar or in Selko):**
- Title: {baseline.get('title')}
- Start: {_civil(baseline.get('start_datetime'))}
- End: {_civil(baseline.get('end_datetime'))}
- All day: {baseline.get('all_day', False)}
- Location: {baseline.get('location', 'Not specified')}
- Description: {baseline.get('description', '')}
- Status: {baseline.get('status', 'unknown')}

**Newly extracted event fields from the email:**
- Title: {extracted_event.get('title')}
- Start: {_civil(extracted_event.get('start_datetime'))}
- End: {_civil(extracted_event.get('end_datetime'))}
- All day: {extracted_event.get('all_day', False)}
- Location: {extracted_event.get('location', 'Not specified')}
- Description: {extracted_event.get('description', '')}
"""
    if email_date_sent:
        prompt += f"\n**This email was sent:** {email_date_sent}\n"
    if baseline_info_date:
        prompt += f"**The event's current information is from an email sent:** {baseline_info_date}\n"
    if email_subject:
        prompt += f"\n**Email subject:** {email_subject}\n"
    if email_snippet:
        prompt += f"\n**Email context (snippet):** {email_snippet[:1500]}\n"

    prompt += f"""
**Task:** Decide whether this email requires updating the existing event.

Rules:
1. If the email is only an RSVP / calendar response (Accepted:, Declined:, Tentative:,
   METHOD:REPLY) that restates the same meeting with no real time/place/title change →
   kind=noop, changes=[].
2. If the email cancels the event → kind=cancellation, include a status change to "cancelled".
3. If time, place, title, or all_day actually change → kind=material_update with those fields.
4. If only description / extra details are new → kind=enrichment.
5. List ONLY fields that should change. Each change must include before (from baseline),
   after (new value), and a short reason.
6. Do NOT invent changes. Same local wall-clock times are NOT changes (ignore offset spelling).
7. Do NOT clear fields the email omitted.
8. When start/end in the extracted fields disagree with an explicit "Event Time" in the
   description, prefer the Event Time and treat matching Event Time as noop for times.
9. Emit after values as naive local datetimes in {tz} (e.g. 2026-09-13T10:00:00) — never Z or +00:00.
10. If this email is OLDER than the event's current information, it must NOT
    change title, start/end, all_day, or location. At most kind=enrichment
    with a description addition. When it adds nothing new → kind=noop.
11. Do NOT propose a title change when both titles describe the same
    real-world event. Rewording, reordering, or adding a role/subtitle
    qualifier (e.g. "- Advocacy Table", "(Recruiter)") is NOT a title change.
    Only propose title when the organizer renamed or materially changed the
    event itself.
12. Description changes must use mode="append" with ONLY the new information
    as a short paragraph — never restate the existing description. Use
    mode="replace" only for organizer-issued corrections or cancellations.

Return JSON with kind, changes[], and reasoning.
"""

    propose_schema = {
        "type": "object",
        "properties": {
            "kind": {
                "type": "string",
                "enum": ["noop", "enrichment", "material_update", "cancellation"],
            },
            "changes": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "field": {
                            "type": "string",
                            "enum": [
                                "start_datetime",
                                "end_datetime",
                                "all_day",
                                "location",
                                "title",
                                "description",
                                "status",
                                "importance",
                            ],
                        },
                        "before": {},
                        "after": {},
                        "reason": {"type": "string"},
                        "mode": {"type": "string", "enum": ["append", "replace"]},
                    },
                    "required": ["field", "after"],
                },
            },
            "reasoning": {"type": "string"},
        },
        "required": ["kind", "changes", "reasoning"],
    }

    try:
        response = gateway.call(
            operation=LLMOperationType.PROPOSE_EVENT_UPDATE,
            contents=[prompt],
            json_schema=propose_schema,
        )
        parsed = json.loads(response.text, strict=False)
        changes: list[FieldChange] = []
        for item in parsed.get("changes") or []:
            field = item.get("field")
            if not field:
                continue
            try:
                changes.append(
                    FieldChange(
                        field=field,
                        before=item.get("before", baseline.get(field)),
                        after=item.get("after"),
                        reason=item.get("reason"),
                        mode=item.get("mode"),
                    )
                )
            except Exception:
                logger.warning("Skipping invalid proposed change: %s", item)
                continue

        raw = EventChangeSet(
            kind=parsed.get("kind") or "noop",
            changes=changes,
            reasoning=parsed.get("reasoning"),
        )
        gated = gate_change_set(raw, baseline, user_timezone=tz)
        logger.info(
            "Propose update: llm_kind=%s gated_kind=%s changes=%d (%s)",
            raw.kind,
            gated.kind,
            len(gated.changes),
            gated.reasoning or "",
        )
        return gated

    except LLMGatewayError:
        raise
    except Exception as e:
        raise LLMGatewayError(f"Event update proposal failed: {e}") from e


def merge_event_data(
    gateway: LLMGateway,
    existing_event: dict[str, Any],
    new_extraction: dict[str, Any],
    source_type: str,
) -> dict[str, Any]:
    """Ask LLM to merge new info into existing event.

    Uses LLM to intelligently merge event data from a new email into an
    existing event. Follows rules like preferring specific times over all-day,
    combining descriptions, etc.

    Args:
        gateway: LLMGateway instance (with user context set).
        existing_event: Current event data from DB.
        new_extraction: New event data from email.
        source_type: Type of update (update, cancellation, reminder, etc).

    Returns:
        Dict with merged event data.

    Raises:
        LLMGatewayError: If merge fails.
    """
    prompt = f"""You are merging calendar event data from multiple emails.

**Existing Event:**
- Title: {existing_event.get('title')}
- Start: {existing_event.get('start_datetime')}
- End: {existing_event.get('end_datetime')}
- All Day: {existing_event.get('all_day', False)}
- Location: {existing_event.get('location', 'Not specified')}
- Description: {existing_event.get('description', '')}
- Importance: {existing_event.get('importance', 'action_required')}

**New Information (source type: {source_type}):**
- Title: {new_extraction.get('title')}
- Start: {new_extraction.get('start_datetime')}
- End: {new_extraction.get('end_datetime')}
- All Day: {new_extraction.get('all_day', False)}
- Location: {new_extraction.get('location', 'Not specified')}
- Description: {new_extraction.get('description', '')}
- Importance: {new_extraction.get('importance', 'action_required')}

**Merge Rules:**
1. If source_type is "cancellation", prefix title with "CANCELLED: " (if not already)
2. Prefer specific time (e.g., 6-7pm) over all-day
3. Combine descriptions, keeping all relevant info (append new info)
4. Use most specific location (longer address usually better)
5. Keep newer times if they differ (updates)
6. For importance: keep the highest level (action_required > fyi)

Output JSON with merged event data:
{{
    "title": "...",
    "start_datetime": "...",
    "end_datetime": "...",
    "all_day": true/false,
    "location": "...",
    "description": "...",
    "importance": "action_required" or "fyi"
}}
"""

    # Use JSON schema for merge response
    merge_schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "start_datetime": {"type": "string"},
            "end_datetime": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "all_day": {"type": "boolean"},
            "location": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "description": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "importance": {"type": "string", "enum": ["action_required", "fyi"]},
        },
        "required": ["title", "start_datetime", "all_day", "importance"],
    }

    try:
        response = gateway.call(
            operation=LLMOperationType.MERGE_EVENTS,
            contents=[prompt],
            json_schema=merge_schema,
        )

        merged = json.loads(response.text, strict=False)
        logger.info(f"Event merge complete: {merged.get('title')}")
        return merged

    except json.JSONDecodeError as e:
        raise LLMGatewayError(f"Event merge failed: invalid JSON response: {e}") from e
    except LLMGatewayError:
        raise
    except Exception as e:
        raise LLMGatewayError(f"Event merge failed: {e}") from e


def generate_source_attribution(sources: list[dict[str, Any]]) -> str:
    """Generate natural English source attribution for calendar event.

    Creates attribution like: "This event was automatically created from an email
    from WCSD on Jan 25th, 2026 at 1:30pm and updated based on emails from WC PTA
    on Jan 26th and 28th."

    Args:
        sources: List of event_source dicts with email metadata.

    Returns:
        Natural English attribution string.
    """
    if not sources:
        return ""

    # Find the original invitation (first non-undone source)
    original = None
    updates = []

    for source in sorted(sources, key=lambda s: s.get("created_at", "")):
        if source.get("is_undone"):
            continue

        if source.get("source_type") == "new_invitation" and not original:
            original = source
        elif source.get("source_type") in ["update", "cancellation"]:
            updates.append(source)

    if not original:
        return ""

    # Format original email
    sender_name = original.get("email_sender_name") or original.get(
        "email_sender", "Unknown"
    )
    email_date = original.get("email_date")

    try:
        if isinstance(email_date, str):
            dt = datetime.fromisoformat(email_date.replace("Z", "+00:00"))
        else:
            dt = email_date
        date_str = (
            dt.strftime("%B %d, %Y at %I:%M%p")
            .replace(" 0", " ")
            .replace("AM", "am")
            .replace("PM", "pm")
        )
    except Exception as e:
        logger.debug(f"Date format failed for original email: {e}")
        date_str = str(email_date)

    attribution = (
        f"This event was automatically created from an email from "
        f"{sender_name} on {date_str}"
    )

    # Add updates if any
    if updates:
        # Group updates by sender
        update_senders: dict[str, list[str]] = {}
        for update in updates:
            sender = update.get("email_sender_name") or update.get(
                "email_sender", "Unknown"
            )
            update_date = update.get("email_date")
            try:
                if isinstance(update_date, str):
                    dt = datetime.fromisoformat(update_date.replace("Z", "+00:00"))
                else:
                    dt = update_date
                date_str = dt.strftime("%B %d").replace(" 0", " ")
            except Exception as e:
                logger.debug(f"Date format failed for update email: {e}")
                date_str = str(update_date)

            if sender not in update_senders:
                update_senders[sender] = []
            update_senders[sender].append(date_str)

        # Format updates
        update_parts = []
        for sender, dates in update_senders.items():
            dates_str = " and ".join(dates)
            update_parts.append(f"{sender} on {dates_str}")

        updates_str = " and ".join(update_parts)
        attribution += f" and updated based on emails from {updates_str}"

    attribution += "."
    return attribution
