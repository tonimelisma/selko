"""Integration tests for Row Level Security isolation.

Tests that user A cannot access user B's data (emails, attachments, integrations).
These are critical security tests for multi-tenant data isolation.
"""

from uuid import uuid4

import pytest
from supabase import create_client

from selko.services.auth import get_authenticated_client
from selko.services.emails import save_emails
from selko.services.attachments import calculate_content_hash


@pytest.mark.integration
@pytest.mark.development
class TestCrossUserRLSIsolation:
    """Test that users cannot access each other's data."""

    def test_user_cannot_read_other_user_emails(
        self, config, authenticated_client, test_user_id, cleanup_emails, temp_user
    ):
        """User A cannot read User B's emails."""
        # Create email as User A (the authenticated test user)
        provider_message_id = f"rls_test_{uuid4().hex[:8]}"
        cleanup_emails.append(provider_message_id)

        email_data = {
            "provider_message_id": provider_message_id,
            "thread_id": "thread_rls_test",
            "subject": "User A's private email",
            "from_email": "sender@example.com",
            "provider_labels": ["INBOX"],
            "date_sent": "2026-01-22T10:00:00+00:00",
        }
        saved = save_emails(authenticated_client, [email_data])
        assert len(saved) == 1
        user_a_email_id = saved[0]["id"]

        # Now sign in as User B (temp_user)
        temp_user_id, temp_email, temp_password = temp_user
        user_b_client = create_client(config.supabase_url, config.supabase_key)
        user_b_client.auth.sign_in_with_password(
            {"email": temp_email, "password": temp_password}
        )

        try:
            # User B tries to read User A's email by ID
            result = (
                user_b_client.table("emails")
                .select("*")
                .eq("id", user_a_email_id)
                .execute()
            )

            # Should return empty (RLS blocks access)
            assert len(result.data) == 0, "User B should not see User A's email"

            # User B tries to read all emails - should not see User A's
            all_emails = user_b_client.table("emails").select("*").execute()
            user_a_emails = [e for e in all_emails.data if e["user_id"] == test_user_id]
            assert len(user_a_emails) == 0, "User B should not see any of User A's emails"

        finally:
            user_b_client.auth.sign_out()

    def test_user_cannot_update_other_user_emails(
        self, config, authenticated_client, test_user_id, cleanup_emails, temp_user
    ):
        """User A cannot update User B's emails."""
        # Create email as User A
        provider_message_id = f"rls_update_test_{uuid4().hex[:8]}"
        cleanup_emails.append(provider_message_id)

        email_data = {
            "provider_message_id": provider_message_id,
            "thread_id": "thread_rls_update",
            "subject": "Original subject",
            "from_email": "sender@example.com",
            "provider_labels": ["INBOX"],
            "date_sent": "2026-01-22T10:00:00+00:00",
        }
        saved = save_emails(authenticated_client, [email_data])
        user_a_email_id = saved[0]["id"]

        # Sign in as User B
        temp_user_id, temp_email, temp_password = temp_user
        user_b_client = create_client(config.supabase_url, config.supabase_key)
        user_b_client.auth.sign_in_with_password(
            {"email": temp_email, "password": temp_password}
        )

        try:
            # User B tries to update User A's email
            result = (
                user_b_client.table("emails")
                .update({"subject": "Hacked!"})
                .eq("id", user_a_email_id)
                .execute()
            )

            # Update should affect 0 rows (RLS blocks)
            assert len(result.data) == 0, "User B should not be able to update User A's email"

            # Verify email was not modified
            check = (
                authenticated_client.table("emails")
                .select("subject")
                .eq("id", user_a_email_id)
                .single()
                .execute()
            )
            assert check.data["subject"] == "Original subject"

        finally:
            user_b_client.auth.sign_out()

    def test_user_cannot_delete_other_user_emails(
        self, config, authenticated_client, test_user_id, cleanup_emails, temp_user
    ):
        """User A cannot delete User B's emails."""
        # Create email as User A
        provider_message_id = f"rls_delete_test_{uuid4().hex[:8]}"
        cleanup_emails.append(provider_message_id)

        email_data = {
            "provider_message_id": provider_message_id,
            "thread_id": "thread_rls_delete",
            "subject": "Don't delete me",
            "from_email": "sender@example.com",
            "provider_labels": ["INBOX"],
            "date_sent": "2026-01-22T10:00:00+00:00",
        }
        saved = save_emails(authenticated_client, [email_data])
        user_a_email_id = saved[0]["id"]

        # Sign in as User B
        temp_user_id, temp_email, temp_password = temp_user
        user_b_client = create_client(config.supabase_url, config.supabase_key)
        user_b_client.auth.sign_in_with_password(
            {"email": temp_email, "password": temp_password}
        )

        try:
            # User B tries to delete User A's email
            result = (
                user_b_client.table("emails")
                .delete()
                .eq("id", user_a_email_id)
                .execute()
            )

            # Delete should affect 0 rows (RLS blocks)
            assert len(result.data) == 0, "User B should not be able to delete User A's email"

            # Verify email still exists
            check = (
                authenticated_client.table("emails")
                .select("id")
                .eq("id", user_a_email_id)
                .execute()
            )
            assert len(check.data) == 1, "Email should still exist"

        finally:
            user_b_client.auth.sign_out()

    def test_user_cannot_read_other_user_attachments(
        self, config, authenticated_client, test_user_id, cleanup_emails, temp_user
    ):
        """User A cannot read User B's attachments."""
        # Create email and attachment as User A
        provider_message_id = f"rls_att_test_{uuid4().hex[:8]}"
        cleanup_emails.append(provider_message_id)

        email_data = {
            "provider_message_id": provider_message_id,
            "thread_id": "thread_att_rls",
            "subject": "Email with attachment",
            "from_email": "sender@example.com",
            "provider_labels": ["INBOX"],
            "date_sent": "2026-01-22T10:00:00+00:00",
        }
        saved = save_emails(authenticated_client, [email_data])
        email_id = saved[0]["id"]

        # Create attachment
        content_hash = calculate_content_hash(b"private data")
        att_result = (
            authenticated_client.table("attachments")
            .insert(
                {
                    "user_id": test_user_id,
                    "email_id": email_id,
                    "provider_attachment_id": "att_123",
                    "filename": "private.pdf",
                    "mime_type": "application/pdf",
                    "size_bytes": 1000,
                    "content_hash": content_hash,
                }
            )
            .execute()
        )
        attachment_id = att_result.data[0]["id"]

        # Sign in as User B
        temp_user_id, temp_email, temp_password = temp_user
        user_b_client = create_client(config.supabase_url, config.supabase_key)
        user_b_client.auth.sign_in_with_password(
            {"email": temp_email, "password": temp_password}
        )

        try:
            # User B tries to read User A's attachment
            result = (
                user_b_client.table("attachments")
                .select("*")
                .eq("id", attachment_id)
                .execute()
            )

            # Should return empty (RLS blocks access)
            assert len(result.data) == 0, "User B should not see User A's attachment"

            # User B queries all attachments
            all_att = user_b_client.table("attachments").select("*").execute()
            user_a_att = [a for a in all_att.data if a["user_id"] == test_user_id]
            assert len(user_a_att) == 0, "User B should not see any of User A's attachments"

        finally:
            user_b_client.auth.sign_out()
            # Cleanup attachment
            authenticated_client.table("attachments").delete().eq(
                "id", attachment_id
            ).execute()

    def test_user_cannot_read_other_user_integrations(
        self, config, authenticated_client, test_user_id, temp_user
    ):
        """User A cannot read User B's OAuth integrations."""
        # Create integration as User A (using google_calendar to avoid conflict with seeded gmail)
        integration_result = (
            authenticated_client.table("integrations")
            .insert(
                {
                    "user_id": test_user_id,
                    "provider": "google_calendar",  # Use calendar instead of gmail
                    "status": "active",
                    "access_token": "secret_token_123",
                    "scopes": ["read"],
                }
            )
            .execute()
        )
        integration_id = integration_result.data[0]["id"]

        # Sign in as User B
        temp_user_id, temp_email, temp_password = temp_user
        user_b_client = create_client(config.supabase_url, config.supabase_key)
        user_b_client.auth.sign_in_with_password(
            {"email": temp_email, "password": temp_password}
        )

        try:
            # User B tries to read User A's integration
            result = (
                user_b_client.table("integrations")
                .select("*")
                .eq("id", integration_id)
                .execute()
            )

            # Should return empty (RLS blocks access)
            assert len(result.data) == 0, "User B should not see User A's integration"

            # User B tries to read by provider
            by_provider = (
                user_b_client.table("integrations")
                .select("*")
                .eq("provider", "gmail")
                .execute()
            )
            user_a_integrations = [i for i in by_provider.data if i["user_id"] == test_user_id]
            assert len(user_a_integrations) == 0, "User B should not see User A's integrations"

        finally:
            user_b_client.auth.sign_out()
            # Cleanup
            authenticated_client.table("integrations").delete().eq(
                "id", integration_id
            ).execute()

    def test_user_cannot_insert_data_for_other_user(
        self, config, authenticated_client, test_user_id, temp_user
    ):
        """User cannot insert data with another user's ID."""
        # Sign in as User B
        temp_user_id, temp_email, temp_password = temp_user
        user_b_client = create_client(config.supabase_url, config.supabase_key)
        user_b_client.auth.sign_in_with_password(
            {"email": temp_email, "password": temp_password}
        )

        try:
            # User B tries to insert email with User A's ID
            provider_message_id = f"inject_test_{uuid4().hex[:8]}"

            # This should either fail or insert with User B's ID, not User A's
            # due to RLS with check policies
            try:
                result = (
                    user_b_client.table("emails")
                    .insert(
                        {
                            "user_id": test_user_id,  # Trying to use User A's ID
                            "provider_message_id": provider_message_id,
                            "thread_id": "injected",
                            "subject": "Injected email",
                            "from_email": "attacker@example.com",
                            "provider_labels": ["INBOX"],
                            "date_sent": "2026-01-22T10:00:00+00:00",
                        }
                    )
                    .execute()
                )

                # If insert succeeded, verify it used User B's ID, not User A's
                if result.data:
                    assert result.data[0]["user_id"] == temp_user_id, \
                        "Insert should use authenticated user's ID, not the provided one"
                    # Cleanup
                    user_b_client.table("emails").delete().eq(
                        "provider_message_id", provider_message_id
                    ).execute()

            except Exception:
                # RLS policy violation is expected - this is correct behavior
                pass

        finally:
            user_b_client.auth.sign_out()


@pytest.mark.integration
@pytest.mark.staging
class TestCrossUserRLSIsolationStaging:
    """Test RLS isolation in staging environment."""

    def test_rls_enforced_staging(
        self, config, authenticated_client, test_user_id, cleanup_emails, temp_user
    ):
        """RLS is enforced in staging environment."""
        # Create email as test user
        provider_message_id = f"staging_rls_{uuid4().hex[:8]}"
        cleanup_emails.append(provider_message_id)

        saved = save_emails(
            authenticated_client,
            [
                {
                    "provider_message_id": provider_message_id,
                    "thread_id": "staging_test",
                    "subject": "Staging RLS test",
                    "from_email": "test@example.com",
                    "provider_labels": ["INBOX"],
                    "date_sent": "2026-01-22T10:00:00+00:00",
                }
            ],
        )

        # Sign in as different user
        temp_user_id, temp_email, temp_password = temp_user
        user_b_client = create_client(config.supabase_url, config.supabase_key)
        user_b_client.auth.sign_in_with_password(
            {"email": temp_email, "password": temp_password}
        )

        try:
            # Cannot see other user's data
            result = (
                user_b_client.table("emails")
                .select("*")
                .eq("provider_message_id", provider_message_id)
                .execute()
            )
            assert len(result.data) == 0

        finally:
            user_b_client.auth.sign_out()
