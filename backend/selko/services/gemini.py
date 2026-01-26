"""Gemini service for AI-powered calendar event extraction.

Uses Google's Gemini 3 Flash model to analyze email content and attachments,
extracting structured calendar event data.
"""

import logging
import time
from datetime import datetime
from typing import Any, Optional

from google import genai
from google.genai import types
from supabase import Client

from selko.api.schemas.calendar import CalendarEventExtraction
from selko.config import Config

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
) -> CalendarEventExtraction:
    """Extract calendar events from email using Gemini.

    Args:
        client: Initialized Gemini client.
        email_text: Email body text (plain text or HTML).
        email_metadata: Dict with keys: gmail_id, subject, from_name, from_email, date_sent.
        attachments: Optional list of attachment dicts with keys: data (bytes), mime_type.
        model: Gemini model to use (default: gemini-3-flash-preview).
        max_retries: Maximum retries for rate-limited requests.

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
        response_schema=CalendarEventExtraction,
        thinking_config=types.ThinkingConfig(thinking_level="low"),
        # Note: Keep temperature at default 1.0 for Gemini 3
    )

    # Retry loop for rate limiting
    for attempt in range(max_retries):
        try:
            logger.info(f"Calling Gemini {model} for event extraction...")
            response = client.models.generate_content(
                model=model,
                contents=content_parts,
                config=generate_config,
            )

            # Parse Pydantic model directly from response
            result = response.parsed
            logger.info(
                f"Extraction complete: {len(result.events)} events found "
                f"(events_found={result.events_found})"
            )
            return result

        except Exception as e:
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
                    raise GeminiError(
                        f"Failed to extract events after {max_retries} retries (rate limited)"
                    ) from e
            else:
                # Other errors - fail immediately
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
        if "Email not found" in str(e):
            raise
        raise GeminiError(f"Failed to fetch email data: {e}") from e
