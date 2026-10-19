"""The worker's accept-set and the bucket's allowlist are one contract.

Two independently-maintained allowlists decide whether an attachment can be
stored: what `acquire_attachment` will try to upload, and what the
`attachments` bucket will accept. Any type in the first and not the second is
a guaranteed failure — `415 invalid_mime_type`, wrapped in a generic
`AttachmentError`, classified `unknown`, retried 8 times, then `dead_letter`,
which `assert-health.sh` calls never acceptable and which no worker clears.

They have drifted twice. `20260728000001` added the three types production had
hit by then; on 2026-10-18 a `text/markdown` attachment hit the gap again and
pinned /health to degraded. Comparing the sets at that point also found
`application/rtf`, which the worker accepted and the bucket did not, and which
nobody had happened to receive yet.

Enumerating subtypes cannot close this — `image/*` and `text/*` are unbounded.
These tests read both sets and assert the containment directly, so a change to
either one fails here instead of in production.
"""

import uuid

import pytest

from selko.services.attachments import AttachmentTypeRejected, upload_to_storage
from selko.workers.email_ingestion import (
    SUPPORTED_ATTACHMENT_MIME_PREFIXES,
    SUPPORTED_ATTACHMENT_MIMES,
)


async def _bucket_allowlist(pg_pool) -> list[str]:
    async with pg_pool.acquire() as conn:
        row = await conn.fetchrow(
            "SELECT allowed_mime_types FROM storage.buckets WHERE id = 'attachments'"
        )
    assert row is not None, "the attachments bucket must exist"
    return list(row["allowed_mime_types"] or [])


def _permits(allowlist: list[str], mime: str) -> bool:
    """Does `allowlist` admit `mime`, exactly or by wildcard?

    Mirrors how Supabase Storage matches: an entry `type/*` admits every
    subtype of `type`.
    """
    for entry in allowlist:
        if entry == mime:
            return True
        if entry.endswith("/*") and mime.startswith(entry[:-1]):
            return True
    return False


@pytest.mark.integration
@pytest.mark.development
class TestAttachmentMimeContract:
    async def test_every_prefix_the_worker_accepts_has_a_bucket_wildcard(self, pg_pool):
        """An unbounded prefix can only be covered by a wildcard.

        The worker accepts all of `image/*` and `text/*`. No finite list of
        subtypes can match that, so the bucket must carry the wildcards --
        otherwise the next unlisted subtype dead-letters, which is what
        text/markdown did.
        """
        allowlist = await _bucket_allowlist(pg_pool)

        missing = [
            f"{prefix}*"
            for prefix in SUPPORTED_ATTACHMENT_MIME_PREFIXES
            if f"{prefix}*" not in allowlist
        ]
        assert not missing, (
            f"the worker uploads all of {SUPPORTED_ATTACHMENT_MIME_PREFIXES} but the "
            f"attachments bucket is missing {missing}; any subtype outside the "
            f"enumerated entries would be rejected with 415 and dead-letter. "
            f"Bucket allows: {sorted(allowlist)}"
        )

    async def test_every_explicit_type_the_worker_accepts_is_permitted(self, pg_pool):
        """`application/rtf` was in the worker's set and not the bucket's."""
        allowlist = await _bucket_allowlist(pg_pool)

        missing = sorted(
            mime for mime in SUPPORTED_ATTACHMENT_MIMES if not _permits(allowlist, mime)
        )
        assert not missing, (
            f"acquire_attachment will download and upload {missing}, which the "
            f"attachments bucket rejects. Add them to the bucket allowlist or "
            f"remove them from SUPPORTED_ATTACHMENT_MIMES — the two sets are one "
            f"contract. Bucket allows: {sorted(allowlist)}"
        )

    async def test_the_matcher_itself_can_fail(self, pg_pool):
        """Guard the guard: a wildcard must not admit a foreign top type.

        Without this, `_permits` returning True unconditionally would make both
        assertions above vacuous.
        """
        assert _permits(["text/*"], "text/markdown") is True
        assert _permits(["text/*"], "image/png") is False
        assert _permits(["application/pdf"], "application/pdf") is True
        assert _permits(["application/pdf"], "application/rtf") is False
        assert _permits([], "text/plain") is False

    def test_the_type_that_dead_lettered_production_now_uploads(self, config, temp_user):
        """The 2026-10-18 failure, executed rather than reasoned about.

        With the old allowlist this raised
        `415 invalid_mime_type "mime type text/markdown is not supported"`.
        """
        from selko.services.auth import get_service_client

        client = get_service_client(config)
        path = upload_to_storage(
            client=client,
            user_id=temp_user[0],
            filename=f"contract-{uuid.uuid4().hex}.md",
            data=b"# contract probe\n",
            mime_type="text/markdown",
            bucket=config.storage_bucket_attachments,
        )
        assert path
        client.storage.from_(config.storage_bucket_attachments).remove([path])

    def test_a_rejected_type_raises_the_terminal_error(self, config, temp_user):
        """A type outside the allowlist must surface as AttachmentTypeRejected.

        `application/x-shockwave-flash` is deliberately absent from the bucket
        and from the worker's accept-set, so it stands in for a future drift.
        It must come back typed, not as a generic retryable AttachmentError —
        that distinction is what keeps the row out of dead_letter.
        """
        from selko.services.auth import get_service_client

        client = get_service_client(config)
        with pytest.raises(AttachmentTypeRejected):
            upload_to_storage(
                client=client,
                user_id=temp_user[0],
                filename=f"contract-{uuid.uuid4().hex}.swf",
                data=b"not really flash",
                mime_type="application/x-shockwave-flash",
                bucket=config.storage_bucket_attachments,
            )
