"""Unit tests for Gmail service helpers."""

from datetime import datetime
from unittest.mock import MagicMock, patch

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
    """Tests for reconstructing Credentials with token expiry."""

    def test_sets_naive_utc_expiry_from_db(self, mock_supabase_client, mock_config):
        """token_expiry from DB is applied as naive UTC for google-auth."""
        mock_supabase_client.table().select().eq().eq().maybe_single().execute.return_value = MagicMock(
            data={
                "status": "active",
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "token_expiry": "2026-07-11T04:08:40+00:00",
                "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
            }
        )

        with patch(
            "selko.services.integrations.get_current_user_id",
            return_value="test-user-id",
        ):
            creds = get_oauth_credentials(
                mock_supabase_client, mock_config, "gmail"
            )

        assert creds is not None
        assert creds.expiry == datetime(2026, 7, 11, 4, 8, 40)
        assert creds.expiry.tzinfo is None
        # Ensure .expired is comparable (no naive/aware TypeError)
        assert isinstance(creds.expired, bool)

    def test_handles_five_digit_fractional_expiry(
        self, mock_supabase_client, mock_config
    ):
        """Regression: 5-digit fractional seconds must not crash credential load."""
        mock_supabase_client.table().select().eq().eq().maybe_single().execute.return_value = MagicMock(
            data={
                "status": "active",
                "access_token": "access-token",
                "refresh_token": "refresh-token",
                "token_expiry": "2026-07-11T05:21:38.35908+00:00",
                "scopes": ["https://www.googleapis.com/auth/gmail.readonly"],
            }
        )

        creds = get_oauth_credentials(
            mock_supabase_client, mock_config, "gmail", user_id="u1"
        )

        assert creds is not None
        assert creds.expiry == datetime(2026, 7, 11, 5, 21, 38, 359080)
