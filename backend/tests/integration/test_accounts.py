"""services/users.py over a real SQLite database.

Successor of test_integration_users.py (docs/specs/sqlite-single-process/
05-verification.md §A.2 row 37): create/list/get/delete, a duplicate email
refused, and the ``users`` profile row created with the account (the
successor of GoTrue's ``handle_new_user`` trigger). The staging half is gone
with staging.
"""

from uuid import uuid4

import pytest

from selko.db import runtime
from selko.services import accounts
from selko.services.users import (
    UserManagementError,
    create_user,
    delete_user,
    get_admin_client,
    get_user,
    list_users,
)


@pytest.fixture
def process_db(db):
    runtime.use_database(db)
    yield db
    runtime.use_database(None)


def _email():
    return f"test-{uuid4()}@selko.local"


class TestUserManagement:
    def test_create_user(self, mock_config, process_db):
        email = _email()
        user = create_user(mock_config, email, "testpass123", auto_confirm=True)

        assert user["email"] == email
        assert len(user["id"]) == 36  # UUID format
        account = process_db.query_one("SELECT * FROM accounts WHERE id = ?", (user["id"],))
        assert account["email_confirmed_at"] is not None
        assert account["password_hash"].startswith("$2"), "bcrypt"
        assert accounts.password_matches("testpass123", account["password_hash"])

    def test_create_user_unconfirmed_by_default(self, mock_config, process_db):
        user = create_user(mock_config, _email(), "testpass123")
        account = process_db.query_one("SELECT email_confirmed_at FROM accounts WHERE id = ?", (user["id"],))
        assert account[0] is None

    def test_created_user_can_sign_in(self, mock_config, process_db):
        email = _email()
        create_user(mock_config, email, "testpass123", auto_confirm=True)
        keys = accounts.TokenKeys("k" * 40)
        signed_in = accounts.sign_in(process_db, keys, email, "testpass123")
        assert accounts.verify_access_token(keys, signed_in.access_token).email == email

    def test_list_users(self, mock_config, process_db):
        user = create_user(mock_config, _email(), "testpass123", auto_confirm=True)
        assert user in list_users(mock_config)

    def test_get_user(self, mock_config, process_db):
        email = _email()
        user = create_user(mock_config, email, "testpass123", auto_confirm=True)
        assert get_user(mock_config, user["id"]) == {"id": user["id"], "email": email}

    def test_get_unknown_user_raises(self, mock_config, process_db):
        with pytest.raises(UserManagementError):
            get_user(mock_config, str(uuid4()))

    def test_delete_user_cascades(self, mock_config, process_db, factory):
        user = create_user(mock_config, _email(), "testpass123", auto_confirm=True)
        factory.integration(user["id"], "gmail")

        assert delete_user(mock_config, user["id"]) is True

        with pytest.raises(UserManagementError):
            get_user(mock_config, user["id"])
        assert process_db.query_one("SELECT 1 FROM users WHERE id = ?", (user["id"],)) is None
        assert process_db.query_one("SELECT 1 FROM integrations WHERE user_id = ?", (user["id"],)) is None

    def test_create_duplicate_user(self, mock_config, process_db):
        email = _email()
        create_user(mock_config, email, "testpass123")
        with pytest.raises(UserManagementError) as exc_info:
            create_user(mock_config, email.upper(), "anotherpassword")
        assert "already" in str(exc_info.value).lower()

    def test_weak_password_is_refused(self, mock_config, process_db):
        with pytest.raises(UserManagementError):
            create_user(mock_config, _email(), "x")

    def test_delete_nonexistent_user(self, mock_config, process_db):
        with pytest.raises(UserManagementError):
            delete_user(mock_config, str(uuid4()))

    def test_admin_client_is_the_process_database(self, mock_config, process_db):
        assert get_admin_client(mock_config) is process_db

    def test_user_profile_created_with_the_account(self, mock_config, process_db):
        email = _email()
        user = create_user(mock_config, email, "testpass123", auto_confirm=True)
        profile = process_db.query_one("SELECT * FROM users WHERE id = ?", (user["id"],))
        assert profile["email"] == email
        assert profile["display_name"] == email.split("@")[0]
