"""Google Photos service for Selko.

Handles Google Photos OAuth and API interactions for fetching photo metadata
and downloading photo content.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Optional

import httpx
from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
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

# Google Photos read-only scope
SCOPES = ["https://www.googleapis.com/auth/photoslibrary.readonly"]


class PhotosError(Exception):
    """Raised when Google Photos operations fail."""

    pass


def get_credentials(
    client: Client,
    config: Config,
    user_id: Optional[str] = None,
) -> Optional[Credentials]:
    """Get Google Photos credentials from database, refreshing if needed.

    Args:
        client: Authenticated Supabase client.
        config: Configuration with Google OAuth credentials.
        user_id: Optional user ID (required if using service role client).

    Returns:
        Valid Google Credentials, or None if not found.
    """
    creds = get_oauth_credentials(client, config, "google_photos", user_id=user_id)

    if not creds:
        return None

    # Refresh if expired
    if creds.expired and creds.refresh_token:
        try:
            logger.info("Google Photos token expired, refreshing...")
            creds.refresh(Request())

            # Retry save up to 3 times for atomicity
            for attempt in range(3):
                try:
                    update_oauth_credentials(client, "google_photos", creds)
                    logger.info("Google Photos token refreshed and saved")
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
            logger.warning(f"Google Photos token refresh failed: {e}")
            update_integration_status(client, "google_photos", "expired")
            return None

    return creds


def build_service(credentials: Credentials):
    """Build Google Photos API service.

    Note: static_discovery=False is required for Photos Library API
    because it's not in the standard discovery cache.

    Args:
        credentials: Valid Google credentials.

    Returns:
        Google Photos API service object.
    """
    return build(
        "photoslibrary",
        "v1",
        credentials=credentials,
        static_discovery=False,
    )


def fetch_recent_photos(
    client: Client,
    config: Config,
    user_id: Optional[str] = None,
    since_date: Optional[datetime] = None,
    max_results: int = 100,
) -> list[dict[str, Any]]:
    """Fetch recent photos from Google Photos API.

    Uses mediaItems.search() with date filter and pagination.

    Args:
        client: Authenticated Supabase client.
        config: Configuration with Google OAuth credentials.
        user_id: Optional user ID (required if using service role client).
        since_date: Only fetch photos taken after this date.
        max_results: Maximum number of photos to fetch.

    Returns:
        List of photo metadata dicts from Google Photos API.

    Raises:
        PhotosError: If credentials are invalid or API calls fail.
    """
    creds = get_credentials(client, config, user_id=user_id)
    if not creds:
        raise PhotosError("No Google Photos integration found")

    try:
        service = build_service(creds)
    except Exception as e:
        raise PhotosError(f"Failed to build Google Photos service: {e}") from e

    # Build search filters
    body: dict[str, Any] = {
        "pageSize": min(max_results, 100),  # API max is 100 per page
    }

    if since_date:
        # Google Photos API uses date filter format
        body["filters"] = {
            "dateFilter": {
                "ranges": [
                    {
                        "startDate": {
                            "year": since_date.year,
                            "month": since_date.month,
                            "day": since_date.day,
                        },
                        "endDate": {
                            "year": datetime.now(timezone.utc).year,
                            "month": datetime.now(timezone.utc).month,
                            "day": datetime.now(timezone.utc).day,
                        },
                    }
                ]
            }
        }

    all_photos: list[dict[str, Any]] = []

    try:
        while len(all_photos) < max_results:
            result = service.mediaItems().search(body=body).execute()

            items = result.get("mediaItems", [])
            if not items:
                break

            all_photos.extend(items)

            # Check for next page
            next_page_token = result.get("nextPageToken")
            if not next_page_token:
                break

            body["pageToken"] = next_page_token

    except RefreshError as e:
        raise PhotosError(f"Google Photos credentials expired or revoked: {e}") from e
    except HttpError as e:
        raise PhotosError(f"Google Photos API error: {e}") from e

    # Trim to max_results
    all_photos = all_photos[:max_results]

    logger.info(f"Fetched {len(all_photos)} photos from Google Photos")
    return all_photos


def download_photo_bytes(media_item: dict[str, Any]) -> bytes:
    """Download photo at original quality from Google Photos.

    Appends '=d' to baseUrl for original quality download.

    Args:
        media_item: Google Photos media item dict with baseUrl.

    Returns:
        Raw photo bytes.

    Raises:
        PhotosError: If download fails.
    """
    base_url = media_item.get("baseUrl")
    if not base_url:
        raise PhotosError("Media item has no baseUrl")

    # Append =d for original quality download
    download_url = f"{base_url}=d"

    try:
        with httpx.Client(timeout=60.0) as http_client:
            response = http_client.get(download_url)
            response.raise_for_status()
            return response.content

    except httpx.HTTPStatusError as e:
        raise PhotosError(
            f"Failed to download photo: HTTP {e.response.status_code}"
        ) from e
    except httpx.RequestError as e:
        raise PhotosError(f"Failed to download photo: {e}") from e


def parse_photo_metadata(media_item: dict[str, Any]) -> dict[str, Any]:
    """Parse Google Photos API media item into a dict suitable for DB storage.

    Args:
        media_item: Google Photos media item from API.

    Returns:
        Dict with parsed photo metadata.
    """
    metadata = media_item.get("mediaMetadata", {})
    photo_metadata = metadata.get("photo", {})

    # Parse creation time
    date_taken = None
    creation_time = metadata.get("creationTime")
    if creation_time:
        try:
            date_taken = datetime.fromisoformat(
                creation_time.replace("Z", "+00:00")
            ).isoformat()
        except (ValueError, AttributeError):
            pass

    result = {
        "google_photo_id": media_item.get("id"),
        "filename": media_item.get("filename"),
        "description": media_item.get("description"),
        "mime_type": media_item.get("mimeType"),
        "date_taken": date_taken,
        "width": int(metadata.get("width", 0)) or None,
        "height": int(metadata.get("height", 0)) or None,
    }

    return result
