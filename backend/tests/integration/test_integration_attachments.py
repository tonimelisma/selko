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
from selko.services.attachments import read_attachment_file, upload_to_storage


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




@pytest.mark.integration
class TestAttachmentStorage:
    # Validates: SEL-081
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

