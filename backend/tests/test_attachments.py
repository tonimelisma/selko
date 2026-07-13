"""Unit tests for attachment service.

Tests attachment processing functions with mocked dependencies.
"""

import base64
from unittest.mock import MagicMock, patch

import pytest

from selko.services.attachments import (
    AttachmentError,
    calculate_content_hash,
    download_gmail_attachment,
    process_attachment,
    store_image_content,
)
from selko.services.auth import AuthenticationError
from selko.services.gmail import extract_attachments, extract_inline_images


class TestCalculateContentHash:
    """Test SHA-256 hash calculation."""

    def test_calculate_content_hash_basic(self):
        """Calculate hash of simple content."""
        data = b"Hello, World!"
        hash_result = calculate_content_hash(data)

        # Known SHA-256 hash of "Hello, World!"
        expected = "dffd6021bb2bd5b0af676290809ec3a53191dd81c7f70a4b28688a362182986f"
        assert hash_result == expected

    def test_calculate_content_hash_empty(self):
        """Calculate hash of empty content."""
        data = b""
        hash_result = calculate_content_hash(data)

        # Known SHA-256 hash of empty string
        expected = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
        assert hash_result == expected

    def test_calculate_content_hash_binary(self):
        """Calculate hash of binary content."""
        data = bytes([0, 1, 2, 3, 255, 254, 253])
        hash_result = calculate_content_hash(data)

        assert len(hash_result) == 64  # SHA-256 produces 64 hex chars
        assert hash_result.isalnum()

    def test_calculate_content_hash_deterministic(self):
        """Same content produces same hash."""
        data = b"Test content for determinism"
        hash1 = calculate_content_hash(data)
        hash2 = calculate_content_hash(data)

        assert hash1 == hash2


class TestExtractAttachments:
    """Test Gmail attachment extraction."""

    def test_extract_no_attachments(self):
        """Extract from message with no attachments."""
        msg = {
            "id": "msg123",
            "payload": {
                "headers": [],
                "parts": [],
            },
        }

        attachments = extract_attachments(msg)
        assert attachments == []

    def test_extract_single_attachment(self):
        """Extract single attachment from message."""
        msg = {
            "id": "msg123",
            "payload": {
                "headers": [],
                "parts": [
                    {
                        "filename": "document.pdf",
                        "mimeType": "application/pdf",
                        "body": {
                            "attachmentId": "att123",
                            "size": 1024,
                        },
                    },
                ],
            },
        }

        attachments = extract_attachments(msg)

        assert len(attachments) == 1
        assert attachments[0]["attachment_id"] == "att123"
        assert attachments[0]["filename"] == "document.pdf"
        assert attachments[0]["mime_type"] == "application/pdf"
        assert attachments[0]["size_bytes"] == 1024

    def test_extract_multiple_attachments(self):
        """Extract multiple attachments from message."""
        msg = {
            "id": "msg123",
            "payload": {
                "headers": [],
                "parts": [
                    {
                        "filename": "doc1.pdf",
                        "mimeType": "application/pdf",
                        "body": {"attachmentId": "att1", "size": 1000},
                    },
                    {
                        "filename": "image.png",
                        "mimeType": "image/png",
                        "body": {"attachmentId": "att2", "size": 2000},
                    },
                    {
                        "filename": "data.csv",
                        "mimeType": "text/csv",
                        "body": {"attachmentId": "att3", "size": 500},
                    },
                ],
            },
        }

        attachments = extract_attachments(msg)

        assert len(attachments) == 3
        filenames = [a["filename"] for a in attachments]
        assert "doc1.pdf" in filenames
        assert "image.png" in filenames
        assert "data.csv" in filenames

    def test_extract_nested_multipart(self):
        """Extract attachments from nested multipart message."""
        msg = {
            "id": "msg123",
            "payload": {
                "headers": [],
                "mimeType": "multipart/mixed",
                "parts": [
                    {
                        "mimeType": "multipart/alternative",
                        "parts": [
                            {"mimeType": "text/plain", "body": {"data": "text"}},
                            {"mimeType": "text/html", "body": {"data": "html"}},
                        ],
                    },
                    {
                        "filename": "attachment.pdf",
                        "mimeType": "application/pdf",
                        "body": {"attachmentId": "att123", "size": 5000},
                    },
                ],
            },
        }

        attachments = extract_attachments(msg)

        assert len(attachments) == 1
        assert attachments[0]["filename"] == "attachment.pdf"

    def test_extract_ignores_inline_without_filename(self):
        """Ignore parts without filename (inline content)."""
        msg = {
            "id": "msg123",
            "payload": {
                "headers": [],
                "parts": [
                    {
                        "mimeType": "text/plain",
                        "body": {"data": "inline text"},
                    },
                    {
                        "filename": "",  # Empty filename
                        "mimeType": "image/png",
                        "body": {"attachmentId": "inline123"},
                    },
                    {
                        "filename": "real-attachment.pdf",
                        "mimeType": "application/pdf",
                        "body": {"attachmentId": "att123", "size": 1000},
                    },
                ],
            },
        }

        attachments = extract_attachments(msg)

        assert len(attachments) == 1
        assert attachments[0]["filename"] == "real-attachment.pdf"


class TestDownloadGmailAttachment:
    """Test Gmail attachment download with mocked API."""

    def test_download_success(self):
        """Successfully download attachment."""
        mock_service = MagicMock()
        # Gmail returns base64url encoded data
        test_content = b"Test attachment content"
        encoded = base64.urlsafe_b64encode(test_content).decode()

        mock_service.users().messages().attachments().get().execute.return_value = {
            "data": encoded
        }

        result = download_gmail_attachment(mock_service, "msg123", "att123")

        assert result == test_content

    def test_download_empty_attachment(self):
        """Download empty attachment."""
        mock_service = MagicMock()
        encoded = base64.urlsafe_b64encode(b"").decode()

        mock_service.users().messages().attachments().get().execute.return_value = {
            "data": encoded
        }

        result = download_gmail_attachment(mock_service, "msg123", "att123")

        assert result == b""

    def test_download_binary_content(self):
        """Download binary attachment content."""
        mock_service = MagicMock()
        binary_content = bytes(range(256))  # All byte values
        encoded = base64.urlsafe_b64encode(binary_content).decode()

        mock_service.users().messages().attachments().get().execute.return_value = {
            "data": encoded
        }

        result = download_gmail_attachment(mock_service, "msg123", "att123")

        assert result == binary_content


class TestExtractInlineImages:
    """Test inline/CID image extraction from Gmail messages."""

    def test_extract_inline_image_with_cid(self):
        """Extract image part with Content-ID header and no filename."""
        msg = {
            "id": "msg123",
            "payload": {
                "headers": [],
                "parts": [
                    {
                        "mimeType": "text/html",
                        "body": {"data": "html"},
                    },
                    {
                        "filename": "",
                        "mimeType": "image/png",
                        "headers": [
                            {"name": "Content-ID", "value": "<image001.png@01D6B7>"},
                            {"name": "Content-Disposition", "value": "inline"},
                        ],
                        "body": {"attachmentId": "cid-att-123", "size": 5000},
                    },
                ],
            },
        }

        result = extract_inline_images(msg)

        assert len(result) == 1
        assert result[0]["attachment_id"] == "cid-att-123"
        assert result[0]["filename"] == "inline_0.png"
        assert result[0]["mime_type"] == "image/png"
        assert result[0]["size_bytes"] == 5000
        assert result[0]["content_id"] == "image001.png@01D6B7"

    def test_skips_non_image_parts(self):
        """Skip parts with Content-ID but non-image MIME type."""
        msg = {
            "id": "msg123",
            "payload": {
                "headers": [],
                "parts": [
                    {
                        "filename": "",
                        "mimeType": "text/plain",
                        "headers": [
                            {"name": "Content-ID", "value": "<text001>"},
                        ],
                        "body": {"attachmentId": "att-text", "size": 100},
                    },
                ],
            },
        }

        result = extract_inline_images(msg)

        assert len(result) == 0

    def test_skips_parts_with_filename(self):
        """Skip image parts that have filenames (handled by extract_attachments)."""
        msg = {
            "id": "msg123",
            "payload": {
                "headers": [],
                "parts": [
                    {
                        "filename": "photo.jpg",
                        "mimeType": "image/jpeg",
                        "headers": [
                            {"name": "Content-ID", "value": "<photo001>"},
                        ],
                        "body": {"attachmentId": "att-photo", "size": 10000},
                    },
                ],
            },
        }

        result = extract_inline_images(msg)

        assert len(result) == 0

    def test_extracts_inline_disposition_without_cid(self):
        """Extract image with Content-Disposition: inline but no Content-ID."""
        msg = {
            "id": "msg123",
            "payload": {
                "headers": [],
                "parts": [
                    {
                        "filename": "",
                        "mimeType": "image/jpeg",
                        "headers": [
                            {"name": "Content-Disposition", "value": "inline"},
                        ],
                        "body": {"attachmentId": "att-inline", "size": 8000},
                    },
                ],
            },
        }

        result = extract_inline_images(msg)

        assert len(result) == 1
        assert result[0]["content_id"] is None
        assert result[0]["filename"] == "inline_0.jpg"

    def test_skips_parts_without_cid_or_inline(self):
        """Skip image parts that have neither CID nor inline disposition."""
        msg = {
            "id": "msg123",
            "payload": {
                "headers": [],
                "parts": [
                    {
                        "filename": "",
                        "mimeType": "image/png",
                        "headers": [],
                        "body": {"attachmentId": "att-unknown", "size": 3000},
                    },
                ],
            },
        }

        result = extract_inline_images(msg)

        assert len(result) == 0

    def test_extracts_from_nested_multipart(self):
        """Extract inline images from nested MIME parts."""
        msg = {
            "id": "msg123",
            "payload": {
                "headers": [],
                "mimeType": "multipart/related",
                "parts": [
                    {
                        "mimeType": "multipart/alternative",
                        "parts": [
                            {"mimeType": "text/plain", "body": {"data": "text"}},
                            {"mimeType": "text/html", "body": {"data": "html"}},
                        ],
                    },
                    {
                        "filename": "",
                        "mimeType": "image/gif",
                        "headers": [
                            {"name": "Content-ID", "value": "<anim.gif@01>"},
                        ],
                        "body": {"attachmentId": "att-gif", "size": 15000},
                    },
                ],
            },
        }

        result = extract_inline_images(msg)

        assert len(result) == 1
        assert result[0]["filename"] == "inline_0.gif"
        assert result[0]["mime_type"] == "image/gif"


class TestStoreImageContent:
    """Test storing raw image bytes as attachment records."""

    @patch("selko.services.attachments.save_attachment_metadata")
    @patch("selko.services.attachments.upload_to_storage")
    @patch("selko.services.attachments.get_current_user_id")
    @patch("selko.services.attachments.check_duplicate_attachment")
    def test_stores_new_image(
        self, mock_check_dup, mock_get_user, mock_upload, mock_save
    ):
        """Store a new image that has no duplicate."""
        mock_check_dup.return_value = None
        mock_get_user.return_value = "user-123"
        mock_upload.return_value = "user-123/abc_linked_0.jpg"
        mock_save.return_value = {"id": "att-new", "filename": "linked_0.jpg"}

        config = MagicMock()
        config.max_attachment_size = 10 * 1024 * 1024
        config.storage_bucket_attachments = "attachments"

        result = store_image_content(
            client=MagicMock(),
            email_id="email-123",
            image_data=b"x" * 1000,
            mime_type="image/jpeg",
            filename="linked_0.jpg",
            config=config,
        )

        assert result is not None
        assert result["filename"] == "linked_0.jpg"
        mock_upload.assert_called_once()
        mock_save.assert_called_once()

    @patch("selko.services.attachments.check_duplicate_attachment")
    def test_skips_duplicate_image(self, mock_check_dup):
        """Skip image that already exists (hash match)."""
        mock_check_dup.return_value = {"id": "existing-att", "filename": "old.jpg"}

        config = MagicMock()
        config.max_attachment_size = 10 * 1024 * 1024

        result = store_image_content(
            client=MagicMock(),
            email_id="email-123",
            image_data=b"x" * 1000,
            mime_type="image/jpeg",
            filename="linked_0.jpg",
            config=config,
        )

        assert result["id"] == "existing-att"

    def test_skips_empty_data(self):
        """Return None for empty image data."""
        config = MagicMock()

        result = store_image_content(
            client=MagicMock(),
            email_id="email-123",
            image_data=b"",
            mime_type="image/jpeg",
            filename="empty.jpg",
            config=config,
        )

        assert result is None

    def test_skips_oversized_image(self):
        """Skip images exceeding max_attachment_size."""
        config = MagicMock()
        config.max_attachment_size = 1000

        result = store_image_content(
            client=MagicMock(),
            email_id="email-123",
            image_data=b"x" * 2000,
            mime_type="image/jpeg",
            filename="huge.jpg",
            config=config,
        )

        assert result is None


class TestAttachmentOwnerThreading:
    """Regression tests for the worker 'No user signed in' failure.

    Background workers use a service-role client with no auth session, so
    falling back to get_current_user_id raised AuthenticationError and every
    Gmail fetch with attachments failed in production. When user_id is passed
    explicitly, the session lookup must never happen.
    """

    def _config(self):
        config = MagicMock()
        config.max_attachment_size = 10 * 1024 * 1024
        config.storage_bucket_attachments = "attachments"
        return config

    @patch("selko.services.attachments.save_attachment_metadata")
    @patch("selko.services.attachments.upload_to_storage")
    @patch("selko.services.attachments.get_current_user_id")
    @patch("selko.services.attachments.check_duplicate_attachment")
    def test_store_image_content_with_user_id_skips_session_lookup(
        self, mock_check_dup, mock_get_user, mock_upload, mock_save
    ):
        """store_image_content(user_id=...) works on a session-less client."""
        mock_check_dup.return_value = None
        mock_get_user.side_effect = AuthenticationError("No user signed in")
        mock_upload.return_value = "user-123/abc_linked_0.jpg"
        mock_save.return_value = {"id": "att-new", "filename": "linked_0.jpg"}

        result = store_image_content(
            client=MagicMock(),
            email_id="email-123",
            image_data=b"x" * 1000,
            mime_type="image/jpeg",
            filename="linked_0.jpg",
            config=self._config(),
            user_id="user-123",
        )

        assert result is not None
        mock_get_user.assert_not_called()
        assert mock_upload.call_args.kwargs["user_id"] == "user-123"
        assert mock_save.call_args.kwargs["user_id"] == "user-123"

    @patch("selko.services.attachments.download_gmail_attachment")
    @patch("selko.services.attachments.save_attachment_metadata")
    @patch("selko.services.attachments.upload_to_storage")
    @patch("selko.services.attachments.get_current_user_id")
    @patch("selko.services.attachments.check_duplicate_attachment")
    def test_process_attachment_with_user_id_skips_session_lookup(
        self, mock_check_dup, mock_get_user, mock_upload, mock_save, mock_download
    ):
        """process_attachment(user_id=...) works on a session-less client."""
        mock_check_dup.return_value = None
        mock_get_user.side_effect = AuthenticationError("No user signed in")
        mock_download.return_value = b"pdf-bytes"
        mock_upload.return_value = "user-123/abc_report.pdf"
        mock_save.return_value = {"id": "att-new", "filename": "report.pdf"}

        result = process_attachment(
            client=MagicMock(),
            gmail_service=MagicMock(),
            email_id="email-123",
            message_id="msg-1",
            attachment_part={
                "attachment_id": "gmail-att-1",
                "filename": "report.pdf",
                "mime_type": "application/pdf",
                "size_bytes": 9,
            },
            config=self._config(),
            user_id="user-123",
        )

        assert result is not None
        mock_get_user.assert_not_called()
        assert mock_upload.call_args.kwargs["user_id"] == "user-123"
        assert mock_save.call_args.kwargs["user_id"] == "user-123"


class TestAttachmentError:
    """Test AttachmentError exception."""

    def test_error_message(self):
        """AttachmentError carries message."""
        error = AttachmentError("Test error message")
        assert str(error) == "Test error message"

    def test_error_inheritance(self):
        """AttachmentError inherits from Exception."""
        error = AttachmentError("Test")
        assert isinstance(error, Exception)
