"""Gmail service for Selko.

Handles Gmail OAuth flow and API interactions.
"""

from typing import Optional

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from supabase import Client

from selko.config import Config
from selko.services.integrations import (
    get_oauth_credentials,
    update_integration_status,
    update_oauth_credentials,
)

# Gmail read-only scope
SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class GmailError(Exception):
    """Raised when Gmail operations fail."""

    pass


def run_oauth_flow(config: Config) -> Credentials:
    """Run OAuth flow for Gmail access.

    Opens a browser window for the user to authenticate.

    Args:
        config: Configuration with credentials file path.

    Returns:
        Google Credentials object with tokens.

    Raises:
        GmailError: If credentials file not found or flow fails.
    """
    if not config.credentials_file.exists():
        raise GmailError(
            f"Credentials file not found: {config.credentials_file}\n"
            "Download OAuth client credentials from Google Cloud Console "
            "and save as 'credentials.json' in the cli/ directory."
        )

    try:
        flow = InstalledAppFlow.from_client_secrets_file(
            str(config.credentials_file), SCOPES
        )

        print("Opening browser for authentication...")
        print("If browser doesn't open, visit the URL shown below.\n")

        creds = flow.run_local_server(port=0)
        return creds

    except Exception as e:
        raise GmailError(f"OAuth flow failed: {e}") from e


def get_credentials(
    client: Client,
    config: Config,
) -> Optional[Credentials]:
    """Get Gmail credentials from database, refreshing if needed.

    Args:
        client: Authenticated Supabase client.
        config: Configuration with Google OAuth credentials.

    Returns:
        Valid Google Credentials, or None if not found.
    """
    creds = get_oauth_credentials(client, config, "gmail")

    if not creds:
        return None

    # Refresh if expired
    if creds.expired and creds.refresh_token:
        try:
            print("Token expired, refreshing...")
            creds.refresh(Request())

            # Save refreshed token to database
            update_oauth_credentials(client, "gmail", creds)
            print("Token refreshed and saved.")

        except Exception as e:
            print(f"Token refresh failed: {e}")
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
    """
    return service.users().getProfile(userId="me").execute()


def fetch_messages(
    service,
    max_results: int = 10,
    label_ids: list[str] = None,
) -> list[dict]:
    """Fetch email messages from Gmail.

    Args:
        service: Gmail API service.
        max_results: Maximum number of messages to fetch.
        label_ids: Optional list of label IDs to filter by.

    Returns:
        List of full message objects.
    """
    if label_ids is None:
        label_ids = ["INBOX"]

    results = (
        service.users()
        .messages()
        .list(userId="me", labelIds=label_ids, maxResults=max_results)
        .execute()
    )

    messages = results.get("messages", [])
    if not messages:
        print("No messages found.")
        return []

    # Fetch full message details
    full_messages = []
    for msg in messages:
        full_msg = (
            service.users()
            .messages()
            .get(userId="me", id=msg["id"], format="full")
            .execute()
        )
        full_messages.append(full_msg)

    return full_messages
