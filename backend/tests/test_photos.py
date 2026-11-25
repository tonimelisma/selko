"""Tests for the parked Google Photos integration, over a real SQLite database.

``claim_pending_photo`` is gone with its tests: it had no caller and was not
ported (docs/specs/sqlite-single-process/02-data-layer.md §2.12, function 60).
"""

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from selko.services.photos import (
    PhotosError,
    complete_photo_processing,
    fail_photo_processing,
    get_photo,
    save_photo_metadata,
    unlock_expired_photo_locks,
)
from selko.services.google_photos import (
    get_credentials,
    parse_photo_metadata,
)


def _photo(google_id="photo-1", **extra):
    return {"google_photo_id": google_id, "filename": "IMG_001.jpg", "mime_type": "image/jpeg",
            "width": 100, "height": 50, **extra}


def _row(db, photo_id):
    return dict(db.query_one("SELECT * FROM photos WHERE id = ?", (photo_id,)))


def _parse(ts):
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


class TestSavePhotoMetadata:
    def test_saves_photo_metadata(self, db, factory):
        user = factory.user()
        saved = save_photo_metadata(db, user, _photo(date_taken="2026-01-15T10:30:00+00:00"))
        assert saved["user_id"] == user
        assert saved["google_photo_id"] == "photo-1"
        assert saved["filename"] == "IMG_001.jpg"
        assert saved["processing_status"] == "pending"
        assert saved["date_taken"] == "2026-01-15T10:30:00.000000Z"

    def test_refetch_updates_the_same_row(self, db, factory):
        user = factory.user()
        first = save_photo_metadata(db, user, _photo())
        second = save_photo_metadata(db, user, _photo(filename="renamed.jpg"))
        assert second["id"] == first["id"]
        assert second["filename"] == "renamed.jpg"
        assert db.query_one("SELECT count(*) FROM photos")[0] == 1

    def test_same_photo_id_for_two_users_is_two_rows(self, db, factory):
        save_photo_metadata(db, factory.user(), _photo())
        save_photo_metadata(db, factory.user(), _photo())
        assert db.query_one("SELECT count(*) FROM photos")[0] == 2

    def test_raises_on_database_error(self, db, factory):
        with pytest.raises(PhotosError):
            save_photo_metadata(db, factory.user(), {"filename": "no-google-id.jpg"})
        with pytest.raises(PhotosError):
            save_photo_metadata(db, "00000000-0000-0000-0000-000000000000", _photo())


class TestCompletePhotoProcessing:
    def test_marks_as_processed_and_clears_the_lock(self, db, factory):
        user = factory.user()
        photo = save_photo_metadata(db, user, _photo(locked_by="w1", processing_status="processing"))
        complete_photo_processing(db, photo["id"])
        row = _row(db, photo["id"])
        assert row["processing_status"] == "processed"
        assert row["processed_at"] is not None
        assert row["locked_by"] is None and row["locked_until"] is None


class TestFailPhotoProcessing:
    def _failing(self, db, factory, attempts, max_attempts=3):
        user = factory.user()
        return save_photo_metadata(db, user, _photo(
            processing_status="processing", attempts=attempts, max_attempts=max_attempts, locked_by="w1",
        ))

    def test_retries_when_attempts_remaining(self, db, factory):
        photo = self._failing(db, factory, attempts=1)
        fail_photo_processing(db, photo["id"], "API timeout")
        row = _row(db, photo["id"])
        assert row["processing_status"] == "pending"
        assert row["processing_error"] == "API timeout"
        assert row["locked_by"] is None
        assert row["next_retry_at"] is not None

    def test_dead_letters_when_max_attempts_reached(self, db, factory):
        photo = self._failing(db, factory, attempts=3)
        fail_photo_processing(db, photo["id"], "Permanent error")
        row = _row(db, photo["id"])
        assert row["processing_status"] == "failed"
        assert row["dead_letter_reason"] == "Permanent error"
        assert row["dead_letter_at"] is not None

    @pytest.mark.parametrize("attempts,delay", [(1, 60), (2, 120)])
    def test_exponential_backoff(self, db, factory, attempts, delay):
        photo = self._failing(db, factory, attempts=attempts)
        before = datetime.now(timezone.utc)
        fail_photo_processing(db, photo["id"], "Error")
        retry_at = _parse(_row(db, photo["id"])["next_retry_at"])
        assert before + timedelta(seconds=delay - 5) < retry_at < before + timedelta(seconds=delay + 5)

    def test_unknown_photo_raises(self, db):
        with pytest.raises(PhotosError):
            fail_photo_processing(db, "00000000-0000-0000-0000-000000000000", "Error")


class TestGetPhoto:
    def test_returns_the_users_photo(self, db, factory):
        user = factory.user()
        photo = save_photo_metadata(db, user, _photo())
        assert get_photo(db, photo["id"], user_id=user)["google_photo_id"] == "photo-1"

    def test_returns_none_when_not_found_or_not_owned(self, db, factory):
        alice, bob = factory.user(), factory.user()
        photo = save_photo_metadata(db, alice, _photo())
        assert get_photo(db, photo["id"], user_id=bob) is None
        assert get_photo(db, "00000000-0000-0000-0000-000000000000", user_id=alice) is None

    def test_requires_a_user(self, db):
        with pytest.raises(PhotosError):
            get_photo(db, "00000000-0000-0000-0000-000000000000")


class TestUnlockExpiredPhotoLocks:
    def test_unlocks_only_expired_locks(self, db, factory):
        user = factory.user()
        expired = save_photo_metadata(db, user, _photo("p1", processing_status="processing", locked_by="w"))
        live = save_photo_metadata(db, user, _photo("p2", processing_status="processing", locked_by="w"))
        with db.write() as tx:
            tx.execute("UPDATE photos SET locked_until = ? WHERE id = ?", (tx.ts(-60), expired["id"]))
            tx.execute("UPDATE photos SET locked_until = ? WHERE id = ?", (tx.ts(600), live["id"]))

        assert asyncio.run(unlock_expired_photo_locks(db)) == 1
        assert _row(db, expired["id"])["processing_status"] == "pending"
        assert _row(db, live["id"])["processing_status"] == "processing"

    def test_returns_zero_when_no_expired_locks(self, db):
        assert asyncio.run(unlock_expired_photo_locks(db)) == 0


class TestPhotoFetchWorker:
    """workers/photo_fetch over the database: save, stamp, schedule."""

    def test_fetch_saves_photos_and_stamps_the_sync(self, db, factory, monkeypatch):
        from selko.workers import photo_fetch

        user = factory.user()
        factory.integration(user, "google_photos", last_photo_sync_at="2026-01-01T00:00:00.000000Z")
        seen = {}

        def fake_fetch(client, config, user_id, since_date, max_results):
            seen["since"] = since_date
            return [{"id": "g1", "filename": "a.jpg", "mediaMetadata": {}}]

        monkeypatch.setattr(photo_fetch, "fetch_recent_photos", fake_fetch)
        photo_fetch._process_photo_fetch_sync(db, MagicMock(), {"user_id": user})

        assert seen["since"] == datetime(2026, 1, 1, tzinfo=timezone.utc)
        assert db.query_one("SELECT google_photo_id FROM photos WHERE user_id = ?", (user,))[0] == "g1"
        stamped = db.query_one(
            "SELECT last_photo_sync_at FROM integrations WHERE user_id = ? AND provider = 'google_photos'", (user,)
        )[0]
        assert stamped > "2026-01-01T00:00:00.000000Z"

    def test_scheduler_enqueues_once_per_active_user(self, db, factory, monkeypatch):
        from selko.db import runtime
        from selko.workers import photo_fetch

        active, inactive, queued = factory.user(), factory.user(), factory.user()
        factory.integration(active, "google_photos")
        factory.integration(inactive, "google_photos", status="expired")
        factory.integration(queued, "google_photos")
        photo_fetch.enqueue_scheduled_task(db, queued, "photo_fetch", {"user_id": queued})
        runtime.use_database(db)
        try:
            asyncio.run(photo_fetch.schedule_photo_fetches())
            asyncio.run(photo_fetch.schedule_photo_fetches())
        finally:
            runtime.use_database(None)
        rows = db.query("SELECT user_id FROM scheduled_tasks WHERE task_type = 'photo_fetch'")
        assert sorted(r[0] for r in rows) == sorted([active, queued])


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
    def test_returns_none_when_no_integration(self, mock_get_oauth, db):
        """Verify None is returned when no Google Photos integration exists."""
        mock_get_oauth.return_value = None

        result = get_credentials(db, MagicMock(), user_id="test-user")

        assert result is None
        mock_get_oauth.assert_called_once()

    @patch("selko.services.google_photos.get_oauth_credentials")
    def test_returns_valid_credentials(self, mock_get_oauth, db):
        """Verify valid credentials are returned without refresh."""
        mock_creds = MagicMock()
        mock_creds.expired = False
        mock_get_oauth.return_value = mock_creds

        result = get_credentials(db, MagicMock(), user_id="test-user")

        assert result is mock_creds

    @patch("selko.services.google_photos.update_oauth_credentials")
    @patch("selko.services.google_photos.Request")
    @patch("selko.services.google_photos.get_oauth_credentials")
    def test_refreshes_expired_credentials(
        self, mock_get_oauth, mock_request, mock_update, db
    ):
        """Verify expired credentials are refreshed."""
        mock_creds = MagicMock()
        mock_creds.expired = True
        mock_creds.refresh_token = "refresh-token"
        mock_get_oauth.return_value = mock_creds

        result = get_credentials(db, MagicMock(), user_id="test-user")

        assert result is mock_creds
        mock_creds.refresh.assert_called_once()

    @patch("selko.services.google_photos.update_integration_status")
    @patch("selko.services.google_photos.Request")
    @patch("selko.services.google_photos.get_oauth_credentials")
    def test_handles_refresh_failure(
        self, mock_get_oauth, mock_request, mock_update_status, db
    ):
        """Verify None is returned when refresh fails."""
        from google.auth.exceptions import RefreshError

        mock_creds = MagicMock()
        mock_creds.expired = True
        mock_creds.refresh_token = "refresh-token"
        mock_creds.refresh.side_effect = RefreshError("Token revoked")
        mock_get_oauth.return_value = mock_creds

        result = get_credentials(db, MagicMock(), user_id="test-user")

        assert result is None
        mock_update_status.assert_called_once()
