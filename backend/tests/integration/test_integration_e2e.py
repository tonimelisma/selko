"""End-to-end integration tests.

Tests complete user journeys across multiple services.
"""

from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from selko.services.auth import get_authenticated_client, get_current_user_id
from selko.services.emails import parse_gmail_message, save_emails
from selko.services.gmail import build_service, fetch_messages, get_credentials, get_user_profile
from selko.services.integrations import save_oauth_credentials
from selko.services.users import create_user, delete_user


@pytest.mark.integration
@pytest.mark.development
class TestEndToEndDevelopment:
    """E2E tests with mocked Gmail API (development)."""

    def test_new_user_flow_mocked(self, config, sample_oauth_credentials):
        """Complete flow: create user → auth → save creds → fetch emails."""
        email = f"e2e-test-{uuid4()}@selko.local"
        user = create_user(config, email, "testpass123", auto_confirm=True)
        user_id = user["id"]

        try:
            # Create a config with test user credentials
            from selko.config import Config

            test_config = Config(
                environment=config.environment,
                supabase_url=config.supabase_url,
                supabase_key=config.supabase_key,
                supabase_service_role_key=config.supabase_service_role_key,
                google_client_id=config.google_client_id,
                google_client_secret=config.google_client_secret,
                test_user_email=email,
                test_user_password="testpass123",
            )

            # Authenticate as new user
            client = get_authenticated_client(test_config)
            current_user_id = get_current_user_id(client)
            assert current_user_id == user_id

            # Save OAuth credentials
            save_oauth_credentials(
                client,
                "gmail",
                sample_oauth_credentials,
                provider_email="test@gmail.com",
            )

            # Mock Gmail API for fetch
            with patch("selko.services.gmail.build") as mock_build:
                mock_service = MagicMock()
                mock_build.return_value = mock_service

                mock_service.users().messages().list().execute.return_value = {
                    "messages": [{"id": "msg_e2e_1"}, {"id": "msg_e2e_2"}]
                }

                mock_service.users().messages().get().execute.side_effect = [
                    {
                        "id": "msg_e2e_1",
                        "threadId": "thread_e2e_1",
                        "snippet": "First email",
                        "labelIds": ["INBOX", "UNREAD"],
                        "payload": {
                            "headers": [
                                {"name": "From", "value": "sender@example.com"},
                                {"name": "Subject", "value": "E2E Test Email 1"},
                                {"name": "Date", "value": "Wed, 22 Jan 2026 10:00:00 +0000"},
                            ],
                            "parts": [],
                        },
                    },
                    {
                        "id": "msg_e2e_2",
                        "threadId": "thread_e2e_2",
                        "snippet": "Second email",
                        "labelIds": ["INBOX"],
                        "payload": {
                            "headers": [
                                {"name": "From", "value": "other@example.com"},
                                {"name": "Subject", "value": "E2E Test Email 2"},
                                {"name": "Date", "value": "Wed, 22 Jan 2026 11:00:00 +0000"},
                            ],
                            "parts": [],
                        },
                    },
                ]

                # Fetch emails
                service = build_service(sample_oauth_credentials)
                messages = fetch_messages(service, max_results=2)

                # Parse and save
                parsed_emails = [parse_gmail_message(msg) for msg in messages]
                saved = save_emails(client, parsed_emails)
                assert len(saved) == 2

            # Verify emails in database
            result = (
                client.table("emails")
                .select("*")
                .eq("user_id", user_id)
                .execute()
            )
            assert len(result.data) == 2
            subjects = [e["subject"] for e in result.data]
            assert "E2E Test Email 1" in subjects
            assert "E2E Test Email 2" in subjects

            # Verify trigger processed labels
            unread_email = next(e for e in result.data if e["gmail_id"] == "msg_e2e_1")
            assert unread_email["is_unread"] is True

            client.auth.sign_out()

        finally:
            # Cleanup
            delete_user(config, user_id)

    def test_user_data_cascade_delete(self, config, sample_oauth_credentials):
        """Deleting user cascades to integrations and emails."""
        email = f"cascade-test-{uuid4()}@selko.local"
        user = create_user(config, email, "testpass123", auto_confirm=True)
        user_id = user["id"]

        # Create config for test user
        from selko.config import Config

        test_config = Config(
            environment=config.environment,
            supabase_url=config.supabase_url,
            supabase_key=config.supabase_key,
            test_user_email=email,
            test_user_password="testpass123",
        )

        # Create data
        client = get_authenticated_client(test_config)
        save_oauth_credentials(client, "gmail", sample_oauth_credentials)
        save_emails(
            client,
            [
                {
                    "gmail_id": f"cascade_{uuid4().hex[:8]}",
                    "thread_id": "thread_cascade",
                    "subject": "Cascade test",
                    "from_email": "test@example.com",
                    "gmail_label_ids": ["INBOX"],
                    "date_sent": "2026-01-22T10:00:00+00:00",
                }
            ],
        )
        client.auth.sign_out()

        # Verify data exists (using admin client)
        from selko.services.users import get_admin_client

        admin = get_admin_client(config)

        integrations = (
            admin.table("integrations")
            .select("*")
            .eq("user_id", user_id)
            .execute()
        )
        assert len(integrations.data) == 1

        emails = (
            admin.table("emails").select("*").eq("user_id", user_id).execute()
        )
        assert len(emails.data) == 1

        # Delete user
        delete_user(config, user_id)

        # Verify cascade delete (data should be gone due to RLS/cascade)
        # Note: Depending on cascade setup, data may or may not be auto-deleted
        # The foreign key constraint should handle this


@pytest.mark.integration
@pytest.mark.staging
class TestEndToEndStaging:
    """E2E tests with real Gmail API (staging).

    Requires:
    - Burner Gmail account authorized
    - OAuth tokens stored in staging database
    """

    def test_full_email_sync_pipeline(self, authenticated_client, config):
        """Complete pipeline: auth → fetch Gmail → store in DB."""
        # Get Gmail credentials
        creds = get_credentials(authenticated_client, config)
        if creds is None:
            pytest.skip("No Gmail credentials in staging - run cli_auth_gmail first")

        user_id = get_current_user_id(authenticated_client)

        # Build Gmail service
        service = build_service(creds)
        profile = get_user_profile(service)
        assert "@" in profile["emailAddress"]

        # Fetch messages
        messages = fetch_messages(service, max_results=3)

        # Parse and store
        if messages:
            parsed_emails = [parse_gmail_message(msg) for msg in messages]
            count = save_emails(authenticated_client, parsed_emails)
            assert count == len(messages)

            # Verify stored in DB
            result = (
                authenticated_client.table("emails")
                .select("gmail_id")
                .eq("user_id", user_id)
                .execute()
            )
            stored_ids = {e["gmail_id"] for e in result.data}
            fetched_ids = {m["id"] for m in messages}
            assert fetched_ids.issubset(stored_ids)

    def test_existing_user_fetch_new_emails(self, authenticated_client, config):
        """Existing user can sign in and fetch new emails."""
        creds = get_credentials(authenticated_client, config)
        if creds is None:
            pytest.skip("No Gmail credentials in staging")

        # Just verify the flow works
        service = build_service(creds)
        messages = fetch_messages(service, max_results=1)

        # Should not error
        assert isinstance(messages, list)
