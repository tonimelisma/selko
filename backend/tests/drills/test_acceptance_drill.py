"""The ten-step staging acceptance drill.

The drill composes existing real-Postgres invariant tests instead of creating
an unreviewed second implementation of their SQL. Each entry has a stable
name for evidence manifests and runs only with the staging and drill markers.
"""

import os

import pytest

from tests.integration.test_integration_calendar_work_items import (
    test_enqueue_claim_complete_is_item_fenced as _test_enqueue_claim_complete_is_item_fenced,
    test_new_enqueue_supersedes_old_and_stale_completion_is_fenced as _test_new_enqueue_supersedes_old_and_stale_completion_is_fenced,
    test_unsync_is_worker_owned_and_clears_remote_identity_on_completion as _test_unsync_is_worker_owned_and_clears_remote_identity_on_completion,
)
from tests.integration.test_integration_email_ingestion_v2 import (
    test_discovery_page_write_records_run_counters as _test_discovery_page_write_records_run_counters,
)
from tests.integration.test_integration_email_state_machine import (
    TestDurableEmailStateMachine as _DurableEmailStateMachine,
    TestDurableSyncRunGeneration as _DurableSyncRunGeneration,
)
from tests.integration.test_integration_event_change_proposals import (
    test_new_proposal_supersedes_only_the_previous_pending_proposal as _test_new_proposal_supersedes_only_the_previous_pending_proposal,
    test_proposal_is_authoritative_and_apply_reject_reopen_are_atomic as _test_proposal_is_authoritative_and_apply_reject_reopen_are_atomic,
)
from tests.integration.test_integration_fenced_event_commit import (
    test_stale_generation_cannot_write as _test_stale_generation_cannot_write,
    test_two_emails_same_day_produce_one_event as _test_two_emails_same_day_produce_one_event,
    test_zombie_generation_after_reclaim_writes_nothing as _test_zombie_generation_after_reclaim_writes_nothing,
)


pytestmark = [pytest.mark.integration, pytest.mark.staging, pytest.mark.drill]
if os.getenv("RUN_ACCEPTANCE_DRILL") != "1":
    pytestmark.append(
        pytest.mark.skip(reason="staging acceptance drill requires explicit opt-in")
    )


@pytest.mark.asyncio
async def test_01_lease_expiry_reclaims_without_restart(pg_pool, temp_user):
    await _test_zombie_generation_after_reclaim_writes_nothing(pg_pool, temp_user)


@pytest.mark.asyncio
async def test_02_old_generation_completion_is_fenced(pg_pool, temp_user):
    await _test_stale_generation_cannot_write(pg_pool, temp_user)


@pytest.mark.asyncio
async def test_03_concurrent_same_day_updates_have_one_event(pg_pool, temp_user):
    await _test_two_emails_same_day_produce_one_event(pg_pool, temp_user)


@pytest.mark.asyncio
async def test_04_newer_proposal_supersedes_the_previous_one(admin_client, temp_user):
    await _test_new_proposal_supersedes_only_the_previous_pending_proposal(
        admin_client, temp_user
    )


@pytest.mark.asyncio
async def test_05_apply_queues_worker_owned_calendar_work(
    admin_client, temp_user, pg_pool
):
    await _test_proposal_is_authoritative_and_apply_reject_reopen_are_atomic(
        admin_client, temp_user
    )
    await _test_enqueue_claim_complete_is_item_fenced(
        admin_client, temp_user, pg_pool
    )


@pytest.mark.asyncio
async def test_06_undo_compensation_remains_worker_owned(
    admin_client, temp_user, pg_pool
):
    await _test_unsync_is_worker_owned_and_clears_remote_identity_on_completion(
        admin_client, temp_user, pg_pool
    )


@pytest.mark.asyncio
async def test_07_stale_calendar_completion_cannot_overwrite_newer_work(
    admin_client, temp_user, pg_pool
):
    await _test_new_enqueue_supersedes_old_and_stale_completion_is_fenced(
        admin_client, temp_user, pg_pool
    )


def test_08_crashed_discovery_run_is_reclaimed(admin_client, synced_integration):
    _test_discovery_page_write_records_run_counters(admin_client, synced_integration)


def test_09_faulted_work_degrades_health(admin_client, temp_user):
    _DurableEmailStateMachine().test_health_degrades_on_unclaimable_or_stale_work(
        admin_client, temp_user
    )


def test_10_stale_provider_run_generation_is_fenced(admin_client, synced_integration):
    _DurableSyncRunGeneration().test_stale_sync_generation_cannot_complete_new_run(
        admin_client, synced_integration
    )
