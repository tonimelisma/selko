"""Integration tests for attachment service.

Tests attachment storage and retrieval with real Supabase.
"""

from uuid import uuid4

import pytest

from selko.services.attachments import (
    calculate_content_hash,
    check_duplicate_attachment,
    save_attachment_metadata,
    upload_to_storage,
    delete_attachment,
    process_attachment,
    AttachmentError,
)
from selko.services.emails import parse_gmail_message, save_emails
from selko.services.gmail import (
    get_credentials,
    build_service,
    fetch_messages,
    extract_attachments,
)


@pytest.fixture
def test_email(authenticated_client, test_user_id, cleanup_emails):
    """Create a test email for attachment tests."""
    gmail_id = f"test_att_email_{uuid4().hex[:8]}"
    cleanup_emails.append(gmail_id)

    email_data = {
        "gmail_id": gmail_id,
        "thread_id": f"thread_{uuid4().hex[:8]}",
        "subject": "Test email with attachments",
        "from_email": "sender@example.com",
        "gmail_label_ids": ["INBOX"],
        "date_sent": "2026-01-22T10:00:00+00:00",
        "user_id": test_user_id,
    }

    result = authenticated_client.table("emails").insert(email_data).execute()
    return result.data[0]


@pytest.fixture
def cleanup_attachments(authenticated_client, test_user_id, config):
    """Delete test attachments after test completes."""
    created_attachment_ids = []

    yield created_attachment_ids

    # Cleanup
    for att_id in created_attachment_ids:
        try:
            delete_attachment(authenticated_client, att_id, config)
        except Exception:
            pass


@pytest.fixture
def sample_attachment_data():
    """Sample attachment bytes for testing."""
    return b"This is sample attachment content for testing purposes."


@pytest.mark.integration
@pytest.mark.development
class TestAttachmentStorage:
    """Test attachment storage with real Supabase."""

    def test_upload_to_storage(
        self, authenticated_client, test_user_id, sample_attachment_data, config
    ):
        """Can upload file to Supabase Storage."""
        storage_path = upload_to_storage(
            client=authenticated_client,
            user_id=test_user_id,
            filename="test_upload.txt",
            data=sample_attachment_data,
            mime_type="text/plain",
            bucket=config.storage_bucket_attachments,
        )

        assert storage_path is not None
        assert test_user_id in storage_path
        assert "test_upload.txt" in storage_path

        # Cleanup: delete the uploaded file
        try:
            authenticated_client.storage.from_(
                config.storage_bucket_attachments
            ).remove([storage_path])
        except Exception:
            pass

    def test_upload_with_special_filename(
        self, authenticated_client, test_user_id, sample_attachment_data, config
    ):
        """Upload handles special characters in filename."""
        storage_path = upload_to_storage(
            client=authenticated_client,
            user_id=test_user_id,
            filename="file with spaces & (special).txt",
            data=sample_attachment_data,
            mime_type="text/plain",
            bucket=config.storage_bucket_attachments,
        )

        assert storage_path is not None

        # Cleanup
        try:
            authenticated_client.storage.from_(
                config.storage_bucket_attachments
            ).remove([storage_path])
        except Exception:
            pass


@pytest.mark.integration
@pytest.mark.development
class TestAttachmentMetadata:
    """Test attachment metadata storage."""

    def test_save_attachment_metadata(
        self, authenticated_client, test_user_id, test_email, cleanup_attachments
    ):
        """Can save attachment metadata to database."""
        content_hash = calculate_content_hash(b"test content")

        record = save_attachment_metadata(
            client=authenticated_client,
            email_id=test_email["id"],
            gmail_attachment_id="gmail_att_123",
            filename="test_document.pdf",
            mime_type="application/pdf",
            size_bytes=1024,
            storage_path=f"{test_user_id}/test_doc.pdf",
            content_hash=content_hash,
        )

        cleanup_attachments.append(record["id"])

        assert record is not None
        assert record["filename"] == "test_document.pdf"
        assert record["mime_type"] == "application/pdf"
        assert record["size_bytes"] == 1024
        assert record["content_hash"] == content_hash
        assert record["user_id"] == test_user_id

    def test_check_duplicate_attachment_found(
        self, authenticated_client, test_user_id, test_email, cleanup_attachments
    ):
        """Duplicate detection finds existing attachment by hash."""
        test_content = b"unique content for duplicate test"
        content_hash = calculate_content_hash(test_content)

        # Create first attachment
        record1 = save_attachment_metadata(
            client=authenticated_client,
            email_id=test_email["id"],
            gmail_attachment_id="gmail_att_dup1",
            filename="original.pdf",
            mime_type="application/pdf",
            size_bytes=len(test_content),
            storage_path=f"{test_user_id}/original.pdf",
            content_hash=content_hash,
        )
        cleanup_attachments.append(record1["id"])

        # Check for duplicate
        existing = check_duplicate_attachment(authenticated_client, content_hash)

        assert existing is not None
        assert existing["id"] == record1["id"]
        assert existing["filename"] == "original.pdf"

    def test_check_duplicate_attachment_not_found(self, authenticated_client):
        """Duplicate detection returns None for new hash."""
        unique_hash = calculate_content_hash(b"completely unique content " + uuid4().bytes)

        existing = check_duplicate_attachment(authenticated_client, unique_hash)

        assert existing is None


@pytest.mark.integration
@pytest.mark.development
class TestAttachmentDeletion:
    """Test attachment deletion."""

    def test_delete_attachment(
        self, authenticated_client, test_user_id, test_email, config
    ):
        """Can delete attachment from database."""
        # Create attachment metadata (no actual file)
        content_hash = calculate_content_hash(b"delete test")
        record = save_attachment_metadata(
            client=authenticated_client,
            email_id=test_email["id"],
            gmail_attachment_id="gmail_att_del",
            filename="to_delete.pdf",
            mime_type="application/pdf",
            size_bytes=100,
            storage_path=None,  # No actual file
            content_hash=content_hash,
        )

        # Delete
        result = delete_attachment(authenticated_client, record["id"], config)

        assert result is True

        # Verify deleted
        check = (
            authenticated_client.table("attachments")
            .select("id")
            .eq("id", record["id"])
            .execute()
        )
        assert len(check.data) == 0

    def test_delete_nonexistent_attachment(self, authenticated_client, config):
        """Deleting nonexistent attachment returns False."""
        fake_id = str(uuid4())

        result = delete_attachment(authenticated_client, fake_id, config)

        assert result is False


@pytest.mark.integration
@pytest.mark.development
class TestAttachmentRLS:
    """Test RLS policies for attachments."""

    def test_user_sees_only_own_attachments(
        self, authenticated_client, test_user_id, test_email, cleanup_attachments
    ):
        """RLS ensures user only sees their own attachments."""
        # Create attachment as current user
        content_hash = calculate_content_hash(b"rls test content")
        record = save_attachment_metadata(
            client=authenticated_client,
            email_id=test_email["id"],
            gmail_attachment_id="gmail_att_rls",
            filename="my_file.pdf",
            mime_type="application/pdf",
            size_bytes=100,
            storage_path=f"{test_user_id}/my_file.pdf",
            content_hash=content_hash,
        )
        cleanup_attachments.append(record["id"])

        # Query should return only this user's attachments
        result = (
            authenticated_client.table("attachments")
            .select("*")
            .eq("id", record["id"])
            .execute()
        )

        assert len(result.data) == 1
        assert result.data[0]["user_id"] == test_user_id


@pytest.mark.integration
@pytest.mark.staging
class TestAttachmentStorageStaging:
    """Test attachment storage in staging environment."""

    def test_upload_and_retrieve_staging(
        self, authenticated_client, test_user_id, sample_attachment_data, config
    ):
        """Can upload and retrieve file in staging."""
        storage_path = upload_to_storage(
            client=authenticated_client,
            user_id=test_user_id,
            filename="staging_test.txt",
            data=sample_attachment_data,
            mime_type="text/plain",
            bucket=config.storage_bucket_attachments,
        )

        assert storage_path is not None

        # Verify file can be downloaded
        result = authenticated_client.storage.from_(
            config.storage_bucket_attachments
        ).download(storage_path)

        assert result == sample_attachment_data

        # Cleanup
        authenticated_client.storage.from_(
            config.storage_bucket_attachments
        ).remove([storage_path])


@pytest.mark.integration
@pytest.mark.staging
class TestGmailAttachmentStaging:
    """Test Gmail attachment download with real Gmail API."""

    def test_gmail_attachment_full_pipeline(
        self, authenticated_client, config
    ):
        """Complete pipeline: Gmail fetch → download → storage → metadata."""
        # 1. Get Gmail credentials
        creds = get_credentials(authenticated_client, config)
        if creds is None:
            pytest.fail("No Gmail credentials - run cli_auth_gmail first")

        # 2. Build service and fetch emails with attachments
        service = build_service(creds)
        messages = fetch_messages(service, max_results=20)

        # 3. Find an email with attachments
        email_with_attachment = None
        attachment_part = None
        for msg in messages:
            attachments = extract_attachments(msg)
            if attachments:
                email_with_attachment = msg
                attachment_part = attachments[0]
                break

        if not email_with_attachment:
            pytest.fail("No emails with attachments found in staging Gmail")

        # 4. Save email to DB first (required for attachment FK)
        parsed = parse_gmail_message(email_with_attachment)
        saved_emails = save_emails(authenticated_client, [parsed])
        email_record = saved_emails[0]

        # 5. Process attachment (download → upload → save metadata)
        result = process_attachment(
            client=authenticated_client,
            gmail_service=service,
            email_id=email_record["id"],
            message_id=email_with_attachment["id"],
            attachment_part=attachment_part,
            config=config,
        )

        # 6. Verify result
        assert result is not None
        assert result["filename"] == attachment_part["filename"]
        assert result["storage_path"] is not None
        assert result["content_hash"] is not None

        # 7. Verify file exists in storage
        downloaded = authenticated_client.storage.from_(
            config.storage_bucket_attachments
        ).download(result["storage_path"])
        assert len(downloaded) > 0
