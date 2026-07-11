"""Integration tests for email service.

Tests email parsing and database storage with real Supabase.
"""

import pytest

from selko.services.emails import EmailError, parse_gmail_message, save_emails


@pytest.mark.integration
@pytest.mark.development
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
@pytest.mark.development
class TestEmailStorage:
    """Test email storage with real Supabase."""

    def test_save_email(
        self, authenticated_client, test_user_id, sample_email_data, cleanup_emails
    ):
        """Can save email to database."""
        cleanup_emails.append(sample_email_data["provider_message_id"])

        saved = save_emails(authenticated_client, [sample_email_data])

        assert len(saved) == 1

        # Verify in database
        result = (
            authenticated_client.table("emails")
            .select("*")
            .eq("provider_message_id", sample_email_data["provider_message_id"])
            .single()
            .execute()
        )

        assert result.data is not None
        assert result.data["subject"] == sample_email_data["subject"]
        assert result.data["user_id"] == test_user_id

    def test_save_email_upsert(
        self, authenticated_client, test_user_id, sample_email_data, cleanup_emails
    ):
        """Saving same email twice updates instead of duplicating."""
        cleanup_emails.append(sample_email_data["provider_message_id"])

        # First save
        save_emails(authenticated_client, [sample_email_data])

        # Update subject and save again
        sample_email_data["subject"] = "Updated Subject"
        save_emails(authenticated_client, [sample_email_data])

        # Should only have one record
        result = (
            authenticated_client.table("emails")
            .select("*")
            .eq("provider_message_id", sample_email_data["provider_message_id"])
            .execute()
        )

        assert len(result.data) == 1
        assert result.data[0]["subject"] == "Updated Subject"

    def test_gmail_labels_trigger(self, authenticated_client, test_user_id, cleanup_emails):
        """Database trigger parses provider_labels into boolean flags."""
        from uuid import uuid4

        provider_message_id = f"test_trigger_{uuid4().hex[:8]}"
        cleanup_emails.append(provider_message_id)

        email_data = {
            "provider_message_id": provider_message_id,
            "thread_id": "thread_trigger",
            "provider_labels": ["SPAM", "UNREAD"],
            "subject": "Test spam email",
            "from_email": "spammer@example.com",
            "date_sent": "2026-01-22T10:00:00+00:00",
        }

        save_emails(authenticated_client, [email_data])

        # Fetch and check flags
        result = (
            authenticated_client.table("emails")
            .select("is_spam, is_unread, is_primary, is_trash")
            .eq("provider_message_id", provider_message_id)
            .single()
            .execute()
        )

        assert result.data["is_spam"] is True
        assert result.data["is_unread"] is True
        assert result.data["is_primary"] is False
        assert result.data["is_trash"] is False

    def test_gmail_labels_trigger_promotions(
        self, authenticated_client, test_user_id, cleanup_emails
    ):
        """Trigger correctly sets CATEGORY_PROMOTIONS flag."""
        from uuid import uuid4

        provider_message_id = f"test_promo_{uuid4().hex[:8]}"
        cleanup_emails.append(provider_message_id)

        email_data = {
            "provider_message_id": provider_message_id,
            "thread_id": "thread_promo",
            "provider_labels": ["CATEGORY_PROMOTIONS", "INBOX"],
            "subject": "Sale now!",
            "from_email": "deals@store.com",
            "date_sent": "2026-01-22T10:00:00+00:00",
        }

        save_emails(authenticated_client, [email_data])

        result = (
            authenticated_client.table("emails")
            .select("is_promotions, is_primary")
            .eq("provider_message_id", provider_message_id)
            .single()
            .execute()
        )

        assert result.data["is_promotions"] is True
        assert result.data["is_primary"] is False

    def test_gmail_labels_trigger_primary(
        self, authenticated_client, test_user_id, cleanup_emails
    ):
        """Trigger correctly sets CATEGORY_PERSONAL (primary) flag."""
        from uuid import uuid4

        provider_message_id = f"test_primary_{uuid4().hex[:8]}"
        cleanup_emails.append(provider_message_id)

        email_data = {
            "provider_message_id": provider_message_id,
            "thread_id": "thread_primary",
            "provider_labels": ["CATEGORY_PERSONAL", "INBOX", "IMPORTANT"],
            "subject": "Important message",
            "from_email": "friend@example.com",
            "date_sent": "2026-01-22T10:00:00+00:00",
        }

        save_emails(authenticated_client, [email_data])

        result = (
            authenticated_client.table("emails")
            .select("is_primary, is_important")
            .eq("provider_message_id", provider_message_id)
            .single()
            .execute()
        )

        assert result.data["is_primary"] is True
        assert result.data["is_important"] is True

    def test_save_multiple_emails(
        self, authenticated_client, test_user_id, cleanup_emails
    ):
        """Can save multiple emails at once."""
        from uuid import uuid4

        emails = []
        for i in range(3):
            provider_message_id = f"test_multi_{uuid4().hex[:8]}"
            cleanup_emails.append(provider_message_id)
            emails.append(
                {
                    "provider_message_id": provider_message_id,
                    "thread_id": f"thread_{i}",
                    "subject": f"Email {i}",
                    "from_email": f"sender{i}@example.com",
                    "provider_labels": ["INBOX"],
                    "date_sent": "2026-01-22T10:00:00+00:00",
                }
            )

        saved = save_emails(authenticated_client, emails)

        assert len(saved) == 3

    def test_rls_user_isolation(self, authenticated_client, test_user_id, cleanup_emails):
        """RLS ensures user only sees their own emails."""
        from uuid import uuid4

        provider_message_id = f"test_rls_{uuid4().hex[:8]}"
        cleanup_emails.append(provider_message_id)

        # Save email as current user
        save_emails(
            authenticated_client,
            [
                {
                    "provider_message_id": provider_message_id,
                    "thread_id": "thread_rls",
                    "subject": "RLS Test",
                    "from_email": "test@example.com",
                    "provider_labels": ["INBOX"],
                    "date_sent": "2026-01-22T10:00:00+00:00",
                }
            ],
        )

        # Query should only return emails for current user
        result = (
            authenticated_client.table("emails")
            .select("*")
            .eq("provider_message_id", provider_message_id)
            .execute()
        )

        assert len(result.data) == 1
        assert result.data[0]["user_id"] == test_user_id


@pytest.mark.integration
@pytest.mark.staging
class TestEmailStorageStaging:
    """Test email storage in staging environment."""

    def test_save_email_staging(
        self, authenticated_client, test_user_id, sample_email_data, cleanup_emails
    ):
        """Can save email to staging database."""
        cleanup_emails.append(sample_email_data["provider_message_id"])

        saved = save_emails(authenticated_client, [sample_email_data])

        assert len(saved) == 1

    def test_triggers_work_staging(
        self, authenticated_client, test_user_id, cleanup_emails
    ):
        """Database triggers work in staging."""
        from uuid import uuid4

        provider_message_id = f"test_staging_{uuid4().hex[:8]}"
        cleanup_emails.append(provider_message_id)

        save_emails(
            authenticated_client,
            [
                {
                    "provider_message_id": provider_message_id,
                    "thread_id": "thread_staging",
                    "provider_labels": ["STARRED", "INBOX"],
                    "subject": "Starred email",
                    "from_email": "vip@example.com",
                    "date_sent": "2026-01-22T10:00:00+00:00",
                }
            ],
        )

        result = (
            authenticated_client.table("emails")
            .select("is_starred")
            .eq("provider_message_id", provider_message_id)
            .single()
            .execute()
        )

        assert result.data["is_starred"] is True
