"""Gemini service for AI-powered calendar event extraction.

Uses Google's Gemini 3 Flash model to analyze email content and attachments,
extracting structured calendar event data.

All LLM calls are logged to the database for auditing and analysis.
"""

import logging
import time
from datetime import datetime
from typing import Any, Optional

from google import genai
from google.genai import types
from supabase import Client

from selko.api.schemas.calendar import CalendarEventExtraction, GeminiEventsResponse
from selko.config import Config
from selko.services.llm_logging import (
    LLMCallContext,
    LLMErrorType,
    LLMLoggingService,
    LLMOperationType,
)

logger = logging.getLogger(__name__)


class GeminiError(Exception):
    """Raised when Gemini operations fail."""

    pass


def get_gemini_client(config: Config) -> genai.Client:
    """Initialize Gemini client with API key.

    Args:
        config: Application configuration with gemini_api_key.

    Returns:
        Initialized Gemini client.

    Raises:
        GeminiError: If API key is missing or client initialization fails.
    """
    if not config.gemini_api_key:
        raise GeminiError(
            "GEMINI_API_KEY not configured. "
            "Get your API key from https://aistudio.google.com/apikey"
        )

    try:
        client = genai.Client(api_key=config.gemini_api_key)
        logger.debug("Initialized Gemini client")
        return client
    except Exception as e:
        raise GeminiError(f"Failed to initialize Gemini client: {e}") from e


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

    prompt = f"""You are an expert at extracting calendar events from emails.

**Current Date:** {current_date}

**Email Metadata:**
- Subject: {subject}
- From: {from_name} <{from_email}>
- Date Sent: {date_sent}

**Instructions:**
1. Analyze the email content and any attachments
2. Extract ALL calendar events mentioned (meetings, appointments, parties, reminders, etc.)
3. For each event, extract:
   - Title (clear, concise event name)
   - Start date/time (parse relative dates like "tomorrow", "next Friday")
   - End date/time (if mentioned)
   - Location (physical address or virtual meeting link)
   - Full description with all relevant details
   - Confidence score (0.0-1.0) based on clarity of information

**Important:**
- If NO calendar events are found, set events_found=false and return empty events list
- Parse dates carefully using the current date as context
- Include uncertainty in confidence scores (e.g., 0.7 if time is ambiguous)
- Be conservative - only extract clear event invitations, not casual mentions

**Examples of events:**
✓ Birthday party invitations
✓ Doctor/dentist appointments
✓ Meeting requests
✓ Conference registrations
✓ Webinar invitations

**NOT events:**
✗ Newsletter content
✗ Receipts or order confirmations (unless they mention an appointment)
✗ General announcements without specific event details
"""
    return prompt


def extract_calendar_events(
    client: genai.Client,
    email_text: str,
    email_metadata: dict[str, Any],
    attachments: Optional[list[dict[str, Any]]] = None,
    model: str = "gemini-3-flash-preview",
    max_retries: int = 3,
    logging_service: Optional[LLMLoggingService] = None,
    user_id: Optional[str] = None,
    email_id: Optional[str] = None,
) -> CalendarEventExtraction:
    """Extract calendar events from email using Gemini.

    Args:
        client: Initialized Gemini client.
        email_text: Email body text (plain text or HTML).
        email_metadata: Dict with keys: gmail_id, subject, from_name, from_email, date_sent.
        attachments: Optional list of attachment dicts with keys: data (bytes), mime_type.
        model: Gemini model to use (default: gemini-3-flash-preview).
        max_retries: Maximum retries for rate-limited requests.
        logging_service: Optional LLM logging service for call auditing.
        user_id: User UUID for logging (required if logging_service provided).
        email_id: Email UUID for logging correlation.

    Returns:
        CalendarEventExtraction with structured event data.

    Raises:
        GeminiError: If extraction fails after retries.
    """
    current_date = datetime.now().strftime("%Y-%m-%d")
    prompt = _build_prompt(email_metadata, current_date)

    # Build multimodal content parts
    # Use simple string format for text content
    content_parts = [
        prompt,
        f"\n**Email Body:**\n{email_text}",
    ]

    # Add attachments if provided
    if attachments:
        for att in attachments:
            data = att.get("data")
            mime_type = att.get("mime_type", "application/octet-stream")
            filename = att.get("filename", "attachment")

            if data and len(data) <= 20 * 1024 * 1024:  # 20MB limit
                try:
                    # Use inline_data dict format for attachments
                    import base64
                    content_parts.append({
                        "inline_data": {
                            "mime_type": mime_type,
                            "data": base64.b64encode(data).decode('utf-8')
                        }
                    })
                    logger.debug(f"Added attachment: {filename} ({mime_type})")
                except Exception as e:
                    logger.warning(f"Failed to add attachment {filename}: {e}")
            else:
                logger.warning(
                    f"Skipping oversized attachment: {filename} ({len(data) if data else 0} bytes)"
                )

    # Configure generation with Gemini 3 best practices
    generate_config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=GeminiEventsResponse,  # Only events, not metadata
        thinking_config=types.ThinkingConfig(thinking_level="low"),
        # Note: Keep temperature at default 1.0 for Gemini 3
    )

    # Build full prompt text for logging
    prompt_for_logging = prompt + f"\n**Email Body:**\n{email_text}"
    if attachments:
        prompt_for_logging += f"\n[{len(attachments)} attachment(s) included]"

    # Retry loop for rate limiting
    for attempt in range(max_retries):
        start_time = time.time()
        try:
            logger.info(f"Calling Gemini {model} for event extraction...")
            response = client.models.generate_content(
                model=model,
                contents=content_parts,
                config=generate_config,
            )

            latency_ms = int((time.time() - start_time) * 1000)

            # Parse Gemini's response (events only)
            gemini_result = response.parsed
            logger.info(
                f"Extraction complete: {len(gemini_result.events)} events found "
                f"(events_found={gemini_result.events_found})"
            )

            # Log successful call
            if logging_service and user_id:
                # Extract token counts if available
                prompt_tokens = None
                completion_tokens = None
                if hasattr(response, 'usage_metadata') and response.usage_metadata:
                    prompt_tokens = getattr(response.usage_metadata, 'prompt_token_count', None)
                    completion_tokens = getattr(response.usage_metadata, 'candidates_token_count', None)

                logging_service.log_success(
                    user_id=user_id,
                    operation_type=LLMOperationType.EXTRACT_EVENTS,
                    model=model,
                    prompt_text=prompt_for_logging,
                    response_text=response.text if hasattr(response, 'text') else str(gemini_result),
                    latency_ms=latency_ms,
                    email_id=email_id,
                    prompt_tokens=prompt_tokens,
                    completion_tokens=completion_tokens,
                )

            # Wrap with email metadata to create full extraction result
            result = CalendarEventExtraction(
                email_message_id=email_metadata.get("gmail_id", ""),
                email_date=email_metadata.get("date_sent", datetime.now().isoformat()),
                sender_name=email_metadata.get("from_name"),
                sender_email=email_metadata.get("from_email", ""),
                events_found=gemini_result.events_found,
                events=gemini_result.events,
            )
            return result

        except Exception as e:
            latency_ms = int((time.time() - start_time) * 1000)
            error_str = str(e).lower()

            # Check for rate limiting
            if "429" in error_str or "rate limit" in error_str or "quota" in error_str:
                if attempt < max_retries - 1:
                    wait_time = (2**attempt) + 1  # 1, 3, 5 seconds
                    logger.warning(
                        f"Rate limited by Gemini API, waiting {wait_time}s "
                        f"(attempt {attempt + 1}/{max_retries})"
                    )
                    time.sleep(wait_time)
                    continue
                else:
                    # Log rate limit failure on final attempt
                    if logging_service and user_id:
                        logging_service.log_failure(
                            user_id=user_id,
                            operation_type=LLMOperationType.EXTRACT_EVENTS,
                            model=model,
                            prompt_text=prompt_for_logging,
                            error_message=str(e),
                            latency_ms=latency_ms,
                            error_type=LLMErrorType.RATE_LIMIT,
                            email_id=email_id,
                        )
                    raise GeminiError(
                        f"Failed to extract events after {max_retries} retries (rate limited)"
                    ) from e
            else:
                # Other errors - log and fail immediately
                if logging_service and user_id:
                    logging_service.log_failure(
                        user_id=user_id,
                        operation_type=LLMOperationType.EXTRACT_EVENTS,
                        model=model,
                        prompt_text=prompt_for_logging,
                        error_message=str(e),
                        latency_ms=latency_ms,
                        error_type=LLMErrorType.API_ERROR,
                        email_id=email_id,
                    )
                raise GeminiError(f"Gemini API error: {e}") from e

    raise GeminiError(f"Failed to extract events after {max_retries} retries")


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
        - email_metadata: Dict with gmail_id, subject, from_name, from_email, date_sent
        - email_text: Email snippet/body text
        - attachments_list: List of dicts with keys: data (bytes), mime_type, filename

    Raises:
        GeminiError: If email not found or attachment fetch fails.
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
            raise GeminiError(f"Email not found: {email_id}")

        email = email_result.data
        logger.debug(f"Fetched email: {email.get('subject', '(no subject)')}")

        # Build metadata
        email_metadata = {
            "gmail_id": email.get("gmail_id", ""),
            "subject": email.get("subject", ""),
            "from_name": email.get("from_name", ""),
            "from_email": email.get("from_email", ""),
            "date_sent": email.get("date_sent", ""),
        }

        # Use snippet as email text (for now - could fetch full body later)
        email_text = email.get("snippet", "")

        # Fetch attachments if any
        attachments = []
        if email.get("has_attachments"):
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
            raise GeminiError(f"Email not found: {email_id}") from e
        if "Email not found" in error_str:
            raise
        raise GeminiError(f"Failed to fetch email data: {e}") from e


def compare_events(
    client: genai.Client,
    new_event: dict[str, Any],
    candidate_events: list[dict[str, Any]],
    model: str = "gemini-3-flash-preview",
    logging_service: Optional[LLMLoggingService] = None,
    user_id: Optional[str] = None,
) -> Optional[str]:
    """Ask LLM if new_event matches any candidate events.

    Uses LLM to determine if a newly extracted event is the same as any
    existing events (for deduplication). This handles cases where the same
    event is mentioned in multiple emails.

    Args:
        client: Initialized Gemini client.
        new_event: Dict with event details (title, start_datetime, location, etc).
        candidate_events: List of existing event dicts from DB with same date.
        model: Gemini model to use.
        logging_service: Optional LLM logging service for call auditing.
        user_id: User UUID for logging (required if logging_service provided).

    Returns:
        Event ID of matched event, or None if no match found.

    Raises:
        GeminiError: If comparison fails.
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

Return the Event ID of the matching event, or "NO_MATCH" if it's a different event.

Output format: Just the Event ID or "NO_MATCH", nothing else.
"""
    
    start_time = time.time()
    try:
        response = client.models.generate_content(
            model=model,
            contents=prompt,
        )

        latency_ms = int((time.time() - start_time) * 1000)
        result = response.text.strip()
        logger.info(f"Event comparison result: {result}")

        # Log successful call
        if logging_service and user_id:
            prompt_tokens = None
            completion_tokens = None
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                prompt_tokens = getattr(response.usage_metadata, 'prompt_token_count', None)
                completion_tokens = getattr(response.usage_metadata, 'candidates_token_count', None)

            logging_service.log_success(
                user_id=user_id,
                operation_type=LLMOperationType.COMPARE_EVENTS,
                model=model,
                prompt_text=prompt,
                response_text=result,
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )

        if result == "NO_MATCH":
            return None

        # Validate the returned ID exists in candidates
        for candidate in candidate_events:
            if str(candidate.get('id')) == result:
                return result

        logger.warning(f"LLM returned unknown event ID: {result}")
        return None

    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        # Log failure
        if logging_service and user_id:
            error_str = str(e).lower()
            error_type = LLMErrorType.API_ERROR
            if "429" in error_str or "rate limit" in error_str:
                error_type = LLMErrorType.RATE_LIMIT

            logging_service.log_failure(
                user_id=user_id,
                operation_type=LLMOperationType.COMPARE_EVENTS,
                model=model,
                prompt_text=prompt,
                error_message=str(e),
                latency_ms=latency_ms,
                error_type=error_type,
            )
        raise GeminiError(f"Event comparison failed: {e}") from e


def merge_event_data(
    client: genai.Client,
    existing_event: dict[str, Any],
    new_extraction: dict[str, Any],
    source_type: str,
    model: str = "gemini-3-flash-preview",
    logging_service: Optional[LLMLoggingService] = None,
    user_id: Optional[str] = None,
) -> dict[str, Any]:
    """Ask LLM to merge new info into existing event.

    Uses LLM to intelligently merge event data from a new email into an
    existing event. Follows rules like preferring specific times over all-day,
    combining descriptions, etc.

    Args:
        client: Initialized Gemini client.
        existing_event: Current event data from DB.
        new_extraction: New event data from email.
        source_type: Type of update (update, cancellation, reminder, etc).
        model: Gemini model to use.
        logging_service: Optional LLM logging service for call auditing.
        user_id: User UUID for logging (required if logging_service provided).

    Returns:
        Dict with merged event data.

    Raises:
        GeminiError: If merge fails.
    """
    prompt = f"""You are merging calendar event data from multiple emails.

**Existing Event:**
- Title: {existing_event.get('title')}
- Start: {existing_event.get('start_datetime')}
- End: {existing_event.get('end_datetime')}
- All Day: {existing_event.get('all_day', False)}
- Location: {existing_event.get('location', 'Not specified')}
- Description: {existing_event.get('description', '')}

**New Information (source type: {source_type}):**
- Title: {new_extraction.get('title')}
- Start: {new_extraction.get('start_datetime')}
- End: {new_extraction.get('end_datetime')}
- All Day: {new_extraction.get('all_day', False)}
- Location: {new_extraction.get('location', 'Not specified')}
- Description: {new_extraction.get('description', '')}

**Merge Rules:**
1. If source_type is "cancellation", prefix title with "CANCELLED: " (if not already)
2. Prefer specific time (e.g., 6-7pm) over all-day
3. Combine descriptions, keeping all relevant info (append new info)
4. Use most specific location (longer address usually better)
5. Keep newer times if they differ (updates)

Output JSON with merged event data:
{{
    "title": "...",
    "start_datetime": "...",
    "end_datetime": "...",
    "all_day": true/false,
    "location": "...",
    "description": "..."
}}
"""
    
    start_time = time.time()
    try:
        generate_config = types.GenerateContentConfig(
            response_mime_type="application/json",
        )

        response = client.models.generate_content(
            model=model,
            contents=prompt,
            config=generate_config,
        )

        latency_ms = int((time.time() - start_time) * 1000)

        import json
        merged = json.loads(response.text)
        logger.info(f"Event merge complete: {merged.get('title')}")

        # Log successful call
        if logging_service and user_id:
            prompt_tokens = None
            completion_tokens = None
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                prompt_tokens = getattr(response.usage_metadata, 'prompt_token_count', None)
                completion_tokens = getattr(response.usage_metadata, 'candidates_token_count', None)

            logging_service.log_success(
                user_id=user_id,
                operation_type=LLMOperationType.MERGE_EVENTS,
                model=model,
                prompt_text=prompt,
                response_text=response.text,
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
            )

        return merged

    except Exception as e:
        latency_ms = int((time.time() - start_time) * 1000)
        # Log failure
        if logging_service and user_id:
            error_str = str(e).lower()
            error_type = LLMErrorType.API_ERROR
            if "429" in error_str or "rate limit" in error_str:
                error_type = LLMErrorType.RATE_LIMIT

            logging_service.log_failure(
                user_id=user_id,
                operation_type=LLMOperationType.MERGE_EVENTS,
                model=model,
                prompt_text=prompt,
                error_message=str(e),
                latency_ms=latency_ms,
                error_type=error_type,
            )
        raise GeminiError(f"Event merge failed: {e}") from e


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
    
    for source in sorted(sources, key=lambda s: s.get('created_at', '')):
        if source.get('is_undone'):
            continue
            
        if source.get('source_type') == 'new_invitation' and not original:
            original = source
        elif source.get('source_type') in ['update', 'cancellation']:
            updates.append(source)
    
    if not original:
        return ""
        
    # Format original email
    sender_name = original.get('email_sender_name') or original.get('email_sender', 'Unknown')
    email_date = original.get('email_date')
    
    try:
        from datetime import datetime
        if isinstance(email_date, str):
            dt = datetime.fromisoformat(email_date.replace('Z', '+00:00'))
        else:
            dt = email_date
        date_str = dt.strftime("%B %d, %Y at %I:%M%p").replace(' 0', ' ').replace('AM', 'am').replace('PM', 'pm')
    except Exception as e:
        logger.debug(f"Date format failed for original email: {e}")
        date_str = str(email_date)
    
    attribution = f"This event was automatically created from an email from {sender_name} on {date_str}"
    
    # Add updates if any
    if updates:
        # Group updates by sender
        update_senders = {}
        for update in updates:
            sender = update.get('email_sender_name') or update.get('email_sender', 'Unknown')
            update_date = update.get('email_date')
            try:
                if isinstance(update_date, str):
                    dt = datetime.fromisoformat(update_date.replace('Z', '+00:00'))
                else:
                    dt = update_date
                date_str = dt.strftime("%B %d").replace(' 0', ' ')
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
