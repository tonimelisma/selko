"""A content type storage will never accept must not ride the retry ladder.

On 2026-10-18 one `text/markdown` attachment was rejected by the bucket's MIME
allowlist. `upload_to_storage` wrapped the `415` in a generic
`AttachmentError`, which `classify_email_error` maps to `unknown` (retryable),
so the row spent all 8 attempts reaching the same answer and landed in
`dead_letter` — one of the four counts `assert-health.sh` calls never
acceptable, which no worker clears. A single unstorable file therefore pinned
/health to degraded indefinitely.

The allowlist is now aligned with the worker's accept-set, so that specific
type stores fine. These tests defend the behaviour that makes the *next* drift
survivable: a refusal is terminal, costs one attempt, and is recorded as
`unsupported` rather than as lost work needing an operator.
"""

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock

import pytest

from selko.services.attachments import (
    AttachmentError,
    AttachmentTypeRejected,
    _is_mime_rejection,
    upload_to_storage,
)
from selko.services.email_ingestion import classify_email_error
from selko.workers.email_ingestion import EmailIngestionWorker


class _StorageError(Exception):
    """Stands in for supabase-py's StorageApiError, which carries a status."""

    def __init__(self, message, status=None):
        super().__init__(message)
        self.status = status


def test_a_mime_refusal_is_recognised_by_status_or_body():
    """Both, because a client may surface only one of them."""
    assert _is_mime_rejection(_StorageError("nope", status=415)) is True
    assert _is_mime_rejection(_StorageError("nope", status="415")) is True
    assert _is_mime_rejection(
        Exception("{'statusCode': 415, 'error': invalid_mime_type, 'message': "
                  "mime type text/markdown is not supported}")
    ) is True


def test_a_transient_storage_failure_stays_retryable():
    """The narrow check is the point.

    Treating a storage outage as permanent would silently drop real
    attachments, which is worse than the dead-letter this replaces.
    """
    assert _is_mime_rejection(_StorageError("service unavailable", status=503)) is False
    assert _is_mime_rejection(_StorageError("gateway timeout", status=504)) is False
    assert _is_mime_rejection(TimeoutError("socket timed out")) is False
    assert _is_mime_rejection(Exception("connection reset by peer")) is False


def test_upload_raises_the_terminal_error_on_a_refusal():
    client = MagicMock()
    client.storage.from_.return_value.upload.side_effect = _StorageError(
        "mime type text/markdown is not supported", status=415
    )

    with pytest.raises(AttachmentTypeRejected):
        upload_to_storage(client, "user-1", "notes.md", b"# hi", "text/markdown")


def test_upload_still_raises_the_retryable_error_otherwise():
    client = MagicMock()
    client.storage.from_.return_value.upload.side_effect = _StorageError(
        "service unavailable", status=503
    )

    with pytest.raises(AttachmentError) as caught:
        upload_to_storage(client, "user-1", "notes.md", b"# hi", "text/markdown")
    assert not isinstance(caught.value, AttachmentTypeRejected)


def test_a_refusal_is_classified_terminal_with_its_own_code():
    """`unknown` is the code for "we have no idea", which this is not."""
    classification = classify_email_error(AttachmentTypeRejected("415"))
    assert classification.code == "attachment_type_rejected"
    assert classification.retryable is False
    assert classification.auth_failure is False


def test_a_refused_attachment_is_marked_unsupported_not_retried(mock_config):
    """The regression. Before this, the row retried to dead_letter."""

    async def scenario():
        worker = EmailIngestionWorker(MagicMock(), mock_config, "worker-1")
        worker.repository.finish_attachment = AsyncMock(return_value=True)

        async def rejected(_attachment):
            raise AttachmentTypeRejected("storage rejected 'text/markdown'")

        worker.acquire_attachment = rejected

        # attempts well below max_attempts: if the row were merely "failed",
        # this is the state that would produce 'retry' and burn the ladder.
        await worker._process_attachment_item(
            {"id": "att-1", "mime_type": "text/markdown", "attempts": 0, "max_attempts": 8}
        )

        worker.repository.finish_attachment.assert_awaited_once()
        args = worker.repository.finish_attachment.await_args.args
        assert args[0] == "att-1"
        assert args[2] == "unsupported", (
            "a type storage will always refuse is unsupported, not retryable"
        )
        assert args[3] == "attachment_type_rejected"

    asyncio.run(scenario())


def test_an_ordinary_failure_still_retries(mock_config):
    """Guard the guard: the change must not make every failure terminal."""

    async def scenario():
        worker = EmailIngestionWorker(MagicMock(), mock_config, "worker-1")
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


def test_the_worker_accept_set_needs_no_subtype_enumeration(mock_config):
    """Why the fix is a wildcard in the bucket, not more entries.

    The gate admits any `text/*` and `image/*` subtype, so there is no finite
    list of subtypes that could match it. This pins that property, which is
    the reason the bucket allowlist carries `text/*` and `image/*`.
    """
    from selko.workers.email_ingestion import SUPPORTED_ATTACHMENT_MIME_PREFIXES

    for exotic in ("text/markdown", "text/x-rst", "image/heic", "image/avif"):
        assert exotic.startswith(SUPPORTED_ATTACHMENT_MIME_PREFIXES), exotic
