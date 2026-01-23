"""Selko services package - auth, integrations, gmail, emails, attachments."""

from selko.services.auth import get_authenticated_client, get_current_user_id
from selko.services.users import create_user, list_users, delete_user, get_admin_client
from selko.services.integrations import (
    save_oauth_credentials,
    get_oauth_credentials,
    update_integration_status,
)
from selko.services.gmail import (
    run_oauth_flow,
    get_credentials,
    build_service,
    fetch_messages,
    extract_attachments,
)
from selko.services.emails import parse_gmail_message, save_emails
from selko.services.attachments import (
    process_attachment,
    calculate_content_hash,
    check_duplicate_attachment,
    download_gmail_attachment,
    upload_to_storage,
    save_attachment_metadata,
    delete_attachment,
    AttachmentError,
)

__all__ = [
    # auth
    "get_authenticated_client",
    "get_current_user_id",
    # users
    "create_user",
    "list_users",
    "delete_user",
    "get_admin_client",
    # integrations
    "save_oauth_credentials",
    "get_oauth_credentials",
    "update_integration_status",
    # gmail
    "run_oauth_flow",
    "get_credentials",
    "build_service",
    "fetch_messages",
    "extract_attachments",
    # emails
    "parse_gmail_message",
    "save_emails",
    # attachments
    "process_attachment",
    "calculate_content_hash",
    "check_duplicate_attachment",
    "download_gmail_attachment",
    "upload_to_storage",
    "save_attachment_metadata",
    "delete_attachment",
    "AttachmentError",
]
