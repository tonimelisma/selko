"""Unit tests for Microsoft Graph Outlook ingestion."""

import base64
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from selko.services.outlook import (
    RESYNC_REQUIRED,
    GraphHttpError,
    get_access_token,
    fetch_message_changes,
    parse_outlook_message,
    synthesize_labels,
)
from selko.workers.email_fetch import _store_outlook_attachments
from selko.workers.email_fetch import process_email_fetch_task, schedule_email_fetches


def _response(payload, status_code=200):
    response = MagicMock()
    response.status_code = status_code
    response.json.return_value = payload
    response.text = "graph error"
    return response


class TestParseOutlookMessage:
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
            "body_html": None,
            "body_text": "Plain text body",
            "is_calendar_invite": False,
        }

    def test_omits_empty_recipients_and_html_body(self):
        result = parse_outlook_message(
            {
                "id": "message-2",
                "toRecipients": [],
                "body": {"contentType": "html", "content": "<p>HTML</p>"},
            }
        )

        assert result["to_emails"] is None
        assert result["body_html"] is None
        assert "body_text" not in result

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
    @patch("selko.services.outlook.requests.get")
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

    @patch("selko.services.outlook.requests.get")
    def test_410_returns_resync_sentinel(self, mock_get):
        mock_get.return_value = _response({}, status_code=410)

        changes, cursor = fetch_message_changes("token", "expired-delta-link")

        assert changes == []
        assert cursor == RESYNC_REQUIRED


class TestOutlookTokenRefresh:
    def test_refreshes_expired_token_and_persists_rotation(self, mock_config):
        client = MagicMock()
        client.table().select().eq().eq().maybe_single().execute.return_value = MagicMock(
            data={
                "status": "active",
                "access_token": "expired",
                "refresh_token": "old-refresh",
                "token_expiry": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
            }
        )
        msal_app = MagicMock()
        msal_app.acquire_token_by_refresh_token.return_value = {
            "access_token": "new-access",
            "refresh_token": "new-refresh",
            "expires_in": 3600,
        }

        with (
            patch("selko.services.outlook._msal_app", return_value=msal_app),
            patch("selko.services.outlook.update_provider_tokens") as update_tokens,
        ):
            token = get_access_token(client, mock_config, "user-1")

        assert token == "new-access"
        msal_app.acquire_token_by_refresh_token.assert_called_once_with(
            "old-refresh", scopes=["Mail.Read", "User.Read"]
        )
        assert update_tokens.call_args.kwargs["refresh_token"] == "new-refresh"

    def test_invalid_grant_marks_integration_expired(self, mock_config):
        client = MagicMock()
        client.table().select().eq().eq().maybe_single().execute.return_value = MagicMock(
            data={
                "status": "active",
                "access_token": "expired",
                "refresh_token": "old-refresh",
                "token_expiry": (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
            }
        )
        msal_app = MagicMock()
        msal_app.acquire_token_by_refresh_token.return_value = {
            "error": "invalid_grant",
            "error_description": "refresh token revoked",
        }

        with (
            patch("selko.services.outlook._msal_app", return_value=msal_app),
            patch("selko.services.outlook.update_integration_status") as update_status,
            pytest.raises(Exception, match="refresh token revoked"),
        ):
            get_access_token(client, mock_config, "user-1")

        update_status.assert_called_once_with(client, "outlook", "expired", user_id="user-1")


class TestOutlookAttachments:
    def test_decodes_standard_base64_and_skips_non_file_attachments(self, mock_config):
        client = MagicMock()
        encoded = base64.b64encode(b"outlook bytes").decode("ascii")

        with (
            patch("selko.workers.email_fetch.list_attachments", return_value=[
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "id": "file-1",
                    "name": "document.txt",
                    "contentType": "text/plain",
                    "contentBytes": encoded,
                    "isInline": False,
                },
                {"@odata.type": "#microsoft.graph.itemAttachment", "id": "item-1"},
            ]),
            patch("selko.workers.email_fetch.store_attachment_bytes") as store,
        ):
            _store_outlook_attachments(client, mock_config, "user-1", "email-1", "message-1", "token")

        store.assert_called_once()
        assert store.call_args.kwargs["data"] == b"outlook bytes"
        assert store.call_args.kwargs["provider_attachment_id"] == "file-1"


class TestOutlookWorkerDispatch:
    @pytest.mark.asyncio
    async def test_processes_outlook_payload(self, mock_config):
        client = MagicMock()
        client.table().select().eq().eq().maybe_single().execute.return_value = MagicMock(
            data={"sync_cursor": "cursor-1"}
        )
        message = {"id": "message-1"}

        with (
            patch("selko.workers.email_fetch.get_access_token", return_value="token"),
            patch("selko.workers.email_fetch.fetch_message_changes", return_value=([{"id": "message-1", "removed": False}], "cursor-2")),
            patch("selko.workers.email_fetch.get_full_message", return_value=message),
            patch("selko.workers.email_fetch.parse_outlook_message", return_value={"provider_message_id": "message-1", "email_provider": "outlook"}),
            patch("selko.workers.email_fetch.save_emails", return_value=[{"id": "email-1"}]),
            patch("selko.workers.email_fetch._store_outlook_attachments"),
        ):
            await process_email_fetch_task(
                client,
                mock_config,
                {"user_id": "user-1", "provider": "outlook"},
            )

        client.table().update.assert_called_with({"sync_cursor": "cursor-2"})

    @pytest.mark.asyncio
    async def test_scheduler_enqueues_gmail_and_outlook(self):
        client = MagicMock()
        integrations_result = MagicMock(data=[
            {"user_id": "user-1", "provider": "gmail"},
            {"user_id": "user-1", "provider": "outlook"},
        ])
        existing_result = MagicMock(data=[])
        client.table().select().in_().eq().execute.return_value = integrations_result
        client.table().select().eq().in_().execute.return_value = existing_result

        with (
            patch("selko.config.load_config"),
            patch("selko.services.auth.get_service_client", return_value=client),
            patch("selko.workers.email_fetch.enqueue_scheduled_task") as enqueue,
        ):
            await schedule_email_fetches()

        assert enqueue.call_count == 2
        providers = {call.kwargs["payload"]["provider"] for call in enqueue.call_args_list}
        assert providers == {"gmail", "outlook"}
