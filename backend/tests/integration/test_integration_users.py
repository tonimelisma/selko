"""Integration tests for user management service.

Tests admin operations using service role key.
"""

from uuid import uuid4

import pytest

from selko.services.users import (
    UserManagementError,
    create_user,
    delete_user,
    get_admin_client,
    get_user,
    list_users,
)


@pytest.mark.integration
@pytest.mark.development
class TestUserManagement:
    """Test user management with real Supabase."""

    def test_create_user_development(self, config):
        """Create user with auto-confirm in development."""
        email = f"test-{uuid4()}@selko.local"
        password = "testpass123"

        user = create_user(config, email, password, auto_confirm=True)

        assert user["id"] is not None
        assert user["email"] == email
        assert len(user["id"]) == 36  # UUID format

        # Cleanup
        delete_user(config, user["id"])

    def test_list_users(self, config, temp_user):
        """List users includes created user."""
        user_id, email, _ = temp_user

        users = list_users(config)

        assert len(users) > 0
        user_ids = [u["id"] for u in users]
        assert user_id in user_ids

    def test_get_user(self, config, temp_user):
        """Get specific user by ID."""
        user_id, email, _ = temp_user

        user = get_user(config, user_id)

        assert user["id"] == user_id
        assert user["email"] == email

    def test_delete_user(self, config):
        """Delete user removes from auth."""
        email = f"test-{uuid4()}@selko.local"
        user = create_user(config, email, "testpass123", auto_confirm=True)
        user_id = user["id"]

        result = delete_user(config, user_id)

        assert result is True

        # Verify user is gone
        with pytest.raises(UserManagementError):
            get_user(config, user_id)

    def test_create_duplicate_user(self, config, temp_user):
        """Creating duplicate user raises error."""
        _, email, _ = temp_user

        with pytest.raises(UserManagementError) as exc_info:
            create_user(config, email, "anotherpassword")

        assert "already" in str(exc_info.value).lower() or "exists" in str(
            exc_info.value
        ).lower() or "registered" in str(exc_info.value).lower()

    def test_delete_nonexistent_user(self, config):
        """Deleting nonexistent user raises error."""
        fake_id = str(uuid4())

        with pytest.raises(UserManagementError):
            delete_user(config, fake_id)

    def test_get_admin_client_no_service_key(self, config):
        """Admin client fails without service role key."""
        from selko.config import Config

        no_key_config = Config(
            environment=config.environment,
            supabase_url=config.supabase_url,
            supabase_key=config.supabase_key,
            supabase_service_role_key=None,
        )

        with pytest.raises(UserManagementError) as exc_info:
            get_admin_client(no_key_config)

        assert "SERVICE_ROLE_KEY" in str(exc_info.value)

    def test_user_profile_auto_created(self, config, admin_client):
        """User profile in public.users is auto-created by trigger."""
        email = f"test-{uuid4()}@selko.local"
        user = create_user(config, email, "testpass123", auto_confirm=True)
        user_id = user["id"]

        try:
            # Check public.users table (using admin client to bypass RLS)
            result = (
                admin_client.table("users")
                .select("*")
                .eq("id", user_id)
                .single()
                .execute()
            )

            assert result.data is not None
            assert result.data["id"] == user_id
            assert result.data["email"] == email
        finally:
            delete_user(config, user_id)


@pytest.mark.integration
@pytest.mark.staging
class TestUserManagementStaging:
    """Test user management in staging (no auto-confirm)."""

    def test_create_user_staging_no_auto_confirm(self, config):
        """In staging, users are NOT auto-confirmed."""
        # Note: This test creates a user that will need email confirmation
        # We can still verify the user is created, just not auto-confirmed

        email = f"test-{uuid4()}@selko.local"
        password = "testpass123"

        user = create_user(config, email, password)

        assert user["id"] is not None
        assert user["email"] == email

        # Cleanup
        delete_user(config, user["id"])

    def test_list_users_staging(self, config):
        """List users works in staging."""
        users = list_users(config)

        assert isinstance(users, list)
        # Should have at least the test user
        assert len(users) >= 1
