"""Integration tests for the attachment service: files on disk, rows in SQLite.

Storage, metadata, de-duplication, deletion and ownership against a real
temporary database and attachments directory. The staging-only tests (a real
Storage bucket, a real staging Gmail inbox) are gone with staging; real-Gmail
coverage waits on the owner's decision about a test token
(docs/specs/sqlite-single-process/README.md, "Owner decisions still open").
"""

from unittest.mock import MagicMock

import pytest

from selko.db.runtime import attachments_dir, use_database
from selko.services.attachments import (
    calculate_content_hash,
    check_duplicate_attachment,
    delete_attachment,
    read_attachment_file,
    save_attachment_metadata,
    upload_to_storage,
)


@pytest.fixture
def store(db):
    use_database(db)
    yield db
    use_database(None)


@pytest.fixture
def config():
    cfg = MagicMock()
    cfg.storage_bucket_attachments = "attachments"
    cfg.max_attachment_size = 10 * 1024 * 1024
    return cfg


@pytest.fixture
def owned_email(factory):
    user = factory.user()
    return user, factory.email(user, subject="Test email with attachments")


SAMPLE = b"This is sample attachment content for testing purposes."


def _stored(store, user, email_id, data=SAMPLE, filename="test_document.txt"):
    path = upload_to_storage(store, user, filename, data, "text/plain")
    return save_attachment_metadata(
        store, email_id=email_id, provider_attachment_id="gmail-att-1", filename=filename,
        mime_type="text/plain", size_bytes=len(data), storage_path=path,
        content_hash=calculate_content_hash(data), user_id=user,
    )


@pytest.mark.integration
class TestAttachmentStorage:
    def test_upload_to_storage(self, store, owned_email):
        user, _ = owned_email
        path = upload_to_storage(store, user, "test_document.txt", SAMPLE, "text/plain")

        assert path.startswith(f"{user}/")
        assert path.endswith("_test_document.txt")
        assert read_attachment_file(path) == SAMPLE
        assert (attachments_dir() / path).stat().st_mode & 0o777 == 0o600

    def test_upload_with_special_filename(self, store, owned_email):
        """Non-ASCII and unsafe characters become a URL-safe name that stays in the user's directory."""
        user, _ = owned_email
        path = upload_to_storage(store, user, "Beslut om klagomål (1049457).pdf", b"%PDF", "application/pdf")

        name = path.split("/", 1)[1]
        assert name.endswith("_Beslut_om_klagomal_1049457_.pdf")
        assert read_attachment_file(path) == b"%PDF"


@pytest.mark.integration
class TestAttachmentMetadata:
    def test_save_attachment_metadata(self, store, owned_email):
        user, email_id = owned_email
        row = _stored(store, user, email_id)

        assert row["user_id"] == user
        assert row["email_id"] == email_id
        assert row["size_bytes"] == len(SAMPLE)
        assert row["content_hash"] == calculate_content_hash(SAMPLE)
        assert row["ingestion_status"] == "pending"

    def test_check_duplicate_attachment_found(self, store, owned_email):
        user, email_id = owned_email
        row = _stored(store, user, email_id)

        assert check_duplicate_attachment(store, calculate_content_hash(SAMPLE), user)["id"] == row["id"]

    def test_check_duplicate_attachment_not_found(self, store, owned_email):
        user, _ = owned_email
        assert check_duplicate_attachment(store, "0" * 64, user) is None

    def test_a_duplicate_is_never_another_users(self, store, owned_email, factory):
        user, email_id = owned_email
        _stored(store, user, email_id)

        assert check_duplicate_attachment(store, calculate_content_hash(SAMPLE), factory.user()) is None


@pytest.mark.integration
class TestAttachmentDeletion:
    def test_delete_attachment(self, store, owned_email, config, factory):
        user, email_id = owned_email
        row = _stored(store, user, email_id)

        assert delete_attachment(store, row["id"], config, user_id=user) is True
        assert factory.row("attachments", row["id"]) is None
        assert not (attachments_dir() / row["storage_path"]).exists()

    def test_delete_nonexistent_attachment(self, store, owned_email, config):
        user, _ = owned_email
        assert delete_attachment(store, "00000000-0000-4000-8000-000000000001", config, user_id=user) is False
