"""Gmail service for Selko.

Handles Gmail OAuth flow and API interactions.
"""

import logging
import time
from typing import Optional

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from supabase import Client

from selko.config import Config
from selko.services.integrations import (
    get_oauth_credentials,
    update_integration_status,
    update_oauth_credentials,
)

logger = logging.getLogger(__name__)

# Gmail read-only scope
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class GmailError(Exception):
    """Raised when Gmail operations fail."""

    pass


def run_oauth_flow(config: Config) -> Credentials:
    """Run OAuth flow for Gmail access.

    Opens a browser window for the user to authenticate.

    Args:
        config: Configuration with Google OAuth client credentials.

    Returns:
        Google Credentials object with tokens.

    Raises:
        GmailError: If client credentials not configured or flow fails.
    """
    if not config.google_client_id or not config.google_client_secret:
        raise GmailError(
            "Google OAuth client credentials not configured.\n"
            "Set GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET in your .env file."
        )

    try:
        # Use fixed port 8080 for OAuth redirect so Web app clients work
        # (Web app clients require exact redirect URI match including port)
        redirect_uri = "http://localhost:8080"
        client_config = {
            "installed": {
                "client_id": config.google_client_id,
                "client_secret": config.google_client_secret,
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "redirect_uris": [redirect_uri],
            }
        }
        flow = InstalledAppFlow.from_client_config(client_config, SCOPES)

        logger.info("Opening browser for authentication...")
        logger.info("If browser doesn't open, visit the URL shown below.")

        creds = flow.run_local_server(port=8080, prompt="consent")
        logger.info("OAuth flow completed successfully")
        return creds

    except ValueError as e:
        raise GmailError(f"Invalid OAuth configuration: {e}") from e


def get_credentials(
    client: Client,
    config: Config,
    user_id: Optional[str] = None,
) -> Optional[Credentials]:
    """Get Gmail credentials from database, refreshing if needed.

    Args:
        client: Authenticated Supabase client.
        config: Configuration with Google OAuth credentials.
        user_id: Optional user ID (required if using service role client).

    Returns:
        Valid Google Credentials, or None if not found.
    """
    creds = get_oauth_credentials(client, config, "gmail", user_id=user_id)

    if not creds:
        return None

    # Refresh if expired
    if creds.expired and creds.refresh_token:
        try:
            logger.info("Token expired, refreshing...")
            creds.refresh(Request())

            # Save refreshed token to database
            update_oauth_credentials(client, "gmail", creds)
            logger.info("Token refreshed and saved")

        except RefreshError as e:
            logger.warning(f"Token refresh failed: {e}")
            update_integration_status(client, "gmail", "expired")
            return None

    return creds


def build_service(credentials: Credentials):
    """Build Gmail API service.

    Args:
        credentials: Valid Google credentials.

    Returns:
        Gmail API service object.
    """
    return build("gmail", "v1", credentials=credentials)


def get_user_profile(service) -> dict:
    """Get Gmail user profile.

    Args:
        service: Gmail API service.

    Returns:
        Profile dict with emailAddress, messagesTotal, etc.

    Raises:
        GmailError: If profile fetch fails or credentials are invalid.
    """
    try:
        return service.users().getProfile(userId="me").execute()
    except RefreshError as e:
        raise GmailError(f"Gmail credentials expired or revoked: {e}") from e
    except HttpError as e:
        raise GmailError(f"Gmail API error: {e}") from e


def extract_attachments(email: dict) -> list[dict]:
    """Extract attachment metadata from Gmail message.

    Recursively parses MIME multipart structure to find all attachments.

    Args:
        email: Full Gmail message object from API.

    Returns:
        List of attachment dicts with keys:
        - attachment_id: Gmail attachment ID
        - filename: Original filename
        - mime_type: MIME type
        - size_bytes: Size in bytes (from Gmail metadata)

    Note:
        Does NOT download attachment data - only extracts metadata.
    """
    attachments = []

    def _extract_from_part(part: dict) -> None:
        """Recursively extract attachments from a MIME part."""
        # Check if this part has an attachment
        body = part.get("body", {})
        attachment_id = body.get("attachmentId")
        filename = part.get("filename", "")

        if attachment_id and filename:
            attachments.append(
                {
                    "attachment_id": attachment_id,
                    "filename": filename,
                    "mime_type": part.get("mimeType", "application/octet-stream"),
                    "size_bytes": body.get("size", 0),
                }
            )
            logger.debug(f"Found attachment: {filename}")

        # Recursively check nested parts (for multipart messages)
        for nested_part in part.get("parts", []):
            _extract_from_part(nested_part)

    # Start with the payload
    payload = email.get("payload", {})
    _extract_from_part(payload)

    logger.debug(f"Extracted {len(attachments)} attachments from message {email.get('id')}")
    return attachments


# Map MIME image subtypes to file extensions
_MIME_EXT_MAP = {
    "image/jpeg": "jpg",
    "image/png": "png",
    "image/gif": "gif",
    "image/webp": "webp",
    "image/bmp": "bmp",
    "image/tiff": "tiff",
}


def extract_inline_images(email: dict) -> list[dict]:
    """Extract inline image metadata from Gmail message MIME parts.

    Finds image parts that have Content-ID headers (CID references) or
    Content-Disposition: inline, but lack filenames — which causes
    extract_attachments() to skip them.

    Args:
        email: Full Gmail message object from API.

    Returns:
        List of dicts with keys:
        - attachment_id: Gmail attachment ID (for downloading)
        - filename: Synthetic filename (e.g., "inline_0.png")
        - mime_type: Image MIME type
        - size_bytes: Size from Gmail metadata
        - content_id: The CID value (without angle brackets), or None
    """
    inline_images = []
    index = 0

    def _extract_from_part(part: dict) -> None:
        nonlocal index
        body = part.get("body", {})
        attachment_id = body.get("attachmentId")
        mime_type = part.get("mimeType", "")
        filename = part.get("filename", "")

        # Only consider image parts with a downloadable attachment ID
        if attachment_id and mime_type.startswith("image/"):
            # Skip parts that extract_attachments() already handles (have filename)
            if not filename:
                headers = {
                    h["name"].lower(): h["value"]
                    for h in part.get("headers", [])
                }
                content_id = headers.get("content-id", "")
                disposition = headers.get("content-disposition", "")

                # Must have CID header or inline disposition
                if content_id or "inline" in disposition.lower():
                    # Strip angle brackets from Content-ID
                    cid = content_id.strip("<>") if content_id else None
                    ext = _MIME_EXT_MAP.get(mime_type, "bin")
                    synthetic_name = f"inline_{index}.{ext}"

                    inline_images.append({
                        "attachment_id": attachment_id,
                        "filename": synthetic_name,
                        "mime_type": mime_type,
                        "size_bytes": body.get("size", 0),
                        "content_id": cid,
                    })
                    logger.debug(f"Found inline image: {synthetic_name} (CID: {cid})")
                    index += 1

        # Recurse into nested parts
        for nested_part in part.get("parts", []):
            _extract_from_part(nested_part)

    payload = email.get("payload", {})
    _extract_from_part(payload)

    if inline_images:
        logger.debug(
            f"Extracted {len(inline_images)} inline images from message {email.get('id')}"
        )
    return inline_images


def fetch_messages(
    service,
    max_results: int = 10,
    label_ids: list[str] = None,
    max_retries: int = 3,
) -> list[dict]:
    """Fetch email messages from Gmail with rate limit handling.

    Args:
        service: Gmail API service.
        max_results: Maximum number of messages to fetch.
        label_ids: Optional list of label IDs to filter by.
        max_retries: Maximum retries for rate-limited requests.

    Returns:
        List of full message objects.

    Raises:
        GmailError: If credentials are invalid or API calls fail.
    """
    if label_ids is None:
        label_ids = ["INBOX"]

    try:
        results = (
            service.users()
            .messages()
            .list(userId="me", labelIds=label_ids, maxResults=max_results)
            .execute()
        )
    except RefreshError as e:
        raise GmailError(f"Gmail credentials expired or revoked: {e}") from e
    except HttpError as e:
        raise GmailError(f"Gmail API error listing messages: {e}") from e

    messages = results.get("messages", [])
    if not messages:
        logger.info("No messages found")
        return []

    logger.debug(f"Found {len(messages)} message IDs, fetching full details")

    # Fetch full message details with rate limiting
    full_messages = []
    for i, msg in enumerate(messages):
        for attempt in range(max_retries):
            try:
                full_msg = (
                    service.users()
                    .messages()
                    .get(userId="me", id=msg["id"], format="full")
                    .execute()
                )
                full_messages.append(full_msg)
                break
            except RefreshError as e:
                raise GmailError(f"Gmail credentials expired or revoked: {e}") from e
            except HttpError as e:
                if e.resp.status == 429:  # Rate limited
                    wait_time = (2**attempt) + 1  # 1, 3, 5 seconds
                    logger.warning(
                        f"Rate limited, waiting {wait_time}s "
                        f"(attempt {attempt + 1}/{max_retries})"
                    )
                    time.sleep(wait_time)
                else:
                    raise GmailError(f"Gmail API error fetching message: {e}") from e

        # Small delay between requests to avoid hitting rate limits
        if i < len(messages) - 1:
            time.sleep(0.1)

    logger.info(f"Fetched {len(full_messages)} messages")
    return full_messages
