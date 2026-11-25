"""Unit tests for Gmail service helpers."""

from datetime import datetime
from unittest.mock import MagicMock

from selko.services.gmail import DEFAULT_MESSAGE_QUERY, fetch_messages
from selko.services.integrations import _parse_token_expiry, get_oauth_credentials


def _mock_gmail_service(list_return=None):
    """Build a Gmail service mock with a controllable messages().list()."""
    if list_return is None:
        list_return = {"messages": []}

    list_mock = MagicMock()
    list_mock.return_value.execute.return_value = list_return

    messages_mock = MagicMock()
    messages_mock.list = list_mock

    users_mock = MagicMock()
    users_mock.messages.return_value = messages_mock

    service = MagicMock()
    service.users.return_value = users_mock
    return service, list_mock


class TestFetchMessages:
    """Tests for fetch_messages label/query filtering."""

    def test_default_applies_exclusion_query(self):
        """Default fetch excludes spam/trash/drafts/sent/noisy categories."""
        service, list_mock = _mock_gmail_service()

        fetch_messages(service, max_results=10)

        list_mock.assert_called_once_with(
            userId="me",
            maxResults=10,
            q=DEFAULT_MESSAGE_QUERY,
        )
        assert "labelIds" not in list_mock.call_args.kwargs
        assert "-category:promotions" in DEFAULT_MESSAGE_QUERY
        assert "-in:spam" in DEFAULT_MESSAGE_QUERY

    def test_explicit_inbox_filter_still_supported(self):
        """Callers can still request INBOX-only pulls."""
        service, list_mock = _mock_gmail_service()

        fetch_messages(service, max_results=5, label_ids=["INBOX"])

        list_mock.assert_called_once_with(
            userId="me",
            maxResults=5,
            labelIds=["INBOX"],
            q=DEFAULT_MESSAGE_QUERY,
        )

    def test_empty_query_disables_search_filter(self):
        """Pass query='' to omit the Gmail search filter."""
        service, list_mock = _mock_gmail_service()

        fetch_messages(service, max_results=3, query="")

        list_mock.assert_called_once_with(userId="me", maxResults=3)
        assert "q" not in list_mock.call_args.kwargs


class TestParseTokenExpiry:
    """Tests for token_expiry parsing used by get_oauth_credentials."""

    def test_parses_odd_fractional_seconds(self):
        """Google refresh tokens may use 5-digit fractional seconds."""
        expiry = _parse_token_expiry("2026-07-11T05:21:38.35908+00:00")
        assert expiry == datetime(2026, 7, 11, 5, 21, 38, 359080)
        assert expiry.tzinfo is None

    def test_parses_zulu_timestamp(self):
        expiry = _parse_token_expiry("2026-07-11T04:08:40Z")
        assert expiry == datetime(2026, 7, 11, 4, 8, 40)


class TestGetOAuthCredentialsExpiry:
    """Reconstructing Credentials with token expiry, from a real integrations row."""

    @staticmethod
    def _gmail(factory, token_expiry: str) -> str:
        user = factory.user()
        factory.integration(
            user, provider="gmail", access_token="access-token", refresh_token="refresh-token",
            token_expiry=token_expiry, scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        )
        return user

    def test_sets_naive_utc_expiry_from_db(self, db, factory, mock_config):
        """token_expiry from DB is applied as naive UTC for google-auth."""
        user = self._gmail(factory, "2026-07-11T04:08:40.000000Z")

        creds = get_oauth_credentials(db, mock_config, "gmail", user_id=user)

        assert creds is not None
        assert creds.token == "access-token"
        assert creds.expiry == datetime(2026, 7, 11, 4, 8, 40)
        assert creds.expiry.tzinfo is None
        # Ensure .expired is comparable (no naive/aware TypeError)
        assert isinstance(creds.expired, bool)

    def test_handles_fractional_expiry(self, db, factory, mock_config):
        """Regression: fractional seconds must not crash credential load."""
        user = self._gmail(factory, "2026-07-11T05:21:38.359080Z")

        creds = get_oauth_credentials(db, mock_config, "gmail", user_id=user)

        assert creds is not None
        assert creds.expiry == datetime(2026, 7, 11, 5, 21, 38, 359080)

    def test_another_users_integration_is_not_read(self, db, factory, mock_config):
        self._gmail(factory, "2026-07-11T04:08:40.000000Z")

        assert get_oauth_credentials(db, mock_config, "gmail", user_id=factory.user()) is None


# R2 regression: batch callback exceptions used to be swallowed by googleapiclient
from googleapiclient.errors import HttpError
from google.auth.exceptions import RefreshError
from selko.services.gmail import get_messages_metadata_batch, GmailError, GmailAuthError


class _FakeResp:
    def __init__(self, status):
        self.status = status
        self.reason = "reason"


def _make_http_error(status):
    import json
    content = json.dumps({"error": {"code": status, "message": "err"}}).encode()
    return HttpError(resp=_FakeResp(status), content=content)


class TestGetMessagesMetadataBatch:
    def test_404_in_batch_becomes_deleted_not_failure(self):
        """Per-message 404 (deleted between listing and fetch) must become _deleted."""
        service = MagicMock()

        def fake_batch():
            b = MagicMock()

            def add(req, callback=None, request_id=None):
                if request_id == "msg-404":
                    callback(request_id, None, _make_http_error(404))
                else:
                    callback(request_id, {"id": request_id, "labelIds": ["INBOX"]}, None)
            b.add.side_effect = add
            b.execute.return_value = None
            return b

        service.new_batch_http_request.side_effect = fake_batch
        service.users.return_value.messages.return_value.get.return_value = MagicMock()
        result = get_messages_metadata_batch(service, ["msg-ok", "msg-404"])
        assert result["msg-ok"]["labelIds"] == ["INBOX"]
        assert result["msg-404"] == {"id": "msg-404", "_deleted": True}

    def test_transient_500_is_not_swallowed(self):
        """One 500 in a 100-chunk must not silently disappear — it raises transient."""
        service = MagicMock()

        def fake_batch():
            b = MagicMock()

            def add(req, callback=None, request_id=None):
                if request_id == "msg-500":
                    callback(request_id, None, _make_http_error(500))
                else:
                    callback(request_id, {"id": request_id, "labelIds": ["INBOX"]}, None)
            b.add.side_effect = add
            b.execute.return_value = None
            return b

        service.new_batch_http_request.side_effect = fake_batch
        service.users.return_value.messages.return_value.get.return_value = MagicMock()
        try:
            get_messages_metadata_batch(service, ["msg-ok", "msg-500"])
            assert False, "expected transient GmailError"
        except GmailError as e:
            assert e.status_code == 500
            assert "partial failure" in str(e)

    def test_auth_in_batch_aborts(self):
        """Auth error in callback must surface as GmailAuthError, not swallow."""
        service = MagicMock()

        def fake_batch():
            b = MagicMock()

            def add(req, callback=None, request_id=None):
                callback(request_id, None, RefreshError("invalid_grant"))
            b.add.side_effect = add
            b.execute.return_value = None
            return b

        service.new_batch_http_request.side_effect = fake_batch
        service.users.return_value.messages.return_value.get.return_value = MagicMock()
        try:
            get_messages_metadata_batch(service, ["msg-1"])
            assert False, "expected GmailAuthError"
        except GmailAuthError:
            pass
