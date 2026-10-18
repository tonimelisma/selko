"""Regression tests for the unbounded acquisition executor.

Production stopped claiming ingestion work at 2026-09-29T20:55Z and stayed
stopped for 19 days. The cause was not a failure: `run_acquisition_once`
takes a semaphore permit *before* claiming and releases it in the executor
task's done callback, so a task that never returns never gives the permit
back. Executor width is 2, so two of them ended acquisition for the life of
the process. `_try_acquire` then returned False on every tick, `_claim_loop`
read that as "idle", nothing raised, so `_guarded` logged nothing and every
task kept reporting `alive: true` while 912 claimable rows sat at attempts=0.

The invariant these tests defend: a hung executor costs one row and one
bounded delay, never the work type.
"""

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock

import pytest

from selko.services.email_ingestion import (
    ExecutorTimeoutError,
    classify_email_error,
)
from selko.workers.email_ingestion import EmailIngestionWorker


# The worker clamps the configured bound to a 1s floor, deliberately: a
# sub-second executor timeout would fail every item on a cold cache. So these
# tests wait out the real floor rather than pretending it is not there.
_FLOOR_SECONDS = 1.0
_PAST_THE_BOUND = _FLOOR_SECONDS + 0.4


def _bounded_config(mock_config, **overrides):
    """A config whose executor width is 1 so saturation needs one hung task."""
    return replace(
        mock_config,
        email_acquisition_concurrency=1,
        email_attachment_concurrency=1,
        email_executor_timeout_seconds=_FLOOR_SECONDS,
        **overrides,
    )


def _item(item_id="item-1"):
    return {
        "id": item_id,
        "change_kind": "upsert",
        "integration_id": "integration-1",
        "user_id": "user-1",
        "provider": "outlook",
        "provider_message_id": "msg-1",
        "provider_folder_ids": ["inbox"],
        "attempts": 0,
        "max_attempts": 8,
    }


async def _drain(worker):
    """Cancel anything still in flight so the loop does not outlive the test."""
    for task in list(worker._acquisition_inflight) + list(worker._attachment_inflight):
        task.cancel()
        with pytest.raises((asyncio.CancelledError, Exception)):
            await task


def test_a_hung_acquisition_executor_frees_its_slot(mock_config):
    """The regression. Before the bound, the second claim never came back."""

    async def scenario():
        worker = EmailIngestionWorker(MagicMock(), _bounded_config(mock_config), "worker-1")
        worker.repository.claim_item = AsyncMock(side_effect=[_item("a"), _item("b")])
        worker.repository.fail_item = AsyncMock(return_value=True)

        never_returns = asyncio.Event()

        async def hang(_item):
            await never_returns.wait()

        worker.acquire_item = hang

        # First claim takes the only permit and hands it to a task that hangs.
        assert await worker.run_acquisition_once() is True
        # While it is held the work type is saturated. This much was always
        # true and is correct; what was broken is that it never ended.
        assert await worker.run_acquisition_once() is False

        # Let the bound fire and the done callback run.
        await asyncio.sleep(_PAST_THE_BOUND)

        # The slot is free and the loop claims again. This assertion is the
        # whole point: without the timeout it stays False forever.
        assert await worker.run_acquisition_once() is True

        worker.repository.fail_item.assert_awaited()
        failed_with = worker.repository.fail_item.await_args_list[0].args[2]
        assert isinstance(failed_with, ExecutorTimeoutError)

        await _drain(worker)

    asyncio.run(scenario())


def test_a_timed_out_item_is_failed_not_abandoned(mock_config):
    """A dropped row would stall just as permanently as a held permit.

    fail_item increments attempts and applies the retry ladder, so the item
    comes back. Abandoning it would leave a row that no longer holds a lease
    and no longer makes progress.
    """

    async def scenario():
        worker = EmailIngestionWorker(MagicMock(), _bounded_config(mock_config), "worker-1")
        worker.repository.fail_item = AsyncMock(return_value=True)

        never_returns = asyncio.Event()

        async def hang(_item):
            await never_returns.wait()

        worker.acquire_item = hang

        await worker._process_acquisition_item(_item())

        worker.repository.fail_item.assert_awaited_once()
        args = worker.repository.fail_item.await_args.args
        assert args[0] == "item-1"
        assert args[1] == "worker-1"
        # Retryable, so the row is not dead-lettered on a timeout alone.
        assert classify_email_error(args[2]).retryable is True

    asyncio.run(scenario())


def test_a_hung_attachment_executor_frees_its_slot(mock_config):
    """The attachment executor is the identical twin and stalled the same way."""

    async def scenario():
        worker = EmailIngestionWorker(MagicMock(), _bounded_config(mock_config), "worker-1")
        attachment = {"id": "att-1", "attempts": 0, "max_attempts": 8}
        worker.repository.claim_attachment = AsyncMock(side_effect=[attachment, attachment])
        worker.repository.finish_attachment = AsyncMock(return_value=True)

        never_returns = asyncio.Event()

        async def hang(_attachment):
            await never_returns.wait()

        worker.acquire_attachment = hang

        assert await worker.run_attachment_once() is True
        assert await worker.run_attachment_once() is False
        await asyncio.sleep(_PAST_THE_BOUND)
        assert await worker.run_attachment_once() is True

        worker.repository.finish_attachment.assert_awaited()
        # Retried, not dead-lettered: attempts (0) is below max_attempts.
        assert worker.repository.finish_attachment.await_args_list[0].args[2] == "retry"

        await _drain(worker)

    asyncio.run(scenario())


def test_executor_timeout_has_its_own_error_code():
    """`unknown` is the code for "we have no idea"; a stall is not that.

    The symptom of this failure mode is the *absence* of attempts, so once
    rows start moving again the only trace is the code written on them. It
    needs to be greppable and distinct from every other fallback.
    """
    classification = classify_email_error(ExecutorTimeoutError("timed out"))
    assert classification.code == "executor_timeout"
    assert classification.retryable is True
    assert classification.auth_failure is False


def test_the_bound_stays_below_the_lease(mock_config):
    """fail_item fences on (worker_id, lease). A bound that fires after the
    lease expired records nothing, and the row stalls again -- so the default
    executor timeout must stay under email_lease_seconds."""
    assert mock_config.email_executor_timeout_seconds < mock_config.email_lease_seconds
