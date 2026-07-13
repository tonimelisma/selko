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

# Graph v1.0 does not reliably include wellKnownName in mail-folder list
# responses. Resolve these aliases directly and use their immutable IDs to
# classify localized folder payloads and prevent traversal into forbidden trees.
OUTLOOK_PERMANENT_ALIASES = {
    "junkemail",
    "deleteditems",
    "sentitems",
    "drafts",
    "outbox",
}
OUTLOOK_HIDDEN_SYSTEM_ALIASES = {
    "searchfolders",
    "syncissues",
    "conflicts",
    "localfailures",
    "serverfailures",
    "recoverableitemsroot",
    "recoverableitemsdeletions",
    "recoverableitemspurges",
    "recoverableitemsversions",
    "conversationhistory",
}
OUTLOOK_ELIGIBLE_SYSTEM_ALIASES = {
    "inbox",
    "archive",
    "clutter",
}
OUTLOOK_SYSTEM_ALIASES = (
    OUTLOOK_PERMANENT_ALIASES
    | OUTLOOK_HIDDEN_SYSTEM_ALIASES
    | OUTLOOK_ELIGIBLE_SYSTEM_ALIASES
)
OUTLOOK_SYSTEM_KINDS = {
    "junkemail": "junk",
    "deleteditems": "trash",
    "sentitems": "sent",
    "drafts": "drafts",
    "outbox": "outbox",
    "inbox": "inbox",
    "archive": "archive",
    "clutter": "clutter",
    "conversationhistory": "conversation_history",
}


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


def _graph_prefer(*values: str) -> str:
    return ", ".join(value for value in values if value)


def get_user_profile(access_token: str) -> dict[str, Any]:
    """Fetch the signed-in Microsoft profile."""
    return _graph_get(access_token, f"{GRAPH}/me")


def resolve_well_known_folder_ids(access_token: str) -> dict[str, str]:
    """Resolve Graph folder aliases to immutable IDs.

    Missing aliases are normal for some tenants, so a 404 is ignored. Other
    failures remain fatal because continuing without the exclusion set could
    cause a forbidden tree to be scanned.
    """

    resolved: dict[str, str] = {}
    for alias in sorted(OUTLOOK_SYSTEM_ALIASES):
        try:
            folder = _graph_get(
                access_token,
                f"{GRAPH}/me/mailFolders/{alias}",
                prefer=_graph_prefer('IdType="ImmutableId"'),
            )
        except GraphHttpError as exc:
            if exc.status_code == 404:
                continue
            raise
        folder_id = folder.get("id")
        if folder_id:
            resolved[alias] = str(folder_id)
    return resolved


def fetch_mail_folders(
    access_token: str,
    *,
    resolved_well_known_ids: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Discover the complete Outlook mail-folder hierarchy."""

    resolved = (
        resolved_well_known_ids
        if resolved_well_known_ids is not None
        else resolve_well_known_folder_ids(access_token)
    )
    excluded_ids = {
        folder_id
        for alias, folder_id in resolved.items()
        if alias in OUTLOOK_PERMANENT_ALIASES | OUTLOOK_HIDDEN_SYSTEM_ALIASES
    }
    alias_by_id = {folder_id: alias for alias, folder_id in resolved.items()}
    folders: list[dict[str, Any]] = []
    roots_url = f"{GRAPH}/me/mailFolders"
    roots_params = {"$top": "100", "includeHiddenFolders": "true"}
    pending: list[tuple[str, dict[str, Any] | None]] = [(roots_url, roots_params)]
    while pending:
        url, params = pending.pop(0)
        while url:
            page = _graph_get(
                access_token,
                url,
                params=params,
                prefer=_graph_prefer('IdType="ImmutableId"', "odata.maxpagesize=100"),
            )
            params = None
            for folder in page.get("value", []):
                folder_id = str(folder.get("id") or "")
                # Do not retain or recurse into permanent/hidden roots. Their
                # children are not a source set and may contain recoverable
                # system data that Graph exposes as ordinary folders.
                if not folder_id or folder_id in excluded_ids:
                    continue
                folder = dict(folder)
                if folder_id in alias_by_id:
                    folder["wellKnownName"] = alias_by_id[folder_id]
                folders.append(folder)
                if folder_id:
                    pending.append((
                        f"{GRAPH}/me/mailFolders/{folder_id}/childFolders",
                        {"$top": "100", "includeHiddenFolders": "true"},
                    ))
            url = page.get("@odata.nextLink")
    return folders


def normalize_mail_folders(folders: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Normalize Graph folders into the shared folder persistence shape."""

    by_id = {str(folder.get("id")): folder for folder in folders if folder.get("id")}
    paths: dict[str, str] = {}

    def path_for(folder_id: str, trail: set[str] | None = None) -> str:
        if folder_id in paths:
            return paths[folder_id]
        trail = trail or set()
        if folder_id in trail:
            return str(by_id[folder_id].get("displayName") or folder_id)
        folder = by_id[folder_id]
        name = str(folder.get("displayName") or folder_id)
        parent_id = folder.get("parentFolderId")
        if parent_id and str(parent_id) in by_id:
            path = f"{path_for(str(parent_id), trail | {folder_id})}/{name}"
        else:
            path = name
        paths[folder_id] = path
        return path

    normalized: list[dict[str, Any]] = []
    for folder in folders:
        folder_id = str(folder["id"])
        well_known = str(
            folder.get("wellKnownName")
            or folder.get("well_known_name")
            or ""
        ).lower()
        system_kind = OUTLOOK_SYSTEM_KINDS.get(well_known)
        is_system = well_known in OUTLOOK_SYSTEM_ALIASES
        is_permanently_excluded = (
            well_known in OUTLOOK_PERMANENT_ALIASES
            or well_known in OUTLOOK_HIDDEN_SYSTEM_ALIASES
        )
        normalized.append({
            "id": folder_id,
            "parent_id": folder.get("parentFolderId"),
            "name": folder.get("displayName") or folder_id,
            "full_path": path_for(folder_id),
            "kind": "folder",
            "is_system": is_system,
            "is_scannable": not is_permanently_excluded,
            "is_permanently_excluded": is_permanently_excluded,
            "system_kind": system_kind,
            "well_known_name": well_known,
        })
    return normalized


def fetch_folder_messages(
    access_token: str,
    folder_id: str,
    *,
    since: datetime,
) -> list[dict[str, Any]]:
    """Fetch every message page for an included folder during first sync."""

    url = f"{GRAPH}/me/mailFolders/{folder_id}/messages"
    params: dict[str, Any] | None = {
        "$select": "id,conversationId,parentFolderId,subject,from,toRecipients,receivedDateTime,bodyPreview,body,hasAttachments,isRead,importance,flag",
        "$filter": f"receivedDateTime ge {since.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')}",
        "$orderby": "receivedDateTime desc",
        "$top": "50",
    }
    messages: list[dict[str, Any]] = []
    while url:
        page = _graph_get(
            access_token,
            url,
            params=params,
            prefer=_graph_prefer('IdType="ImmutableId"', "odata.maxpagesize=50", 'outlook.body-content-type="text"'),
        )
        params = None
        messages.extend(page.get("value", []))
        url = page.get("@odata.nextLink")
    return messages


def fetch_message_changes(
    access_token: str,
    delta_link: str | None,
    folder_id: str = "inbox",
    since: datetime | None = None,
    immutable_ids: bool = False,
) -> tuple[list[dict[str, Any]], str]:
    """Fetch one folder's changes and return message IDs plus the next cursor."""
    url = delta_link or f"{GRAPH}/me/mailFolders/{folder_id}/messages/delta"
    params = None if delta_link else {
        "$select": "id,conversationId,parentFolderId",
        "$top": "50",
    }
    if params is not None and since is not None:
        params["$filter"] = (
            "receivedDateTime ge "
            f"{since.astimezone(timezone.utc).isoformat().replace('+00:00', 'Z')}"
        )
    changes: list[dict[str, Any]] = []

    while url:
        try:
            page = _graph_get(
                access_token,
                url,
                params=params,
                prefer=_graph_prefer(
                    'IdType="ImmutableId"' if immutable_ids else "",
                    "odata.maxpagesize=50",
                ),
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
        prefer=_graph_prefer('IdType="ImmutableId"', 'outlook.body-content-type="text"'),
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


def parse_outlook_message(
    msg: dict[str, Any],
    folder_id: str | None = None,
) -> dict[str, Any]:
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
        "is_calendar_invite": "eventmessage" in str(msg.get("@odata.type", "")).lower(),
    }
    if body.get("contentType") == "text" and body.get("content"):
        result["body_text"] = body["content"]
    resolved_folder_id = folder_id or msg.get("parentFolderId")
    if resolved_folder_id:
        result["provider_folder_ids"] = [str(resolved_folder_id)]
    return result
