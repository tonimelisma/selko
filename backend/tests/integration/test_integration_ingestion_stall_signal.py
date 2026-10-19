"""Real-Postgres coverage for the ingestion stall health signal.

`health_work_state` grew `items_stalled_seconds` because nothing in it could
see a stalled acquisition executor. Production sat on 912 claimable
`email_ingestion_items` rows for 19 days with `status: ok`: `items_pending`
counted the backlog but never degraded the rollup, `items_dead_letter` was 0
because nothing ever failed, and `unclaimable_pending` is about `emails`.

A migration that applies cleanly has not been tested. These tests execute the
function against a real database, which is the only thing that can prove the
predicate matches `claim_email_ingestion_item`'s -- if it drifts, this signal
measures a different queue than the one the worker drains.

Each scenario runs on a clean slate inside a transaction that is always rolled
back: the rollup is database-wide, so rows another test left behind would
otherwise decide the result.
"""

from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest


class _Rollback(Exception):
    """Sentinel that unwinds the scenario transaction."""


def _iso(delta_seconds: int = 0) -> datetime:
    return datetime.now(timezone.utc) + timedelta(seconds=delta_seconds)


async def _health(conn, warning_seconds: int = 3600) -> dict:
    row = await conn.fetchrow(
        "SELECT * FROM public.health_work_state($1)", warning_seconds
    )
    assert row is not None, "health_work_state must return one row"
    return dict(row)


def _uuid(value) -> UUID:
    """asyncpg is strict about uuid parameters; temp_user hands back a str."""
    return value if isinstance(value, UUID) else UUID(str(value))


async def _integration(conn, user_id) -> object:
    integration_id = uuid4()
    await conn.execute(
        "INSERT INTO public.integrations (id, user_id, provider, status, access_token)"
        " VALUES ($1, $2, 'gmail', 'active', 'stall-signal-token')",
        integration_id, _uuid(user_id),
    )
    return integration_id


async def _item(conn, integration_id, user_id, **overrides) -> object:
    """One ingestion item. Defaults are a never-attempted claimable row."""
    item_id = uuid4()
    fields = {
        "id": item_id,
        "integration_id": _uuid(integration_id),
        "user_id": _uuid(user_id),
        "provider": "gmail",
        "provider_message_id": f"stall-{item_id.hex}",
        "acquisition_status": "pending",
        "attempts": 0,
        "max_attempts": 8,
        "created_at": _iso(),
        "next_retry_at": None,
        "lease_expires_at": None,
        "lease_owner": None,
    }
    fields.update(overrides)
    columns = ", ".join(fields)
    placeholders = ", ".join(f"${i}" for i in range(1, len(fields) + 1))
    await conn.execute(
        f"INSERT INTO public.email_ingestion_items ({columns}) VALUES ({placeholders})",
        *fields.values(),
    )
    return item_id


async def _quiesce_other_degradations(conn) -> None:
    """Silence every degrade source in health_work_state except the stall.

    The roll-up is a claim about the whole database, so without this a test
    asserting `degraded` can pass on someone else's dead letter. Each
    statement below corresponds to one branch of the function's status CASE.
    Only ever called inside a transaction that is rolled back.
    """
    await conn.execute(
        "UPDATE public.emails SET processing_status = 'processed'"
        " WHERE processing_status = 'processing'"
        "   AND (locked_until IS NULL OR locked_until < now())"
    )
    await conn.execute(
        "UPDATE public.emails SET attempts = 0"
        " WHERE processing_status = 'pending' AND attempts >= max_attempts"
    )
    await conn.execute(
        "UPDATE public.email_sync_runs SET status = 'completed' WHERE status = 'running'"
    )
    await conn.execute(
        "UPDATE public.attachments SET ingestion_status = 'stored'"
        " WHERE ingestion_status = 'dead_letter'"
    )
    await conn.execute(
        "UPDATE public.operational_incidents SET status = 'resolved' WHERE status = 'open'"
    )


async def _scenario(pg_pool, user_id, body):
    """Run `body` against an empty email_ingestion_items, then roll back."""
    async with pg_pool.acquire() as conn:
        try:
            async with conn.transaction():
                await conn.execute("DELETE FROM public.email_ingestion_items")
                integration_id = await _integration(conn, user_id)
                await body(conn, integration_id)
                raise _Rollback
        except _Rollback:
            pass


@pytest.mark.integration
@pytest.mark.development
class TestIngestionStallHealthSignal:
    async def test_a_frozen_backlog_degrades_the_rollup(self, pg_pool, temp_user):
        """The assertion that would have caught the outage on day one."""
        user_id = temp_user[0]

        async def body(conn, integration_id):
            await _item(conn, integration_id, user_id, created_at=_iso(-19 * 86400))

            health = await _health(conn, warning_seconds=3600)

            assert health["items_pending"] == 1
            # The old gauge: depth, with nothing to say about progress.
            assert health["items_dead_letter"] == 0
            # The new one: 19 days of claimable work that nothing is claiming.
            assert health["items_stalled_seconds"] >= 19 * 86400 - 60

            # Attribution. A bare `status == "degraded"` passes even when
            # something else entirely is degrading the roll-up, making it a
            # check that cannot fail for the reason it claims to test. So
            # quiesce every other degrade source first (all inside this
            # rolled-back transaction), then the threshold differential
            # isolates this signal: the only difference between the two calls
            # below is whether the stall exceeds p_warning_seconds.
            await _quiesce_other_degradations(conn)

            without_this_signal = await _health(conn, warning_seconds=10**9)
            assert without_this_signal["status"] == "ok", (
                f"other degrade sources were not quiesced: {without_this_signal}"
            )

            with_this_signal = await _health(conn, warning_seconds=3600)
            assert with_this_signal["status"] == "degraded", (
                "a 19-day frozen backlog must degrade the roll-up, and nothing "
                "else here can"
            )

        await _scenario(pg_pool, user_id, body)

    async def test_an_in_flight_lease_means_draining_not_stalled(self, pg_pool, temp_user):
        """A large backlog is not a stalled one.

        "Oldest claimable row is older than N" is red during any bulk
        backfill, and a signal that cries wolf is ignored exactly as fast as
        one that cannot fire. An unexpired lease proves the executor is alive,
        so the age is not counted.
        """
        user_id = temp_user[0]

        async def body(conn, integration_id):
            await _item(conn, integration_id, user_id, created_at=_iso(-19 * 86400))
            await _item(
                conn, integration_id, user_id,
                acquisition_status="processing",
                attempts=1,
                lease_owner="worker-1",
                lease_expires_at=_iso(900),
            )

            health = await _health(conn, warning_seconds=3600)

            assert health["items_pending"] == 2
            assert health["items_stalled_seconds"] == 0, (
                "an acquisition in flight means the queue is draining"
            )

        await _scenario(pg_pool, user_id, body)

    async def test_it_returns_to_green_when_the_backlog_drains(self, pg_pool, temp_user):
        """A gauge that cannot read zero is ignored as fast as one that cannot
        go red -- this codebase has shipped both (see 20260901000001). No
        claimable work means NULL, with no operator action."""
        user_id = temp_user[0]

        async def body(conn, integration_id):
            item_id = await _item(
                conn, integration_id, user_id, created_at=_iso(-19 * 86400)
            )
            assert (await _health(conn))["items_stalled_seconds"] is not None

            await conn.execute(
                "UPDATE public.email_ingestion_items"
                " SET acquisition_status = 'completed', completed_at = now()"
                " WHERE id = $1",
                item_id,
            )

            health = await _health(conn, warning_seconds=3600)
            assert health["items_stalled_seconds"] is None
            assert health["items_pending"] == 0
            # Deliberately NOT `status == "ok"`. The roll-up is a claim about
            # the whole database -- any other row anywhere that dead-letters
            # or goes stale makes it degrade -- so asserting it here made this
            # test depend on the random ordering seed. It passed when written
            # and failed as soon as a neighbouring test left a dead-lettered
            # attachment behind. test_integration_api.py::test_health_check
            # documents the identical trap and resolves it the same way.
            #
            # The property this test exists for is that the signal I added
            # clears itself: NULL once no claimable work remains, with no
            # operator action. That is asserted above and is scoped to the
            # rows this scenario controls.

        await _scenario(pg_pool, user_id, body)

    async def test_a_row_serving_its_retry_backoff_is_not_stalled(self, pg_pool, temp_user):
        """`next_retry_at` in the future means the row is deliberately waiting.

        The predicate has to mirror claim_email_ingestion_item exactly, which
        excludes these rows -- counting them would report a stall every time
        an item took a normal retry.
        """
        user_id = temp_user[0]

        async def body(conn, integration_id):
            await _item(
                conn, integration_id, user_id,
                acquisition_status="retry",
                attempts=1,
                created_at=_iso(-19 * 86400),
                next_retry_at=_iso(600),
            )

            health = await _health(conn, warning_seconds=3600)

            assert health["items_pending"] == 1, "still counted as depth"
            assert health["items_stalled_seconds"] is None, (
                "a row inside its backoff window is not claimable, so not stalled"
            )

        await _scenario(pg_pool, user_id, body)

    async def test_an_exhausted_row_is_not_counted_as_stalled(self, pg_pool, temp_user):
        """attempts >= max_attempts is unclaimable by construction.

        Counting it would pin the signal red forever, which is exactly the
        defect 20260901000001 had to undo for `unclaimable_emails`.
        """
        user_id = temp_user[0]

        async def body(conn, integration_id):
            await _item(
                conn, integration_id, user_id,
                acquisition_status="pending",
                attempts=8,
                max_attempts=8,
                created_at=_iso(-19 * 86400),
            )

            health = await _health(conn, warning_seconds=3600)
            assert health["items_stalled_seconds"] is None

        await _scenario(pg_pool, user_id, body)
