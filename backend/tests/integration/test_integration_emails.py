"""Integration tests for email service.

Email parsing, and storage on a real temporary SQLite database.
"""

import pytest

from selko.services.emails import parse_gmail_message, save_emails


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


@pytest.mark.integration
class TestEmailStorage:
    """Email storage on a real temporary database."""

    @staticmethod
    def _row(db, user_id, provider_message_id):
        from selko.db import codec

        rows = db.query(
            "SELECT * FROM emails WHERE user_id = ? AND provider_message_id = ?",
            (codec.to_id(user_id), provider_message_id),
        )
        return [db.schema.decode("emails", r) for r in rows]

    def _email(self, **fields):
        from uuid import uuid4

        return {
            "provider_message_id": f"test_{uuid4().hex[:8]}",
            "thread_id": "thread",
            "subject": "Subject",
            "from_email": "sender@example.com",
            "date_sent": "2026-01-22T10:00:00+00:00",
            **fields,
        }

    def test_save_email(self, db, factory, sample_email_data):
        user_id = factory.user()

        saved = save_emails(db, [sample_email_data], user_id=user_id)

        assert len(saved) == 1
        [row] = self._row(db, user_id, sample_email_data["provider_message_id"])
        assert row["subject"] == sample_email_data["subject"]
        assert row["user_id"] == user_id
        assert row["to_emails"] == ["recipient@example.com"]

    def test_save_email_upsert(self, db, factory, sample_email_data):
        """Saving the same email twice updates instead of duplicating."""
        user_id = factory.user()
        save_emails(db, [sample_email_data], user_id=user_id)
        sample_email_data["subject"] = "Updated Subject"
        save_emails(db, [sample_email_data], user_id=user_id)

        rows = self._row(db, user_id, sample_email_data["provider_message_id"])
        assert [r["subject"] for r in rows] == ["Updated Subject"]

    def test_gmail_labels_trigger(self, db, factory):
        """The labels trigger parses provider_labels into boolean flags."""
        user_id = factory.user()
        email = self._email(provider_labels=["SPAM", "UNREAD"])
        save_emails(db, [email], user_id=user_id)

        [row] = self._row(db, user_id, email["provider_message_id"])
        assert (row["is_spam"], row["is_unread"], row["is_primary"], row["is_trash"]) == (True, True, False, False)

    def test_gmail_labels_trigger_promotions(self, db, factory):
        user_id = factory.user()
        email = self._email(provider_labels=["CATEGORY_PROMOTIONS", "INBOX"])
        save_emails(db, [email], user_id=user_id)

        [row] = self._row(db, user_id, email["provider_message_id"])
        assert (row["is_promotions"], row["is_primary"]) == (True, False)

    def test_gmail_labels_trigger_primary(self, db, factory):
        user_id = factory.user()
        email = self._email(provider_labels=["CATEGORY_PERSONAL", "INBOX", "IMPORTANT"])
        save_emails(db, [email], user_id=user_id)

        [row] = self._row(db, user_id, email["provider_message_id"])
        assert (row["is_primary"], row["is_important"]) == (True, True)

    def test_save_multiple_emails(self, db, factory):
        user_id = factory.user()
        emails = [self._email(subject=f"Email {i}", provider_labels=["INBOX"]) for i in range(3)]

        saved = save_emails(db, emails, user_id=user_id)

        assert sorted(r["subject"] for r in saved) == ["Email 0", "Email 1", "Email 2"]

    def test_the_same_message_id_is_separate_per_user(self, db, factory):
        """Ownership is part of the upsert key: another user's copy is never overwritten."""
        alice, bob = factory.user(), factory.user()
        email = self._email()
        save_emails(db, [dict(email)], user_id=alice)
        save_emails(db, [{**email, "subject": "Bob's"}], user_id=bob)

        assert [r["subject"] for r in self._row(db, alice, email["provider_message_id"])] == ["Subject"]
        assert [r["subject"] for r in self._row(db, bob, email["provider_message_id"])] == ["Bob's"]
