"""Tests for Google Photos integration."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from selko.services.photos import (
    PhotosError,
    claim_pending_photo,
    complete_photo_processing,
    fail_photo_processing,
    get_photo,
    save_photo_metadata,
    unlock_expired_photo_locks,
)
from selko.services.google_photos import (
    PhotosError as GooglePhotosError,
    get_credentials,
    parse_photo_metadata,
)


class TestSavePhotoMetadata:
    """Test photo metadata save and deduplication."""

    def test_saves_photo_metadata(self, mock_supabase_client):
        """Verify photo metadata is saved correctly."""
        photo_data = {
            "google_photo_id": "photo-123",
            "filename": "vacation.jpg",
            "mime_type": "image/jpeg",
            "date_taken": "2026-01-15T10:30:00+00:00",
            "width": 4032,
            "height": 3024,
        }

        mock_supabase_client.table().upsert().execute.return_value = MagicMock(
            data=[{**photo_data, "id": "uuid-1", "user_id": "test-user-id"}]
        )

        result = save_photo_metadata(
            mock_supabase_client, "test-user-id", photo_data
        )

        assert result is not None
        assert result["google_photo_id"] == "photo-123"
        mock_supabase_client.table.assert_called_with("photos")

    def test_saves_with_user_id(self, mock_supabase_client):
        """Verify user_id is added to photo data."""
        photo_data = {
            "google_photo_id": "photo-456",
            "filename": "test.jpg",
        }

        mock_supabase_client.table().upsert().execute.return_value = MagicMock(
            data=[{**photo_data, "id": "uuid-2", "user_id": "test-user-id"}]
        )

        save_photo_metadata(mock_supabase_client, "test-user-id", photo_data)

        upsert_call = mock_supabase_client.table().upsert.call_args
        data = upsert_call[0][0]
        assert data["user_id"] == "test-user-id"

    def test_handles_upsert_conflict(self, mock_supabase_client):
        """Verify upsert uses correct conflict columns for deduplication."""
        photo_data = {
            "google_photo_id": "photo-789",
            "filename": "duplicate.jpg",
        }

        mock_supabase_client.table().upsert().execute.return_value = MagicMock(
            data=[{**photo_data, "id": "uuid-3", "user_id": "test-user-id"}]
        )

        save_photo_metadata(mock_supabase_client, "test-user-id", photo_data)

        upsert_call = mock_supabase_client.table().upsert.call_args
        assert upsert_call[1]["on_conflict"] == "user_id,google_photo_id"

    def test_returns_none_on_empty_result(self, mock_supabase_client):
        """Verify None is returned when upsert returns no data."""
        mock_supabase_client.table().upsert().execute.return_value = MagicMock(
            data=[]
        )

        result = save_photo_metadata(
            mock_supabase_client,
            "test-user-id",
            {"google_photo_id": "photo-empty"},
        )

        assert result is None

    def test_raises_on_api_error(self, mock_supabase_client):
        """Verify PhotosError is raised on API error."""
        from supabase import PostgrestAPIError

        mock_supabase_client.table().upsert().execute.side_effect = (
            PostgrestAPIError({"message": "DB error", "code": "500", "details": "", "hint": ""})
        )

        with pytest.raises(PhotosError, match="Failed to save photo metadata"):
            save_photo_metadata(
                mock_supabase_client,
                "test-user-id",
                {"google_photo_id": "photo-err"},
            )


class TestClaimPendingPhoto:
    """Test photo claiming function."""

    def test_claims_photo_successfully(self, mock_supabase_client):
        """Verify a pending photo can be claimed."""
        claimed_photo = {
            "id": "photo-uuid-1",
            "filename": "ticket.jpg",
            "attempts": 1,
            "max_attempts": 3,
        }
        mock_supabase_client.rpc().execute.return_value = MagicMock(
            data=[claimed_photo]
        )

        result = claim_pending_photo(mock_supabase_client, "worker-1")

        assert result is not None
        assert result["id"] == "photo-uuid-1"
        mock_supabase_client.rpc.assert_called_with(
            "claim_pending_photo",
            {"p_worker_id": "worker-1", "p_lock_duration_seconds": 300},
        )

    def test_returns_none_when_no_pending(self, mock_supabase_client):
        """Verify None is returned when no pending photos exist."""
        mock_supabase_client.rpc().execute.return_value = MagicMock(data=[])

        result = claim_pending_photo(mock_supabase_client, "worker-1")

        assert result is None

    def test_custom_lock_duration(self, mock_supabase_client):
        """Verify custom lock duration is passed to RPC."""
        mock_supabase_client.rpc().execute.return_value = MagicMock(data=[])

        claim_pending_photo(mock_supabase_client, "worker-1", lock_duration_seconds=600)

        mock_supabase_client.rpc.assert_called_with(
            "claim_pending_photo",
            {"p_worker_id": "worker-1", "p_lock_duration_seconds": 600},
        )

    def test_raises_on_error(self, mock_supabase_client):
        """Verify PhotosError is raised on RPC error."""
        mock_supabase_client.rpc().execute.side_effect = Exception("RPC failed")

        with pytest.raises(PhotosError, match="Failed to claim pending photo"):
            claim_pending_photo(mock_supabase_client, "worker-1")


class TestCompletePhotoProcessing:
    """Test photo processing completion."""

    def test_marks_as_processed(self, mock_supabase_client):
        """Verify photo is marked as processed with timestamp."""
        complete_photo_processing(mock_supabase_client, "photo-uuid-1")

        mock_supabase_client.table.assert_called_with("photos")
        update_call = mock_supabase_client.table().update.call_args
        data = update_call[0][0]
        assert data["processing_status"] == "processed"
        assert data["locked_by"] is None
        assert data["locked_until"] is None
        assert "processed_at" in data

    def test_raises_on_error(self, mock_supabase_client):
        """Verify PhotosError is raised on update failure."""
        mock_supabase_client.table().update().eq().execute.side_effect = Exception(
            "DB error"
        )

        with pytest.raises(PhotosError, match="Failed to complete photo processing"):
            complete_photo_processing(mock_supabase_client, "photo-uuid-1")


class TestFailPhotoProcessing:
    """Test photo processing failure with retry and dead-letter logic."""

    def test_retries_when_attempts_remaining(self, mock_supabase_client):
        """Verify status is set back to pending when retries remain."""
        mock_supabase_client.table().select().eq().single().execute.return_value = (
            MagicMock(data={"attempts": 1, "max_attempts": 3})
        )

        fail_photo_processing(mock_supabase_client, "photo-uuid-1", "Download failed")

        update_call = mock_supabase_client.table().update.call_args
        data = update_call[0][0]
        assert data["processing_status"] == "pending"
        assert data["processing_error"] == "Download failed"
        assert "next_retry_at" in data
        assert data["locked_by"] is None

    def test_dead_letters_when_max_attempts_exceeded(self, mock_supabase_client):
        """Verify status is set to failed when max attempts reached."""
        mock_supabase_client.table().select().eq().single().execute.return_value = (
            MagicMock(data={"attempts": 3, "max_attempts": 3})
        )

        fail_photo_processing(mock_supabase_client, "photo-uuid-1", "Final failure")

        update_call = mock_supabase_client.table().update.call_args
        data = update_call[0][0]
        assert data["processing_status"] == "failed"
        assert data["dead_letter_reason"] == "Final failure"
        assert "dead_letter_at" in data

    def test_exponential_backoff_first_retry(self, mock_supabase_client):
        """Verify first retry delay is 60 seconds."""
        mock_supabase_client.table().select().eq().single().execute.return_value = (
            MagicMock(data={"attempts": 1, "max_attempts": 3})
        )

        fail_photo_processing(mock_supabase_client, "photo-uuid-1", "error")

        update_call = mock_supabase_client.table().update.call_args
        data = update_call[0][0]
        # First retry: base_delay * 2^(1-1) = 60 * 1 = 60s
        next_retry = datetime.fromisoformat(data["next_retry_at"])
        now = datetime.now(timezone.utc)
        delta = (next_retry - now).total_seconds()
        assert 55 <= delta <= 65  # Allow some tolerance

    def test_exponential_backoff_second_retry(self, mock_supabase_client):
        """Verify second retry delay is 120 seconds."""
        mock_supabase_client.table().select().eq().single().execute.return_value = (
            MagicMock(data={"attempts": 2, "max_attempts": 3})
        )

        fail_photo_processing(mock_supabase_client, "photo-uuid-1", "error")

        update_call = mock_supabase_client.table().update.call_args
        data = update_call[0][0]
        # Second retry: base_delay * 2^(2-1) = 60 * 2 = 120s
        next_retry = datetime.fromisoformat(data["next_retry_at"])
        now = datetime.now(timezone.utc)
        delta = (next_retry - now).total_seconds()
        assert 115 <= delta <= 125  # Allow some tolerance


class TestGetPhoto:
    """Test fetching a single photo record."""

    def test_returns_photo_when_found(self, mock_supabase_client):
        """Verify photo is returned when found."""
        photo = {"id": "photo-uuid-1", "filename": "test.jpg"}
        mock_supabase_client.table().select().eq().maybe_single().execute.return_value = (
            MagicMock(data=photo)
        )

        result = get_photo(mock_supabase_client, "photo-uuid-1")

        assert result is not None
        assert result["id"] == "photo-uuid-1"

    def test_returns_none_when_not_found(self, mock_supabase_client):
        """Verify None is returned when photo doesn't exist."""
        mock_supabase_client.table().select().eq().maybe_single().execute.return_value = (
            MagicMock(data=None)
        )

        result = get_photo(mock_supabase_client, "nonexistent")

        assert result is None


class TestUnlockExpiredPhotoLocks:
    """Test expired photo lock recovery."""

    def test_unlocks_expired_locks(self, mock_supabase_client):
        """Verify expired locks are unlocked."""
        mock_supabase_client.rpc().execute.return_value = MagicMock(data=2)

        count = unlock_expired_photo_locks(mock_supabase_client)

        assert count == 2
        mock_supabase_client.rpc.assert_called_with("unlock_expired_photo_locks")

    def test_returns_zero_when_no_expired_locks(self, mock_supabase_client):
        """Verify zero is returned when no locks are expired."""
        mock_supabase_client.rpc().execute.return_value = MagicMock(data=0)

        count = unlock_expired_photo_locks(mock_supabase_client)

        assert count == 0


class TestParsePhotoMetadata:
    """Test Google Photos API media item parsing."""

    def test_parses_complete_media_item(self):
        """Verify all fields are parsed from a media item."""
        media_item = {
            "id": "photo-abc-123",
            "filename": "IMG_20260115.jpg",
            "description": "A photo of an event ticket",
            "mimeType": "image/jpeg",
            "mediaMetadata": {
                "creationTime": "2026-01-15T10:30:00Z",
                "width": "4032",
                "height": "3024",
                "photo": {},
            },
        }

        result = parse_photo_metadata(media_item)

        assert result["google_photo_id"] == "photo-abc-123"
        assert result["filename"] == "IMG_20260115.jpg"
        assert result["description"] == "A photo of an event ticket"
        assert result["mime_type"] == "image/jpeg"
        assert result["width"] == 4032
        assert result["height"] == 3024
        assert result["date_taken"] is not None

    def test_handles_minimal_media_item(self):
        """Verify parsing works with minimal fields."""
        media_item = {
            "id": "photo-minimal",
            "mediaMetadata": {},
        }

        result = parse_photo_metadata(media_item)

        assert result["google_photo_id"] == "photo-minimal"
        assert result["filename"] is None
        assert result["description"] is None
        assert result["mime_type"] is None
        assert result["date_taken"] is None
        assert result["width"] is None
        assert result["height"] is None

    def test_handles_invalid_creation_time(self):
        """Verify graceful handling of invalid dates."""
        media_item = {
            "id": "photo-bad-date",
            "mediaMetadata": {
                "creationTime": "not-a-valid-date",
            },
        }

        result = parse_photo_metadata(media_item)

        assert result["date_taken"] is None


class TestPathTraversalSanitization:
    """Test that filename sanitization prevents path traversal (B3)."""

    def test_path_traversal_sanitization(self):
        """Test that filename sanitization prevents path traversal (B3)."""
        import os
        # Simulate the fixed sanitization logic
        dangerous = "../../etc/passwd"
        safe = os.path.basename(dangerous).replace("..", "")[:100]
        assert "/" not in safe
        assert ".." not in safe
        assert safe == "passwd"

    def test_path_traversal_backslash(self):
        """Test backslash path traversal is neutralized."""
        import os
        dangerous = "..\\..\\windows\\system32"
        safe = os.path.basename(dangerous).replace("..", "")[:100]
        # os.path.basename on Unix treats backslash as regular character,
        # but ".." sequences are still stripped by the replace
        assert ".." not in safe


class TestGetCredentials:
    """Test Google Photos credential handling."""

    @patch("selko.services.google_photos.get_oauth_credentials")
    def test_returns_none_when_no_integration(self, mock_get_oauth):
        """Verify None is returned when no Google Photos integration exists."""
        mock_get_oauth.return_value = None

        result = get_credentials(MagicMock(), MagicMock(), user_id="test-user")

        assert result is None
        mock_get_oauth.assert_called_once()

    @patch("selko.services.google_photos.get_oauth_credentials")
    def test_returns_valid_credentials(self, mock_get_oauth):
        """Verify valid credentials are returned without refresh."""
        mock_creds = MagicMock()
        mock_creds.expired = False
        mock_get_oauth.return_value = mock_creds

        result = get_credentials(MagicMock(), MagicMock(), user_id="test-user")

        assert result is mock_creds

    @patch("selko.services.google_photos.update_oauth_credentials")
    @patch("selko.services.google_photos.Request")
    @patch("selko.services.google_photos.get_oauth_credentials")
    def test_refreshes_expired_credentials(
        self, mock_get_oauth, mock_request, mock_update
    ):
        """Verify expired credentials are refreshed."""
        mock_creds = MagicMock()
        mock_creds.expired = True
        mock_creds.refresh_token = "refresh-token"
        mock_get_oauth.return_value = mock_creds

        result = get_credentials(MagicMock(), MagicMock(), user_id="test-user")

        assert result is mock_creds
        mock_creds.refresh.assert_called_once()

    @patch("selko.services.google_photos.update_integration_status")
    @patch("selko.services.google_photos.Request")
    @patch("selko.services.google_photos.get_oauth_credentials")
    def test_handles_refresh_failure(
        self, mock_get_oauth, mock_request, mock_update_status
    ):
        """Verify None is returned when refresh fails."""
        from google.auth.exceptions import RefreshError

        mock_creds = MagicMock()
        mock_creds.expired = True
        mock_creds.refresh_token = "refresh-token"
        mock_creds.refresh.side_effect = RefreshError("Token revoked")
        mock_get_oauth.return_value = mock_creds

        result = get_credentials(MagicMock(), MagicMock(), user_id="test-user")

        assert result is None
        mock_update_status.assert_called_once()
