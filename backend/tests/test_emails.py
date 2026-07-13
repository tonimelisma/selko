"""Tests for email parsing."""

import base64
from datetime import datetime, timezone

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

    def test_extracts_provider_identity(self):
        """Ensure the provider and provider message ID are extracted."""
        msg = self._make_message()
        msg["id"] = "unique-gmail-id-123"
        result = parse_gmail_message(msg)

        assert result["email_provider"] == "gmail"
        assert result["provider_message_id"] == "unique-gmail-id-123"

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

    def test_extracts_provider_labels(self):
        """Ensure provider labels are extracted."""
        msg = self._make_message()
        msg["labelIds"] = ["INBOX", "IMPORTANT", "STARRED"]
        result = parse_gmail_message(msg)

        assert result["provider_labels"] == ["INBOX", "IMPORTANT", "STARRED"]

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

    def test_parses_date_with_parenthetical_timezone(self):
        """Regression: Date headers with (UTC)/(PDT) comments used to store NULL."""
        msg = self._make_message()
        msg["payload"]["headers"].append(
            {"name": "Date", "value": "Mon, 20 Jan 2026 10:30:00 +0000 (UTC)"}
        )
        result = parse_gmail_message(msg)

        assert result["date_sent"] is not None
        assert "2026-01-20" in result["date_sent"]

    def test_parses_date_with_double_space_day(self):
        """Regression: single-digit day padded with space broke strptime."""
        msg = self._make_message()
        msg["payload"]["headers"].append(
            {"name": "Date", "value": "Mon,  5 Jan 2026 09:15:00 -0800"}
        )
        result = parse_gmail_message(msg)

        assert result["date_sent"] is not None
        assert "2026-01-05" in result["date_sent"]

    def test_falls_back_to_gmail_internal_date(self):
        """When Date header is missing, use Gmail internalDate (epoch ms)."""
        msg = self._make_message()
        # 2026-01-20T10:30:00Z
        msg["internalDate"] = str(int(datetime(2026, 1, 20, 10, 30, tzinfo=timezone.utc).timestamp() * 1000))
        result = parse_gmail_message(msg)

        assert result["date_sent"] is not None
        assert "2026-01-20" in result["date_sent"]

    def test_unparseable_date_without_internal_date_stays_none(self):
        """Don't invent a timestamp when neither Date nor internalDate works."""
        msg = self._make_message()
        msg["payload"]["headers"].append(
            {"name": "Date", "value": "not-a-real-date"}
        )
        result = parse_gmail_message(msg)

        assert result["date_sent"] is None

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


def _b64url(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii")


def _make_message_with_calendar_part(
    *, content_type: str = "text/calendar", body_text: str = "", inline_data: str | None = None
) -> dict:
    """Gmail message with a text/calendar MIME part, method resolvable either
    from the Content-Type header (default) or from inline body data."""
    headers = [{"name": "From", "value": "Organizer <organizer@example.com>"}]
    calendar_part: dict = {
        "mimeType": "text/calendar",
        "headers": [{"name": "Content-Type", "value": content_type}],
        "body": {},
    }
    if inline_data is not None:
        calendar_part["body"]["data"] = inline_data
    return {
        "id": "invite-msg-id",
        "threadId": "invite-thread",
        "snippet": "Meeting invite",
        "labelIds": ["INBOX"],
        "payload": {
            "headers": headers,
            "mimeType": "multipart/mixed",
            "parts": [
                {
                    "mimeType": "text/plain",
                    "body": {"data": _b64url(body_text)},
                },
                calendar_part,
            ],
        },
    }


class TestGmailCalendarInviteDetection:
    """Tests for Gmail invite-at-ingestion detection (WS6)."""

    def test_method_request_in_content_type_header(self):
        msg = _make_message_with_calendar_part(content_type="text/calendar; method=REQUEST; charset=UTF-8")
        result = parse_gmail_message(msg)

        assert result["is_calendar_invite"] is True
        assert result["processing_status"] == "skipped"
        assert result["processing_outcome"] == "calendar_invite"
        assert "processed_at" in result

    def test_method_reply_in_content_type_header_case_insensitive(self):
        msg = _make_message_with_calendar_part(content_type="text/calendar; METHOD=Reply")
        result = parse_gmail_message(msg)

        assert result["is_calendar_invite"] is True

    def test_method_resolved_from_inline_body_when_header_absent(self):
        ics = "BEGIN:VCALENDAR\nMETHOD:CANCEL\nEND:VCALENDAR"
        msg = _make_message_with_calendar_part(content_type="text/calendar", inline_data=_b64url(ics))

        result = parse_gmail_message(msg)

        assert result["is_calendar_invite"] is True
        assert result["processing_status"] == "skipped"

    def test_method_publish_is_not_an_invite(self):
        msg = _make_message_with_calendar_part(content_type="text/calendar; method=PUBLISH")
        result = parse_gmail_message(msg)

        assert result["is_calendar_invite"] is False
        assert "processing_status" not in result

    def test_no_method_and_no_inline_body_is_not_an_invite(self):
        """Attachment-only calendar part (no inline data, no header method) is
        left undetermined at ingest time — the process-time backstop covers it."""
        msg = _make_message_with_calendar_part(content_type="text/calendar")
        result = parse_gmail_message(msg)

        assert result["is_calendar_invite"] is False
        assert "processing_status" not in result

    def test_no_calendar_part_is_not_an_invite(self):
        msg = {
            "id": "plain-msg",
            "threadId": "t",
            "snippet": "hi",
            "labelIds": ["INBOX"],
            "payload": {"headers": [], "parts": []},
        }
        result = parse_gmail_message(msg)

        assert result["is_calendar_invite"] is False
        assert "processing_status" not in result


class TestSaveEmailsIngestShortCircuit:
    """An invite-flagged parsed dict must upsert pre-skipped, never claimable."""

    def test_invite_flagged_email_saves_as_skipped(self):
        from unittest.mock import MagicMock

        from selko.services.emails import save_emails

        mock_client = MagicMock()
        mock_execute_result = MagicMock()
        mock_execute_result.data = [{"id": "email-1"}]
        mock_client.table.return_value.upsert.return_value.execute.return_value = mock_execute_result

        msg = _make_message_with_calendar_part(content_type="text/calendar; method=REQUEST")
        parsed = parse_gmail_message(msg)

        save_emails(mock_client, [parsed], user_id="user-1")

        upsert_payload = mock_client.table.return_value.upsert.call_args[0][0]
        assert upsert_payload["processing_status"] == "skipped"
        assert upsert_payload["processing_outcome"] == "calendar_invite"

    def test_non_invite_email_has_no_skip_fields_on_save(self):
        from unittest.mock import MagicMock

        from selko.services.emails import save_emails

        mock_client = MagicMock()
        mock_execute_result = MagicMock()
        mock_execute_result.data = [{"id": "email-2"}]
        mock_client.table.return_value.upsert.return_value.execute.return_value = mock_execute_result

        msg = {
            "id": "plain",
            "threadId": "t",
            "snippet": "hi",
            "labelIds": ["INBOX"],
            "payload": {"headers": [], "parts": []},
        }
        parsed = parse_gmail_message(msg)

        save_emails(mock_client, [parsed], user_id="user-1")

        upsert_payload = mock_client.table.return_value.upsert.call_args[0][0]
        assert "processing_status" not in upsert_payload
