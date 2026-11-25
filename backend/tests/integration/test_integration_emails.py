"""Integration tests for email service.

Email parsing, and storage on a real temporary SQLite database.
"""

import pytest

from selko.services.emails import parse_gmail_message


@pytest.mark.integration
class TestEmailParsing:
    """Test email parsing (no DB required)."""

    def test_parse_gmail_message(self, sample_gmail_api_message):
        """Parse Gmail API message into database format."""
        parsed = parse_gmail_message(sample_gmail_api_message)

        assert parsed["provider_message_id"] == sample_gmail_api_message["id"]
        assert parsed["thread_id"] == sample_gmail_api_message["threadId"]
        assert parsed["subject"] == "Test Subject from Gmail"
        assert parsed["from_email"] == "john@example.com"
        assert parsed["from_name"] == "John Doe"
        assert "jane@example.com" in parsed["to_emails"]
        assert parsed["provider_labels"] == ["INBOX", "UNREAD", "IMPORTANT"]

    def test_parse_message_no_from_name(self):
        """Parse message with email-only From header."""
        msg = {
            "id": "msg123",
            "threadId": "thread123",
            "labelIds": ["INBOX"],
            "payload": {
                "headers": [
                    {"name": "From", "value": "sender@example.com"},
                    {"name": "Subject", "value": "Test"},
                ],
                "parts": [],
            },
        }

        parsed = parse_gmail_message(msg)

        assert parsed["from_email"] == "sender@example.com"
        assert parsed["from_name"] is None

    def test_parse_message_multiple_recipients(self):
        """Parse message with multiple To addresses."""
        msg = {
            "id": "msg123",
            "threadId": "thread123",
            "labelIds": ["INBOX"],
            "payload": {
                "headers": [
                    {"name": "From", "value": "sender@example.com"},
                    {
                        "name": "To",
                        "value": "one@example.com, Two Person <two@example.com>, three@example.com",
                    },
                ],
                "parts": [],
            },
        }

        parsed = parse_gmail_message(msg)

        assert len(parsed["to_emails"]) == 3
        assert "one@example.com" in parsed["to_emails"]
        assert "two@example.com" in parsed["to_emails"]
        assert "three@example.com" in parsed["to_emails"]

    def test_parse_message_with_attachments(self):
        """Parse message and detect attachments."""
        msg = {
            "id": "msg123",
            "threadId": "thread123",
            "labelIds": ["INBOX"],
            "payload": {
                "headers": [],
                "parts": [
                    {"filename": "document.pdf", "mimeType": "application/pdf"},
                    {"filename": "", "mimeType": "text/plain"},  # No filename
                ],
            },
        }

        parsed = parse_gmail_message(msg)

        assert parsed["has_attachments"] is True

    def test_parse_message_no_attachments(self):
        """Parse message without attachments."""
        msg = {
            "id": "msg123",
            "threadId": "thread123",
            "labelIds": ["INBOX"],
            "payload": {
                "headers": [],
                "parts": [],
            },
        }

        parsed = parse_gmail_message(msg)

        assert parsed["has_attachments"] is False


