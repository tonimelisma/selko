"""The revival migration's predicate, executed against real Postgres.

`20261019000002` resets attachments stranded in `dead_letter` by the bucket
MIME allowlist gap. A `db reset` proves it parses and applies, but the table is
empty then, so the predicate itself is never exercised — and the predicate is
the whole migration. Applying cleanly to an empty table is not a test.

These tests read the shipped .sql and execute it, so the statement under test
cannot drift from the statement that ships. Each case runs in a transaction
that is always rolled back.
"""

import re
from pathlib import Path
from uuid import UUID, uuid4

import pytest

MIGRATION = (
    Path(__file__).resolve().parents[3]
    / "supabase"
    / "migrations"
    / "20261019000002_revive_mime_rejected_attachment_dead_letters.sql"
)


class _Rollback(Exception):
    pass


def _migration_sql() -> str:
    """The shipped statement, comments stripped."""
    text = MIGRATION.read_text()
    body = "\n".join(
        line for line in text.splitlines() if not line.strip().startswith("--")
    ).strip()
    assert body.upper().startswith("UPDATE PUBLIC.ATTACHMENTS"), body[:80]
    return body


async def _seed(conn, user_id, **overrides) -> UUID:
    email_id = uuid4()
    await conn.execute(
        "INSERT INTO public.emails (id, user_id, provider_message_id, email_provider,"
        " subject, from_email, date_sent, processing_status)"
        " VALUES ($1, $2, $3, 'outlook', 'revival probe', 'probe@example.test',"
        " '1900-01-01T00:00:00Z', 'processed')",
        email_id, user_id, f"revive-{email_id.hex}",
    )
    attachment_id = uuid4()
    fields = {
        "id": attachment_id,
        "user_id": user_id,
        "email_id": email_id,
        "filename": "farewell-slack-dms.md",
        "mime_type": "text/markdown",
        "ingestion_status": "dead_letter",
        "attempts": 8,
        "max_attempts": 8,
        "ingestion_error_code": "unknown",
    }
    fields.update(overrides)
    columns = ", ".join(fields)
    placeholders = ", ".join(f"${i}" for i in range(1, len(fields) + 1))
    await conn.execute(
        f"INSERT INTO public.attachments ({columns}) VALUES ({placeholders})",
        *fields.values(),
    )
    return attachment_id


async def _state(conn, attachment_id) -> dict:
    row = await conn.fetchrow(
        "SELECT ingestion_status, attempts, ingestion_error_code, locked_by,"
        " locked_until, next_retry_at FROM public.attachments WHERE id = $1",
        attachment_id,
    )
    return dict(row)


async def _run(pg_pool, user_id, body):
    async with pg_pool.acquire() as conn:
        try:
            async with conn.transaction():
                await body(conn, UUID(str(user_id)))
                raise _Rollback
        except _Rollback:
            pass


@pytest.mark.integration
@pytest.mark.development
class TestReviveMimeRejectedDeadLetters:
    async def test_it_revives_the_row_production_is_holding(self, pg_pool, temp_user):
        """text/markdown, 8/8, 'unknown' — the exact production row."""

        async def body(conn, user_id):
            attachment_id = await _seed(conn, user_id)

            await conn.execute(_migration_sql())

            after = await _state(conn, attachment_id)
            assert after["ingestion_status"] == "pending"
            assert after["attempts"] == 0, "must be claimable again"
            assert after["ingestion_error_code"] is None
            assert after["locked_by"] is None
            assert after["locked_until"] is None
            assert after["next_retry_at"] is None

        await _run(pg_pool, temp_user[0], body)

    async def test_it_leaves_a_differently_failed_row_alone(self, pg_pool, temp_user):
        """A typed error code means a cause this migration does not fix.

        Reviving it would walk it straight back to dead_letter and the gauge
        would return — the failure mode 20260901000001 had to undo elsewhere.
        """

        async def body(conn, user_id):
            typed = await _seed(conn, user_id, ingestion_error_code="provider_permanent")

            await conn.execute(_migration_sql())

            after = await _state(conn, typed)
            assert after["ingestion_status"] == "dead_letter"
            assert after["attempts"] == 8

        await _run(pg_pool, temp_user[0], body)

    async def test_it_leaves_a_type_the_bucket_still_rejects_alone(self, pg_pool, temp_user):
        """Only types the corrected allowlist admits are worth re-attempting."""

        async def body(conn, user_id):
            still_rejected = await _seed(
                conn, user_id,
                filename="movie.mkv",
                mime_type="video/x-matroska",
            )

            await conn.execute(_migration_sql())

            after = await _state(conn, still_rejected)
            assert after["ingestion_status"] == "dead_letter", (
                "video/* is in neither allowlist; reviving it would just loop"
            )

        await _run(pg_pool, temp_user[0], body)

    async def test_it_leaves_the_live_retry_cohort_alone(self, pg_pool, temp_user):
        """attempts below the limit means the ladder is still working."""

        async def body(conn, user_id):
            retrying = await _seed(
                conn, user_id, ingestion_status="retry", attempts=2,
            )

            await conn.execute(_migration_sql())

            after = await _state(conn, retrying)
            assert after["ingestion_status"] == "retry"
            assert after["attempts"] == 2

        await _run(pg_pool, temp_user[0], body)

    async def test_it_is_idempotent(self, pg_pool, temp_user):
        """A second run must match nothing, not reset a now-pending row."""

        async def body(conn, user_id):
            attachment_id = await _seed(conn, user_id)
            sql = _migration_sql()

            await conn.execute(sql)
            await conn.execute(
                "UPDATE public.attachments SET attempts = 3 WHERE id = $1", attachment_id
            )
            await conn.execute(sql)

            after = await _state(conn, attachment_id)
            assert after["attempts"] == 3, "second run must not touch a revived row"

        await _run(pg_pool, temp_user[0], body)
