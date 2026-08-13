"""Gmail service for Selko.

Handles Gmail OAuth flow and API interactions.
"""

import base64
import binascii
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from supabase import Client

from selko.config import Config
from selko.services.egress import GMAIL, record_egress
from selko.services.google_errors import google_error_reason
from selko.services.integrations import (
    get_oauth_credentials,
    update_integration_status,
    update_oauth_credentials,
)

logger = logging.getLogger(__name__)

# Gmail read-only scope
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class GmailError(Exception):
    """Raised when Gmail operations fail.

    Unlike the earlier bare ``Exception``, this preserves the structured HTTP
    ``status_code`` and Google's structured ``reason`` so callers can branch on
    type/structure instead of substring-matching the human-readable message.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        reason: str | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.reason = reason


class GmailAuthError(GmailError):
    """Raised when Gmail credentials cannot be used (expired/revoked).

    Auth is a *type*, not a string: the ingestion classifier branches on this
    subclass so an expired refresh token never dead-letters mail on the first
    attempt and is reported as a provider auth failure instead.
    """


class GmailHistoryExpiredError(GmailError):
    """Raised when Gmail no longer retains the requested history cursor."""

    pass


class GmailMessageNotFoundError(GmailError):
    """Raised when a history entry refers to a message deleted before fetch."""

    pass


def _wrap_http_error(e: HttpError, *, prefix: str) -> GmailError:
    """Re-raise an HttpError as a GmailError carrying its status/reason."""
    return GmailError(
        f"{prefix}: {e}",
        status_code=getattr(e.resp, "status", None),
        reason=google_error_reason(e),
    )


def _auth_error(e: RefreshError, *, prefix: str) -> GmailAuthError:
    """Re-raise a RefreshError as a GmailAuthError (typed auth failure)."""
    return GmailAuthError(f"{prefix}: {e}")


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


def get_gmail_credentials(
    client: Client,
    config: Config,
    user_id: Optional[str] = None,
) -> Optional[Credentials]:
    """Get Gmail credentials from database, refreshing if needed.

    Renamed from get_credentials (8c) to disambiguate from
    selko.services.integrations.get_credentials which has an incompatible
    signature (client, user_id, provider). The old name is kept as an alias
    for backwards compat with tests that patch the import path.

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

            # Retry save up to 3 times for atomicity
            for attempt in range(3):
                try:
                    update_oauth_credentials(
                        client, "gmail", creds, user_id=user_id
                    )
                    logger.info("Token refreshed and saved")
                    break
                except Exception as save_err:
                    logger.error(
                        "Failed to save refreshed token (attempt %d): %s",
                        attempt + 1,
                        save_err,
                    )
                    if attempt == 2:
                        logger.error(
                            "CRITICAL: Refreshed token could not be saved after 3 attempts"
                        )

        except RefreshError as e:
            logger.warning(f"Token refresh failed: {e}")
            update_integration_status(
                client, "gmail", "expired", user_id=user_id
            )
            return None

    return creds


# Backwards-compat alias: old name was get_credentials, new name is
# get_gmail_credentials (8c). Keep the old import path working so existing
# patches (selko.services.gmail.get_credentials) and callers that have not
# yet migrated do not break. New code should import get_gmail_credentials.
get_credentials = get_gmail_credentials


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
        raise GmailAuthError(f"Gmail credentials expired or revoked: {e}") from e
    except HttpError as e:
        raise _wrap_http_error(e, prefix="Gmail API error") from e


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


def extract_inline_calendar_parts(email: dict) -> list[bytes]:
    """Return inline ``text/calendar`` MIME bodies from a full Gmail message."""
    payloads: list[bytes] = []

    def _walk(part: dict) -> None:
        if str(part.get("mimeType", "")).lower() == "text/calendar":
            data = (part.get("body") or {}).get("data")
            if data:
                try:
                    padding = "=" * (-len(data) % 4)
                    payloads.append(base64.urlsafe_b64decode(data + padding))
                except (ValueError, binascii.Error):
                    logger.warning("Malformed inline calendar body ignored")
        for nested in part.get("parts", []):
            _walk(nested)

    _walk(email.get("payload", {}))
    return payloads


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


# Default Gmail search: inbox + archive + Primary/Updates, skip noisy tabs
# and outbound/drafts. Spam/trash are also excluded by API default.
DEFAULT_MESSAGE_QUERY = (
    "-in:spam -in:trash -in:drafts -in:sent "
    "-category:promotions -category:social -category:forums"
)


def build_initial_sync_query(
    excluded_label_names: list[str] | None = None,
    *,
    days: int = 14,
) -> str:
    """Build the bounded first-sync search used by reliable ingestion."""

    since = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y/%m/%d")
    terms = [f"after:{since}", DEFAULT_MESSAGE_QUERY]
    for name in excluded_label_names or []:
        # Gmail accepts label names in quotes; escape quotes in a user label.
        safe_name = str(name).replace('"', '\\"')
        terms.append(f'-label:"{safe_name}"')
    return " ".join(terms)


def list_labels(service) -> list[dict]:
    """Return every Gmail label, following all API pages."""

    labels: list[dict] = []
    page_token: str | None = None
    while True:
        kwargs = {"userId": "me"}
        if page_token:
            kwargs["pageToken"] = page_token
        try:
            page = service.users().labels().list(**kwargs).execute()
        except RefreshError as e:
            raise GmailAuthError(f"Gmail credentials expired or revoked: {e}") from e
        except HttpError as e:
            raise _wrap_http_error(e, prefix="Gmail API error listing labels") from e
        labels.extend(page.get("labels", []))
        page_token = page.get("nextPageToken")
        if not page_token:
            return labels


def list_message_ids(
    service,
    *,
    query: str,
    page_size: int = 500,
) -> list[dict]:
    """List all message IDs for a search, draining every result page."""

    message_ids: list[dict] = []
    page_token: str | None = None
    while True:
        kwargs = {"userId": "me", "maxResults": page_size, "q": query}
        if page_token:
            kwargs["pageToken"] = page_token
        try:
            page = service.users().messages().list(**kwargs).execute()
        except RefreshError as e:
            raise GmailAuthError(f"Gmail credentials expired or revoked: {e}") from e
        except HttpError as e:
            raise _wrap_http_error(e, prefix="Gmail API error listing messages") from e
        message_ids.extend(page.get("messages", []))
        page_token = page.get("nextPageToken")
        if not page_token:
            return message_ids


def get_message_metadata(service, message_id: str) -> dict:
    """Fetch only labels and identity before deciding whether content is eligible."""

    try:
        return (
            service.users()
            .messages()
            .get(
                userId="me",
                id=message_id,
                format="metadata",
            )
            .execute()
        )
    except RefreshError as e:
        raise _auth_error(e, prefix="Gmail credentials expired or revoked") from e
    except HttpError as e:
        if getattr(e.resp, "status", None) == 404:
            raise GmailMessageNotFoundError(
                f"Gmail message {message_id} no longer exists"
            ) from e
        raise _wrap_http_error(e, prefix="Gmail API error fetching message metadata") from e


def get_messages_metadata_batch(service, message_ids: Iterable[str], *, batch_size: int = 100) -> dict[str, dict]:
    """Fetch metadata for many messages in one batch per ``batch_size`` IDs.

    Discovery used to call ``get_message_metadata`` once per message in a plain
    ``for`` loop; acquisition later called ``get_full_message`` for the same
    message, so discovery cost two API calls per message with no batching and
    no concurrency. Gmail's ``BatchHttpRequest`` collapses N calls into
    ceil(N/100) HTTP requests — one quota round-trip per 100 messages and a
    material ~100x reduction on a 20k-message weekly reconciliation pass.

    Returns ``{message_id: metadata_dict}``. Per-message failures (the most
    common is 404 — ``GmailMessageNotFoundError`` — when a discovered message
    was deleted before metadata fetch) are returned as ``{"id": id,
    "_deleted": True}`` so the caller can decide whether to mark the message
    ``removed`` rather than ``upsert``. The whole batch raises if the
    underlying transport fails (e.g. auth or 5xx, which break the whole batch).
    """
    results: dict[str, dict] = {}
    ids = [mid for mid in message_ids if mid]
    if not ids:
        return results

    # R2: never raise inside the callback — some googleapiclient versions swallow
    # per-request callback exceptions. Capture per-request outcomes as values
    # and resolve after execute().
    per_request_errors: list[BaseException] = []

    def _on_message(request_id, response, exception):  # noqa: ANN001
        if exception is None:
            results[request_id] = response
            return
        if isinstance(exception, RefreshError):
            per_request_errors.append(_auth_error(exception, prefix="Gmail credentials expired or revoked"))
            return
        if isinstance(exception, HttpError):
            if getattr(exception.resp, "status", None) == 404:
                # The message was deleted between listing and metadata fetch.
                # The serial path raised GmailMessageNotFoundError here and the
                # caller mapped it to `removed`; keep that outcome per message
                # instead of failing the whole batch.
                results[request_id] = {"id": request_id, "_deleted": True}
                return
            per_request_errors.append(_wrap_http_error(exception, prefix="Gmail API error batch metadata"))
            return
        # Anything else (transport, parsing) is not per-message recoverable.
        per_request_errors.append(GmailError(f"Gmail API error batch metadata: {exception}"))

    for chunk in _chunks(ids, batch_size):
        per_request_errors.clear()
        batch = service.new_batch_http_request()
        for mid in chunk:
            batch.add(
                service.users().messages().get(userId="me", id=mid, format="metadata"),
                callback=_on_message,
                request_id=mid,
            )
        try:
            batch.execute()
        except RefreshError as e:
            raise _auth_error(e, prefix="Gmail credentials expired or revoked") from e
        except HttpError as e:
            raise _wrap_http_error(e, prefix="Gmail API error batch metadata") from e
        if per_request_errors:
            # Auth aborts the whole discover — no partial progress is safe
            for err in per_request_errors:
                if isinstance(err, GmailAuthError):
                    raise err
            # One transient in a 100-chunk must not silently disappear; raise
            # a batch-level transient so classify_email_error → provider_transient
            # and the caller retries via backoff. Successful ids in this chunk
            # are preserved in `results` for the caller to commit before retry
            # (see R4 chunk-level retry), but raising here surfaces the partial
            # failure now — the next pass will re-fetch the failed identities
            # via the resumable known_provider_message_ids filter.
            raise GmailError(
                f"Gmail batch metadata partial failure ({len(per_request_errors)}/{len(chunk)})",
                status_code=500,
            )
    return results


def _chunks(values: Iterable[Any], size: int = 100) -> Iterable[list[Any]]:
    chunk: list[Any] = []
    for value in values:
        chunk.append(value)
        if len(chunk) == size:
            yield chunk
            chunk = []
    if chunk:
        yield chunk


def get_full_message(service, message_id: str) -> dict:
    """Fetch full message content only after label eligibility was established."""

    try:
        message = service.users().messages().get(
            userId="me", id=message_id, format="full"
        ).execute()
        # `sizeEstimate` is Gmail's own byte estimate for the message and is a
        # far better proxy for what crossed the wire than the size of the parsed
        # dict. This is the counter that answers "how much mail did we actually
        # download", as opposed to how much polling chatter we generated.
        record_egress(
            GMAIL,
            "GET /gmail/v1/users/me/messages/{id}?format=full",
            response_bytes=int(message.get("sizeEstimate") or 0),
        )
        return message
    except RefreshError as e:
        raise GmailAuthError(f"Gmail credentials expired or revoked: {e}") from e
    except HttpError as e:
        if getattr(e.resp, "status", None) == 404:
            raise GmailMessageNotFoundError(
                f"Gmail message {message_id} no longer exists"
            ) from e
        raise _wrap_http_error(e, prefix="Gmail API error fetching message") from e


def fetch_history_message_ids(
    service,
    start_history_id: str,
) -> tuple[list[str], str]:
    """Drain Gmail History pages and return changed message IDs plus new cursor."""

    message_ids: set[str] = set()
    page_token: str | None = None
    latest_history_id = start_history_id
    while True:
        kwargs = {
            "userId": "me",
            "startHistoryId": start_history_id,
            "historyTypes": ["messageAdded", "labelAdded", "labelRemoved", "messageDeleted"],
        }
        if page_token:
            kwargs["pageToken"] = page_token
        try:
            page = service.users().history().list(**kwargs).execute()
        except RefreshError as e:
            raise GmailAuthError(f"Gmail credentials expired or revoked: {e}") from e
        except HttpError as e:
            if getattr(e.resp, "status", None) == 404:
                raise GmailHistoryExpiredError(
                    f"Gmail history cursor {start_history_id} expired"
                ) from e
            raise _wrap_http_error(e, prefix="Gmail API error reading history") from e

        latest_history_id = page.get("historyId") or latest_history_id
        for entry in page.get("history", []):
            latest_history_id = entry.get("id") or latest_history_id
            for key in ("messagesAdded", "labelsAdded", "labelsRemoved", "messagesDeleted"):
                for item in entry.get(key, []):
                    message = item.get("message", item)
                    if message.get("id"):
                        message_ids.add(message["id"])
            for message in entry.get("messages", []):
                if message.get("id"):
                    message_ids.add(message["id"])

        page_token = page.get("nextPageToken")
        if not page_token:
            return sorted(message_ids), page.get("historyId") or latest_history_id


def fetch_messages(
    service,
    max_results: int = 10,
    label_ids: list[str] = None,
    query: str = DEFAULT_MESSAGE_QUERY,
    max_retries: int = 3,
) -> list[dict]:
    """Fetch email messages from Gmail with rate limit handling.

    By default, fetches recent mail across the mailbox (not INBOX-only) while
    excluding spam, trash, drafts, sent, promotions, social, and forums.
    Many users archive aggressively, so INBOX-only pulls return nothing even
    when recent actionable mail exists under category/archive labels.

    Args:
        service: Gmail API service.
        max_results: Maximum number of messages to fetch.
        label_ids: Optional list of label IDs to filter by. None means no
            label filter. Pass ["INBOX"] to restrict to the inbox.
        query: Gmail search query. Defaults to DEFAULT_MESSAGE_QUERY.
            Pass an empty string to disable the search filter.
        max_retries: Maximum retries for rate-limited requests.

    Returns:
        List of full message objects.

    Raises:
        GmailError: If credentials are invalid or API calls fail.
    """
    list_kwargs: dict = {
        "userId": "me",
        "maxResults": max_results,
    }
    if label_ids is not None:
        list_kwargs["labelIds"] = label_ids
    if query:
        list_kwargs["q"] = query

    try:
        results = (
            service.users()
            .messages()
            .list(**list_kwargs)
            .execute()
        )
    except RefreshError as e:
        raise GmailAuthError(f"Gmail credentials expired or revoked: {e}") from e
    except HttpError as e:
        raise _wrap_http_error(e, prefix="Gmail API error listing messages") from e

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
                raise GmailAuthError(f"Gmail credentials expired or revoked: {e}") from e
            except HttpError as e:
                if e.resp.status == 429:  # Rate limited
                    wait_time = (2**attempt) + 1  # 1, 3, 5 seconds
                    logger.warning(
                        f"Rate limited, waiting {wait_time}s "
                        f"(attempt {attempt + 1}/{max_retries})"
                    )
                    time.sleep(wait_time)
                else:
                    raise _wrap_http_error(e, prefix="Gmail API error fetching message") from e

        # Small delay between requests to avoid hitting rate limits
        if i < len(messages) - 1:
            time.sleep(0.1)

    logger.info(f"Fetched {len(full_messages)} messages")
    return full_messages
