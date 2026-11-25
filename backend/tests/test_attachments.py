"""Unit tests for the attachment service.

Storage runs against a real temporary database and attachments directory;
only the Gmail API is mocked.
"""

import base64
from unittest.mock import MagicMock

import pytest

from selko.db.runtime import attachments_dir, use_database
from selko.services.attachments import (
    AttachmentError,
    calculate_content_hash,
    download_gmail_attachment,
    read_attachment_file,
    upload_to_storage,
    write_attachment_file,
)
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


@pytest.fixture
def store(db):
    """The test database installed as the process database (the file store's root)."""
    use_database(db)
    yield db
    use_database(None)


def _config(max_size: int = 10 * 1024 * 1024):
    config = MagicMock()
    config.max_attachment_size = max_size
    config.storage_bucket_attachments = "attachments"
    return config







class TestFileStore:
    """Attachments on disk: atomic writes, paths that cannot escape, delete."""

    def test_write_is_atomic_and_leaves_no_temp_file(self, store):
        write_attachment_file("user-1/abc_file.txt", b"hello")
        files = sorted(p.name for p in (attachments_dir() / "user-1").iterdir())
        assert files == ["abc_file.txt"]
        assert read_attachment_file("user-1/abc_file.txt") == b"hello"

    def test_a_failed_write_leaves_no_partial_file(self, store, monkeypatch):
        import os

        def crash(_src, _dst):
            raise OSError("crash between write and rename")

        monkeypatch.setattr(os, "replace", crash)
        with pytest.raises(OSError):
            write_attachment_file("user-1/abc_file.txt", b"hello")
        assert not any(p.is_file() for p in attachments_dir().rglob("*"))

    @pytest.mark.parametrize(
        "path", ["../escape.txt", "user-1/../../escape.txt", "/etc/passwd", "", "user/../.."],
    )
    def test_paths_never_escape_the_attachments_directory(self, store, path):
        with pytest.raises(AttachmentError):
            write_attachment_file(path, b"x")
        with pytest.raises(AttachmentError):
            read_attachment_file(path)

    def test_a_filename_cannot_steer_the_path(self, store):
        path = upload_to_storage(store, "user-1", "../../../etc/passwd", b"x", "text/plain")
        assert path.startswith("user-1/")
        assert ".." not in path.split("/")
        assert (attachments_dir() / path).resolve().is_relative_to(attachments_dir().resolve())




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
