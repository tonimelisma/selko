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
)
from selko.services.gmail import extract_attachments


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
