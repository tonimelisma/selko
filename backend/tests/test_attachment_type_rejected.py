"""A content type the store will never accept must not ride the retry ladder.

On 2026-10-18 one `text/markdown` attachment was rejected by the Supabase
bucket's MIME allowlist. `upload_to_storage` wrapped the `415` in a generic
`AttachmentError`, which `classify_email_error` maps to `unknown` (retryable),
so the row spent all 8 attempts reaching the same answer and landed in
`dead_letter` — one of the four counts `assert-health.sh` calls never
acceptable, which no worker clears.

Attachments are now files on disk, and the store accepts exactly the worker's
accept-set (one list, `selko.services.attachments`). These tests defend the
behaviour that keeps a refusal survivable: it is terminal, costs one attempt,
and is recorded as `unsupported` rather than as lost work needing an operator.
"""

import asyncio
from unittest.mock import AsyncMock

import pytest

from selko.db.runtime import attachments_dir, use_database
from selko.services.attachments import (
    SUPPORTED_ATTACHMENT_MIME_PREFIXES,
    SUPPORTED_ATTACHMENT_MIMES,
    AttachmentError,
    AttachmentTypeRejected,
    read_attachment_file,
    upload_to_storage,
)
from selko.services.email_ingestion import classify_email_error
from selko.workers.email_ingestion import EmailIngestionWorker


@pytest.fixture
def store(db):
    use_database(db)
    yield db
    use_database(None)


ACCEPTED = sorted(SUPPORTED_ATTACHMENT_MIMES) + ["text/markdown", "text/plain", "image/png", "image/heic"]


@pytest.mark.parametrize("mime", ACCEPTED)
def test_every_type_the_worker_accepts_is_stored(store, mime):
    path = upload_to_storage(store, "user-1", "file.bin", b"payload", mime)
    assert read_attachment_file(path) == b"payload"
    assert (attachments_dir() / path).is_file()


# Validates: SEL-078
@pytest.mark.parametrize("mime", ["application/zip", "application/octet-stream", "video/mp4"])
def test_the_store_refuses_a_type_outside_the_accept_set(store, mime):
    """The matcher itself can fail: a type outside the set is refused, nothing is written."""
    with pytest.raises(AttachmentTypeRejected):
        upload_to_storage(store, "user-1", "archive.zip", b"PK", mime)
    assert not any(p.is_file() for p in attachments_dir().rglob("*"))


# Validates: SEL-079
def test_a_failed_write_stays_retryable(store, monkeypatch):
    """A disk failure is not a property of the type, so it must not be terminal."""
    import selko.services.attachments as attachments

    def broken(_path, _data):
        raise OSError("No space left on device")

    monkeypatch.setattr(attachments, "write_attachment_file", broken)
    with pytest.raises(AttachmentError) as caught:
        upload_to_storage(store, "user-1", "notes.md", b"# hi", "text/markdown")
    assert not isinstance(caught.value, AttachmentTypeRejected)


def test_a_refusal_is_classified_terminal_with_its_own_code():
    """`unknown` is the code for "we have no idea", which this is not."""
    classification = classify_email_error(AttachmentTypeRejected("415"))
    assert classification.code == "attachment_type_rejected"
    assert classification.retryable is False
    assert classification.auth_failure is False


# Validates: SEL-078
def test_a_refused_attachment_is_marked_unsupported_not_retried(db, mock_config):
    """The regression. Before this, the row retried to dead_letter."""

    async def scenario():
        worker = EmailIngestionWorker(db, mock_config, "worker-1", pg_pool=db)
        worker.repository.finish_attachment = AsyncMock(return_value=True)

        async def rejected(_attachment):
            raise AttachmentTypeRejected("storage rejected 'application/zip'")

        worker.acquire_attachment = rejected

        # attempts well below max_attempts: if the row were merely "failed",
        # this is the state that would produce 'retry' and burn the ladder.
        await worker._process_attachment_item(
            {"id": "att-1", "mime_type": "application/zip", "attempts": 0, "max_attempts": 8}
        )

        worker.repository.finish_attachment.assert_awaited_once()
        args = worker.repository.finish_attachment.await_args.args
        assert args[0] == "att-1"
        assert args[2] == "unsupported", (
            "a type the store will always refuse is unsupported, not retryable"
        )
        assert args[3] == "attachment_type_rejected"

    asyncio.run(scenario())


# Validates: SEL-079
def test_an_ordinary_failure_still_retries(db, mock_config):
    """Guard the guard: the change must not make every failure terminal."""

    async def scenario():
        worker = EmailIngestionWorker(db, mock_config, "worker-1", pg_pool=db)
        worker.repository.finish_attachment = AsyncMock(return_value=True)

        async def blew_up(_attachment):
            raise AttachmentError("transient storage failure")

        worker.acquire_attachment = blew_up

        await worker._process_attachment_item(
            {"id": "att-2", "mime_type": "image/png", "attempts": 0, "max_attempts": 8}
        )

        args = worker.repository.finish_attachment.await_args.args
        assert args[2] == "retry"

    asyncio.run(scenario())


# Validates: SEL-078
def test_the_worker_and_the_store_share_one_accept_set():
    """Two allowlists drifted once (the bucket vs the worker); now there is one."""
    from selko.workers import email_ingestion

    assert email_ingestion.SUPPORTED_ATTACHMENT_MIME_PREFIXES is SUPPORTED_ATTACHMENT_MIME_PREFIXES
    assert email_ingestion.SUPPORTED_ATTACHMENT_MIMES is SUPPORTED_ATTACHMENT_MIMES
    for exotic in ("text/markdown", "text/x-rst", "image/heic", "image/avif"):
        assert exotic.startswith(SUPPORTED_ATTACHMENT_MIME_PREFIXES), exotic
