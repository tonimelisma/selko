"""Tests for email parsing."""

import pytest

from selko.services.emails import parse_gmail_message


class TestParseGmailMessage:
    """Test email header parsing."""

    def test_simple_from_header(self):
        """Parse simple 'Name <email>' format."""
        msg = self._make_message(from_header="John Doe <john@example.com>")
        result = parse_gmail_message(msg)

        assert result["from_name"] == "John Doe"
        assert result["from_email"] == "john@example.com"

    def test_quoted_name_with_comma(self):
        """Parse quoted name with comma."""
        msg = self._make_message(from_header='"Smith, John" <john@example.com>')
        result = parse_gmail_message(msg)

        assert result["from_name"] == "Smith, John"
        assert result["from_email"] == "john@example.com"

    def test_email_only(self):
        """Parse email without name."""
        msg = self._make_message(from_header="john@example.com")
        result = parse_gmail_message(msg)

        assert result["from_name"] is None
        assert result["from_email"] == "john@example.com"

    def test_angle_brackets_only(self):
        """Parse <email> format."""
        msg = self._make_message(from_header="<john@example.com>")
        result = parse_gmail_message(msg)

        assert result["from_email"] == "john@example.com"

    def test_multiple_to_addresses(self):
        """Parse multiple recipients."""
        msg = self._make_message(
            to_header="John <john@example.com>, Jane <jane@example.com>"
        )
        result = parse_gmail_message(msg)

        assert "john@example.com" in result["to_emails"]
        assert "jane@example.com" in result["to_emails"]

    def test_to_with_quoted_name(self):
        """Parse recipient with quoted name containing special chars."""
        msg = self._make_message(
            to_header='"Doe, Jane" <jane@example.com>'
        )
        result = parse_gmail_message(msg)

        assert "jane@example.com" in result["to_emails"]

    def test_empty_from_header(self):
        """Handle empty from header gracefully."""
        msg = self._make_message(from_header="")
        result = parse_gmail_message(msg)

        assert result["from_email"] == ""
        assert result["from_name"] is None

    def test_extracts_gmail_id(self):
        """Ensure Gmail ID is extracted."""
        msg = self._make_message()
        msg["id"] = "unique-gmail-id-123"
        result = parse_gmail_message(msg)

        assert result["gmail_id"] == "unique-gmail-id-123"

    def test_extracts_thread_id(self):
        """Ensure thread ID is extracted."""
        msg = self._make_message()
        msg["threadId"] = "thread-456"
        result = parse_gmail_message(msg)

        assert result["thread_id"] == "thread-456"

    def test_extracts_subject(self):
        """Ensure subject is extracted from headers."""
        msg = self._make_message(subject="Important Meeting")
        result = parse_gmail_message(msg)

        assert result["subject"] == "Important Meeting"

    def test_extracts_snippet(self):
        """Ensure snippet is extracted."""
        msg = self._make_message()
        msg["snippet"] = "Email preview text..."
        result = parse_gmail_message(msg)

        assert result["snippet"] == "Email preview text..."

    def test_extracts_label_ids(self):
        """Ensure label IDs are extracted."""
        msg = self._make_message()
        msg["labelIds"] = ["INBOX", "IMPORTANT", "STARRED"]
        result = parse_gmail_message(msg)

        assert result["gmail_label_ids"] == ["INBOX", "IMPORTANT", "STARRED"]

    def test_detects_attachments(self):
        """Detect when email has attachments."""
        msg = self._make_message()
        msg["payload"]["parts"] = [
            {"filename": "document.pdf", "mimeType": "application/pdf"}
        ]
        result = parse_gmail_message(msg)

        assert result["has_attachments"] is True

    def test_no_attachments(self):
        """Detect when email has no attachments."""
        msg = self._make_message()
        msg["payload"]["parts"] = []
        result = parse_gmail_message(msg)

        assert result["has_attachments"] is False

    def test_parses_date_with_timezone(self):
        """Parse date with timezone offset."""
        msg = self._make_message()
        msg["payload"]["headers"].append(
            {"name": "Date", "value": "Mon, 20 Jan 2026 10:30:00 +0000"}
        )
        result = parse_gmail_message(msg)

        assert result["date_sent"] is not None
        assert "2026-01-20" in result["date_sent"]

    def _make_message(
        self,
        from_header: str = "Test <test@example.com>",
        to_header: str = "Recipient <recipient@example.com>",
        subject: str = "Test Subject",
    ) -> dict:
        """Helper to create Gmail message structure."""
        headers = [
            {"name": "From", "value": from_header},
            {"name": "To", "value": to_header},
            {"name": "Subject", "value": subject},
        ]
        return {
            "id": "test-id",
            "threadId": "test-thread",
            "snippet": "Test snippet",
            "labelIds": ["INBOX"],
            "payload": {"headers": headers, "parts": []},
        }
