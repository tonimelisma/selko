"""Unit tests for Microsoft Graph Outlook ingestion."""

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from selko.services.outlook import (
    RESYNC_REQUIRED,
    get_access_token,
    fetch_message_changes,
    parse_outlook_message,
    synthesize_labels,
)


def _response(payload, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    response.text = "graph error"
    return response


class TestParseOutlookMessage:
    # Validates: SEL-072
    def test_maps_message_fields_and_plain_text_body(self):
        message = {
            "id": "outlook-message-1",
            "conversationId": "conversation-1",
            "subject": "Meeting",
            "from": {"emailAddress": {"address": "sender@example.com", "name": "Sender"}},
            "toRecipients": [
                {"emailAddress": {"address": "recipient@example.com", "name": "Recipient"}},
                {"emailAddress": {}},
            ],
            "receivedDateTime": "2026-07-11T16:30:00Z",
            "bodyPreview": "Preview",
            "body": {"contentType": "text", "content": "Plain text body"},
            "hasAttachments": True,
            "isRead": False,
            "importance": "high",
            "flag": {"flagStatus": "flagged"},
        }

        result = parse_outlook_message(message)

        assert result == {
            "email_provider": "outlook",
            "provider_message_id": "outlook-message-1",
            "thread_id": "conversation-1",
            "subject": "Meeting",
            "from_email": "sender@example.com",
            "from_name": "Sender",
            "to_emails": ["recipient@example.com"],
            "date_sent": "2026-07-11T16:30:00Z",
            "snippet": "Preview",
            "provider_labels": ["UNREAD", "IMPORTANT", "STARRED"],
            "has_attachments": True,
            "body_text": "Plain text body",
            "is_calendar_invite": False,
        }
        assert "body_html" not in result

    # Validates: SEL-072
    def test_omits_empty_recipients_and_never_stores_markup(self):
        """An HTML body is rendered to text, never stored as markup.

        This previously asserted `body_text` was absent entirely. That pinned
        the wrong half of the intent: the rule is that markup is never stored,
        not that the message is discarded. Dropping it sent extraction the
        ~255-char bodyPreview instead of the mail, which is the Outlook twin of
        the Gmail defect in test_email_body.py. Graph normally honours the
        `outlook.body-content-type="text"` Prefer header, so this path is the
        fallback for when it does not.
        """
        result = parse_outlook_message(
            {
                "id": "message-2",
                "toRecipients": [],
                "body": {"contentType": "html", "content": "<p>HTML</p>"},
            }
        )

        assert result["to_emails"] is None
        assert "body_html" not in result
        assert result["body_text"] == "HTML"
        assert "<p>" not in result["body_text"]

    # Validates: SEL-073
    def test_flags_event_message_request_as_calendar_invite(self):
        result = parse_outlook_message(
            {
                "id": "message-3",
                "@odata.type": "#microsoft.graph.eventMessageRequest",
            }
        )
        assert result["is_calendar_invite"] is True
        # Ingest-time filter: invite must be stored pre-skipped, never queued.
        assert result["processing_status"] == "skipped"
        assert result["processing_outcome"] == "calendar_invite"
        assert "processed_at" in result

    def test_flags_event_message_response_as_calendar_invite(self):
        result = parse_outlook_message(
            {
                "id": "message-4",
                "@odata.type": "#microsoft.graph.eventMessageResponse",
            }
        )
        assert result["is_calendar_invite"] is True

    def test_plain_message_is_not_a_calendar_invite(self):
        result = parse_outlook_message(
            {
                "id": "message-5",
                "@odata.type": "#microsoft.graph.message",
            }
        )
        assert result["is_calendar_invite"] is False
        assert "processing_status" not in result


class TestOutlookLabels:
    def test_synthesizes_supported_gmail_style_tokens(self):
        assert synthesize_labels({
            "isRead": False,
            "importance": "HIGH",
            "flag": {"flagStatus": "flagged"},
        }) == ["UNREAD", "IMPORTANT", "STARRED"]

    def test_normal_message_has_no_labels(self):
        assert synthesize_labels({"isRead": True, "importance": "normal"}) == []


class TestFetchMessageChanges:
    # Validates: SEL-027
    @patch("selko.services.msgraph.requests.get")
    def test_follows_next_link_and_returns_delta_link(self, mock_get):
        mock_get.side_effect = [
            _response({
                "value": [{"id": "created"}],
                "@odata.nextLink": "https://graph.example/next?$skiptoken=1",
            }),
            _response({
                "value": [{"id": "removed", "@removed": {"reason": "changed"}}],
                "@odata.deltaLink": "https://graph.example/delta?$deltatoken=2",
            }),
        ]

        changes, cursor = fetch_message_changes("token", None)

        assert changes == [
            {"id": "created", "removed": False},
            {"id": "removed", "removed": True},
        ]
        assert cursor == "https://graph.example/delta?$deltatoken=2"
        assert mock_get.call_args_list[0].kwargs["headers"]["Prefer"] == "odata.maxpagesize=50"

    # Validates: SEL-028
    @patch("selko.services.msgraph.requests.get")
    def test_410_returns_resync_sentinel(self, mock_get):
        mock_get.return_value = _response({}, status_code=410)

        changes, cursor = fetch_message_changes("token", "expired-delta-link")

        assert changes == []
        assert cursor == RESYNC_REQUIRED


class TestOutlookTokenRefresh:
    """The integration row is the integrations service's to read; here it is a fixed row."""

    @staticmethod
    def _expired_row():
        return {
            "status": "active",
            "access_token": "expired",
            "refresh_token": "old-refresh",
            "token_expiry": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
        }

    def test_refreshes_expired_token_and_persists_rotation(self, db, mock_config):
        client = db
        msal_app = MagicMock()
        msal_app.acquire_token_by_refresh_token.return_value = {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        }

        with (
            patch("selko.services.outlook.get_provider_integration", return_value=self._expired_row()),
            patch("selko.services.outlook._msal_app", return_value=msal_app),
            patch("selko.services.outlook.update_provider_tokens") as update_tokens,
        ):
            token = get_access_token(client, mock_config, "user-1")

        assert token == "new-access"
        msal_app.acquire_token_by_refresh_token.assert_called_once_with(
            "old-refresh", scopes=["Mail.Read", "User.Read"]
        )
        assert update_tokens.call_args.kwargs["refresh_token"] == "new-refresh"

    def test_invalid_grant_marks_integration_expired(self, db, mock_config):
        client = db
        msal_app = MagicMock()
        msal_app.acquire_token_by_refresh_token.return_value = {
            "error": "invalid_grant",
            "error_description": "refresh token revoked",
        }

        with (
            patch("selko.services.outlook.get_provider_integration", return_value=self._expired_row()),
            patch("selko.services.outlook._msal_app", return_value=msal_app),
            patch("selko.services.outlook.update_integration_status") as update_status,
            pytest.raises(Exception, match="refresh token revoked"),
        ):
            get_access_token(client, mock_config, "user-1")

        update_status.assert_called_once_with(client, "outlook", "expired", user_id="user-1")


def test_get_access_token_requires_the_owner(db, mock_config):
    """No signed-in session exists to guess the owner from: a missing owner is an error."""
    from selko.services.outlook import OutlookError

    with pytest.raises(OutlookError, match="owner"):
        get_access_token(db, mock_config)
