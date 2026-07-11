"""Microsoft Graph service for Outlook email ingestion.

This module owns the Microsoft OAuth flow and the Inbox delta-sync helpers.
Parsed messages intentionally use the same provider-agnostic shape as Gmail
messages so the downstream email and event-processing pipeline is shared.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Any

import msal
import requests
from supabase import Client

from selko.config import Config
from selko.services.auth import get_current_user_id
from selko.services.integrations import (
    get_provider_integration,
    update_integration_status,
    update_provider_tokens,
)

logger = logging.getLogger(__name__)

GRAPH = "https://graph.microsoft.com/v1.0"
AUTHORITY = "https://login.microsoftonline.com/common"
SCOPES = ["Mail.Read", "User.Read"]
RESYNC_REQUIRED = "__outlook_resync_required__"


class OutlookError(Exception):
    """Raised when Microsoft Graph or OAuth operations fail."""


class GraphHttpError(OutlookError):
    """Microsoft Graph error that preserves the HTTP status code."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


def _require_config(config: Config) -> None:
    if not config.microsoft_client_id or not config.microsoft_client_secret:
        raise OutlookError(
            "Microsoft OAuth client credentials not configured. "
            "Set MICROSOFT_CLIENT_ID and MICROSOFT_CLIENT_SECRET."
        )


def _msal_app(config: Config) -> msal.ConfidentialClientApplication:
    """Create the confidential MSAL client used for code and refresh flows."""
    _require_config(config)
    return msal.ConfidentialClientApplication(
        client_id=config.microsoft_client_id,
        client_credential=config.microsoft_client_secret,
        authority=AUTHORITY,
    )


def build_auth_url(config: Config, state: str, redirect_uri: str) -> str:
    """Build a Microsoft authorization-code URL."""
    try:
        return _msal_app(config).get_authorization_request_url(
            scopes=SCOPES,
            state=state,
            redirect_uri=redirect_uri,
            prompt="select_account",
        )
    except Exception as exc:
        raise OutlookError(f"Failed to build Microsoft authorization URL: {exc}") from exc


def exchange_code(config: Config, code: str, redirect_uri: str) -> dict[str, Any]:
    """Exchange an authorization code for Microsoft tokens."""
    try:
        result = _msal_app(config).acquire_token_by_authorization_code(
            code=code,
            scopes=SCOPES,
            redirect_uri=redirect_uri,
        )
    except Exception as exc:
        raise OutlookError(f"Microsoft token exchange failed: {exc}") from exc

    if not result or result.get("error"):
        description = (result or {}).get("error_description") or (result or {}).get("error")
        raise OutlookError(f"Microsoft token exchange failed: {description or 'unknown error'}")
    return result


def _parse_expiry(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        logger.warning("Ignoring invalid Outlook token expiry: %s", value)
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def get_access_token(
    client: Client,
    config: Config,
    user_id: str | None = None,
) -> str | None:
    """Load an Outlook token and refresh it when it has expired."""
    if user_id is None:
        user_id = get_current_user_id(client)

    try:
        row = get_provider_integration(client, "outlook", user_id=user_id)
    except Exception as exc:
        raise OutlookError(f"Failed to load Outlook integration: {exc}") from exc

    if not row or row.get("status") in ("expired", "revoked", "error"):
        return None

    expiry = _parse_expiry(row.get("token_expiry"))
    if row.get("access_token") and expiry and expiry > datetime.now(timezone.utc):
        return row["access_token"]

    refresh_token = row.get("refresh_token")
    if not refresh_token:
        update_integration_status(client, "outlook", "expired", user_id=user_id)
        raise OutlookError("Outlook integration has no refresh token")

    try:
        refreshed = _msal_app(config).acquire_token_by_refresh_token(
            refresh_token,
            scopes=SCOPES,
        )
    except Exception as exc:
        raise OutlookError(f"Outlook token refresh failed: {exc}") from exc

    if not refreshed or refreshed.get("error"):
        if (refreshed or {}).get("error") == "invalid_grant":
            update_integration_status(client, "outlook", "expired", user_id=user_id)
        description = (refreshed or {}).get("error_description") or (refreshed or {}).get("error")
        raise OutlookError(f"Outlook token refresh failed: {description or 'unknown error'}")

    access_token = refreshed.get("access_token")
    if not access_token:
        raise OutlookError("Outlook token refresh returned no access token")

    expires_in = int(refreshed.get("expires_in", 3600))
    token_expiry = datetime.now(timezone.utc) + timedelta(seconds=expires_in)
    update_provider_tokens(
        client,
        "outlook",
        access_token=access_token,
        refresh_token=refreshed.get("refresh_token") or refresh_token,
        token_expiry=token_expiry,
        user_id=user_id,
    )
    return access_token


def _graph_get(
    access_token: str,
    url: str,
    *,
    params: dict[str, Any] | None = None,
    prefer: str | None = None,
) -> dict[str, Any]:
    """GET a Microsoft Graph JSON resource."""
    headers = {"Authorization": f"Bearer {access_token}"}
    if prefer:
        headers["Prefer"] = prefer

    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
    except requests.RequestException as exc:
        raise OutlookError(f"Microsoft Graph request failed: {exc}") from exc

    if response.status_code >= 400:
        try:
            detail = response.json().get("error", {}).get("message")
        except (TypeError, ValueError):
            detail = None
        raise GraphHttpError(
            response.status_code,
            f"Microsoft Graph returned HTTP {response.status_code}: {detail or response.text}",
        )

    try:
        return response.json()
    except ValueError as exc:
        raise OutlookError("Microsoft Graph returned invalid JSON") from exc


def get_user_profile(access_token: str) -> dict[str, Any]:
    """Fetch the signed-in Microsoft profile."""
    return _graph_get(access_token, f"{GRAPH}/me")


def fetch_message_changes(
    access_token: str,
    delta_link: str | None,
) -> tuple[list[dict[str, Any]], str]:
    """Fetch Inbox changes and return message IDs plus the next delta cursor."""
    url = delta_link or f"{GRAPH}/me/mailFolders/inbox/messages/delta"
    params = None if delta_link else {
        "$select": "id,conversationId",
        "$top": "50",
    }
    changes: list[dict[str, Any]] = []

    while url:
        try:
            page = _graph_get(
                access_token,
                url,
                params=params,
                prefer="odata.maxpagesize=50",
            )
        except GraphHttpError as exc:
            if exc.status_code == 410:
                logger.info("Outlook delta cursor expired; a full resync is required")
                return [], RESYNC_REQUIRED
            raise

        params = None
        for item in page.get("value", []):
            message_id = item.get("id")
            if message_id:
                changes.append({
                    "id": message_id,
                    "removed": bool(item.get("@removed")),
                })

        url = page.get("@odata.nextLink")
        if not url:
            return changes, page.get("@odata.deltaLink", "")

    return changes, ""


def get_full_message(access_token: str, message_id: str) -> dict[str, Any]:
    """Fetch one Outlook message with a plain-text body."""
    return _graph_get(
        access_token,
        f"{GRAPH}/me/messages/{message_id}",
        prefer='outlook.body-content-type="text"',
    )


def list_attachments(access_token: str, message_id: str) -> list[dict[str, Any]]:
    """List inline and regular file attachments for one Outlook message."""
    result = _graph_get(
        access_token,
        f"{GRAPH}/me/messages/{message_id}/attachments",
    )
    return result.get("value", [])


def synthesize_labels(msg: dict[str, Any]) -> list[str]:
    """Map Outlook state into the Gmail-style provider label tokens."""
    labels: list[str] = []
    if msg.get("isRead") is False:
        labels.append("UNREAD")
    if str(msg.get("importance", "")).lower() == "high":
        labels.append("IMPORTANT")
    if (msg.get("flag") or {}).get("flagStatus") == "flagged":
        labels.append("STARRED")
    return labels


def parse_outlook_message(msg: dict[str, Any]) -> dict[str, Any]:
    """Convert a Graph message into the provider-agnostic email DB shape."""
    sender = (msg.get("from") or {}).get("emailAddress") or {}
    recipients = []
    for recipient in msg.get("toRecipients", []):
        address = (recipient.get("emailAddress") or {}).get("address")
        if address:
            recipients.append(address)

    body = msg.get("body") or {}
    result: dict[str, Any] = {
        "email_provider": "outlook",
        "provider_message_id": msg["id"],
        "thread_id": msg.get("conversationId"),
        "subject": msg.get("subject"),
        "from_email": sender.get("address"),
        "from_name": sender.get("name") or None,
        "to_emails": recipients or None,
        "date_sent": msg.get("receivedDateTime"),
        "snippet": msg.get("bodyPreview"),
        "provider_labels": synthesize_labels(msg),
        "has_attachments": bool(msg.get("hasAttachments")),
        "body_html": None,
    }
    if body.get("contentType") == "text" and body.get("content"):
        result["body_text"] = body["content"]
    return result
