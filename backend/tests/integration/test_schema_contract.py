"""Executable contracts for the live public database schema."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import ast
import asyncpg
import json
from pathlib import Path
import re
from typing import Any
from uuid import UUID, uuid4

import pytest


pytestmark = [pytest.mark.integration, pytest.mark.development]


@dataclass(frozen=True)
class ContractContext:
    user_id: UUID
    gmail_integration_id: UUID
    outlook_integration_id: UUID
    calendar_integration_id: UUID
    email_id: UUID
    event_id: UUID
    attachment_id: UUID
    ingestion_item_id: UUID
    sync_run_id: UUID
    recovery_id: UUID
    folder_id: UUID


# Trigger-only functions are exercised by test_live_triggers_for_every_table.
TRIGGER_ONLY_FUNCTIONS = {
    "calendar_work_item_owner_check",
    "enforce_event_change_proposal_invariant",
    "ensure_email_sync_state",
    "handle_new_user",
    "notify_work_available",
    "reset_skipped_emails_for_sender_rule",
    "trg_emails_broadcast",
    "trg_event_sources_broadcast",
    "trg_event_change_proposals_broadcast",
    "trg_calendar_work_items_broadcast",
    "trg_events_broadcast",
    "trg_integrations_broadcast",
}


# The only SECURITY DEFINER functions a signed-in user may execute. Each entry
# records why exposing it is safe: the function must derive the acting user from
# auth.uid(), or reject a p_user_id that does not match it. Everything else in
# public is worker coordination and belongs to service_role alone.
#
# anon is absent by design. This product has no unauthenticated RPC.
AUTHENTICATED_EXECUTABLE_FUNCTIONS: dict[str, str] = {
    "reprocess_email": "raises unless auth.uid() = p_user_id or caller is service_role",
    "request_email_sync_now": "returns false unless the integration belongs to auth.uid()",
    "set_email_folder_preference": "updates only rows whose user_id = auth.uid()",
    "set_event_review_status": "raises unless auth.uid() = p_user_id or caller is service_role",
}


# Every enumerated CHECK domain in public is pinned here. Adding a value is a
# one-line edit, while removing one requires checking every writer first.
EXPECTED_CHECK_DOMAINS: dict[tuple[str, str], set[str]] = {
    ("action_history", "action_type"): {"create", "update", "delete"},
    ("action_history", "entity_type"): {"event", "sender_rule"},
    ("attachments", "ingestion_status"): {
        "pending", "processing", "stored", "unsupported", "retry", "dead_letter",
    },
    # I2: distinguishes entries Selko wrote (they carry our private
    # extendedProperty) from ones the user created or accepted elsewhere.
    ("calendar_entries", "origin"): {"selko_created", "external"},
    ("calendar_work_items", "action"): {"upsert", "cancel"},
    ("calendar_work_items", "status"): {
        "pending", "processing", "succeeded", "failed", "blocked", "superseded",
    },
    ("calendar_sync_log", "action"): {"created", "updated", "deleted"},
    ("email_folders", "classification_decision"): {"include", "exclude", "uncertain"},
    ("email_folders", "folder_kind"): {"label", "folder"},
    ("email_folders", "provider"): {"gmail", "outlook"},
    ("email_ingestion_items", "acquisition_status"): {
        "pending", "processing", "completed", "retry", "dead_letter", "removed",
    },
    ("email_ingestion_items", "change_kind"): {"upsert", "membership_change", "removed"},
    ("email_ingestion_items", "provider"): {"gmail", "outlook"},
    ("email_sync_runs", "provider"): {"gmail", "outlook"},
    ("email_sync_runs", "run_kind"): {
        "initial", "incremental", "daily_reconcile", "weekly_reconcile", "manual_repair",
    },
    ("email_sync_runs", "status"): {"running", "completed", "failed", "abandoned"},
    ("email_sync_state", "provider"): {"gmail", "outlook"},
    ("emails", "processing_outcome"): {
        "no_event", "event_matched", "event_created", "event_updated",
        "event_created_and_updated", "event_cancelled", "calendar_invite",
        "cancellation_unmatched", "cancellation_ambiguous",
    },
    ("emails", "processing_status"): {"pending", "processing", "processed", "failed", "skipped"},
    ("event_sources", "source_origin"): {"email", "google_calendar", "google_photos"},
    ("event_sources", "source_type"): {"new_invitation", "update", "cancellation", "reminder", "unknown"},
    ("event_change_proposals", "kind"): {"material_update", "cancellation"},
    ("event_change_proposals", "status"): {"pending", "applied", "rejected", "superseded", "closed_legacy"},
    ("event_identity_hints", "kind"): {"ical_uid", "provider_thread", "join_url", "management_url"},
    ("event_identity_hints", "strength"): {"authoritative", "supporting"},
    ("event_repair_audit", "action"): {"merge_duplicate_group", "merge_source", "cancel_event", "resolve_proposal"},
    ("events", "review_status"): {"pending_review", "active", "rejected", "cancelled"},
    ("events", "importance"): {"action_required", "fyi"},
    ("graph_api_failures", "graph_surface"): {"outlook_mail", "onedrive"},
    ("integration_recoveries", "reason"): {"initial_connection", "reauthorization"},
    ("integration_recoveries", "status"): {
        "pending", "processing", "waiting", "completed", "completed_with_errors",
        "failed", "superseded",
    },
    ("operational_incidents", "severity"): {"warning", "critical"},
    ("operational_incidents", "status"): {"open", "resolved"},
    ("photos", "processing_status"): {"pending", "processing", "processed", "failed", "skipped"},
    ("scheduled_tasks", "status"): {"pending", "processing", "completed", "failed"},
    ("scheduled_tasks", "task_type"): {"photo_fetch", "email_fetch"},
    ("sender_rules", "action"): {"auto_approve", "ignore"},
    ("user_calendar_settings", "all_day_display_mode"): {
        "all_day", "day_9_to_5", "morning_8_to_9", "custom",
    },
}


def _status_literals_in_write(node: ast.AST) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []

    def inspect_mapping(mapping: ast.Dict) -> None:
        for key, value in zip(mapping.keys, mapping.values):
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                continue
            if key.value not in {"processing_status", "status", "acquisition_status", "ingestion_status", "sync_status"}:
                continue
            if isinstance(value, ast.Constant) and isinstance(value.value, str):
                found.append((key.value, value.value))

    for child in ast.walk(node):
        if not isinstance(child, ast.Call) or not isinstance(child.func, ast.Attribute):
            continue
        if child.func.attr in {"insert", "update", "upsert"}:
            for argument in child.args:
                if isinstance(argument, ast.Dict):
                    inspect_mapping(argument)
        elif child.func.attr == "eq" and len(child.args) >= 2:
            key, value = child.args[:2]
            if (
                isinstance(key, ast.Constant)
                and isinstance(key.value, str)
                and key.value in {"processing_status", "status", "acquisition_status", "ingestion_status", "sync_status"}
                and isinstance(value, ast.Constant)
                and isinstance(value.value, str)
            ):
                found.append((key.value, value.value))
    return found


async def _seed_context(conn) -> ContractContext:
    user_id = uuid4()
    gmail_id = uuid4()
    outlook_id = uuid4()
    calendar_id = uuid4()
    email_id = uuid4()
    event_id = uuid4()
    attachment_id = uuid4()
    ingestion_item_id = uuid4()
    sync_run_id = uuid4()
    recovery_id = uuid4()
    folder_id = uuid4()

    await conn.execute("SELECT set_config('request.jwt.claim.sub', $1, true)", str(user_id))
    await conn.execute("SELECT set_config('request.jwt.claim.role', 'service_role', true)")
    email = f"schema-contract-{user_id}@example.com"
    await conn.execute(
        """
        INSERT INTO auth.users
            (id, aud, role, email, email_confirmed_at, raw_app_meta_data,
             raw_user_meta_data, created_at, updated_at)
        VALUES ($1, 'authenticated', 'authenticated', $2, now(), '{}'::jsonb,
                '{}'::jsonb, now(), now())
        """,
        user_id,
        email,
    )
    await conn.execute(
        """
        INSERT INTO public.users (id, email)
        VALUES ($1, $2)
        ON CONFLICT (id) DO NOTHING
        """,
        user_id,
        email,
    )
    for integration_id, provider in (
        (gmail_id, "gmail"),
        (outlook_id, "outlook"),
        (calendar_id, "google_calendar"),
    ):
        await conn.execute(
            """
            INSERT INTO public.integrations
                (id, user_id, provider, access_token, provider_email)
            VALUES ($1, $2, $3::integration_provider, 'contract-token', $4)
            """,
            integration_id,
            user_id,
            provider,
            f"{provider}@schema-contract.example.com",
        )
    await conn.execute(
        """
        INSERT INTO public.email_folders
            (id, user_id, integration_id, provider, provider_folder_id,
             name, full_path, folder_kind)
        VALUES ($1, $2, $3, 'gmail', 'INBOX', 'Inbox', 'Inbox', 'label')
        """,
        folder_id,
        user_id,
        gmail_id,
    )
    await conn.execute(
        """
        INSERT INTO public.emails
            (id, user_id, integration_id, provider_message_id,
             email_provider, subject, from_email, provider_labels,
             email_folder_id, processing_status)
        VALUES ($1, $2, $3, 'schema-contract-email', 'gmail',
                'contract email', 'sender@example.com', ARRAY['INBOX'], $4,
                'processed')
        """,
        email_id,
        user_id,
        gmail_id,
        folder_id,
    )
    await conn.execute(
        "INSERT INTO public.events (id, user_id, title, review_status) VALUES ($1, $2, 'schema contract event', 'pending_review')",
        event_id,
        user_id,
    )
    await conn.execute(
        """
        INSERT INTO public.attachments
            (id, user_id, email_id, provider_attachment_id, filename,
             mime_type, size_bytes, ingestion_status, locked_by,
             locked_until)
        VALUES ($1, $2, $3, 'schema-contract-attachment', 'contract.txt',
                'text/plain', 1, 'processing', 'schema-contract-worker',
                now() + interval '1 minute')
        """,
        attachment_id,
        user_id,
        email_id,
    )
    await conn.execute(
        """
        INSERT INTO public.email_sync_runs
            (id, integration_id, user_id, provider, run_kind, status)
        VALUES ($1, $2, $3, 'gmail', 'initial', 'running')
        """,
        sync_run_id,
        gmail_id,
        user_id,
    )
    await conn.execute(
        """
        INSERT INTO public.email_ingestion_items
            (id, integration_id, user_id, provider, provider_message_id)
        VALUES ($1, $2, $3, 'gmail', 'schema-contract-item')
        """,
        ingestion_item_id,
        gmail_id,
        user_id,
    )
    await conn.execute(
        """
        INSERT INTO public.integration_recoveries
            (id, integration_id, user_id, provider, reason)
        VALUES ($1, $2, $3, 'google_calendar', 'initial_connection')
        """,
        recovery_id,
        calendar_id,
        user_id,
    )
    return ContractContext(
        user_id,
        gmail_id,
        outlook_id,
        calendar_id,
        email_id,
        event_id,
        attachment_id,
        ingestion_item_id,
        sync_run_id,
        recovery_id,
        folder_id,
    )


@pytest.fixture
async def contract_connection(pg_pool):
    async with pg_pool.acquire() as conn:
        transaction = conn.transaction()
        await transaction.start()
        try:
            context = await _seed_context(conn)
            yield conn, context
        finally:
            await transaction.rollback()


def _function_arguments(context: ContractContext) -> dict[str, tuple[Any, ...]]:
    worker = "schema-contract-worker"
    now = datetime.now(timezone.utc)
    return {
        "_enqueue_calendar_work": (
            context.event_id, context.user_id, "upsert",
            {"title": "schema contract event"}, None, False,
        ),
        "apply_event_change_proposal": (
            context.event_id,
            context.user_id,
            context.attachment_id,
            None,
            "applied contract event",
            now,
            now + timedelta(hours=1),
            False,
            "contract location",
            "contract description",
            "action_required",
            "active",
            "upsert",
        ),
        "broadcast_user_ui_change": (context.user_id, "events", "updated", context.event_id),
        "check_and_increment_quota": (context.user_id, "llm_calls", 1),
        "claim_due_email_reconciliation": (worker, 60),
        "claim_due_email_sync": (worker, 60),
        "claim_email_attachment": (worker, 60),
        "claim_email_ingestion_item": (worker, 60),
        "claim_integration_recovery": (worker, 60),
        "claim_pending_photo": (worker, 60),
        "claim_unprocessed_email": (worker, 60),
        "commit_email_extraction": (context.email_id, worker, 1, [], "processed"),
        "complete_email_ingestion_item": (context.ingestion_item_id, worker, context.email_id),
        "complete_email_sync": (context.gmail_integration_id, context.sync_run_id, worker, 1, 60, False),
        "complete_integration_reauthorization": (
            context.user_id,
            "google_calendar",
            "schema-contract-access-token",
            "schema-contract-refresh-token",
            now + timedelta(hours=1),
            ["calendar.readonly"],
            "schema-contract@example.com",
        ),
        "fail_email_ingestion_item": (context.ingestion_item_id, worker, "schema_contract", 5, 60, False),
        "fail_email_processing": (context.email_id, worker, 1, "schema_contract", "probe", 5, 60),
        "fail_email_sync": (context.gmail_integration_id, context.sync_run_id, worker, 1, "schema_contract", "probe", 5, 60, False),
        "finish_email_attachment": (context.attachment_id, worker, "stored", "schema_contract"),
        "get_llm_usage_summary": (context.user_id, date.today() - timedelta(days=1), date.today()),
        "get_user_quota_usage": (context.user_id, date.today()),
        "health_work_state": (60,),
        "heartbeat_email_sync": (context.gmail_integration_id, worker, 1, 60),
        "reconcile_outlook_email_folders": (context.outlook_integration_id, []),
        "refresh_waiting_calendar_recoveries": (10,),
        "reprocess_email": (context.user_id, context.email_id),
        "reject_event_change_proposal": (
            context.event_id,
            context.user_id,
            context.attachment_id,
            None,
            False,
            "rejected contract event",
            now,
            now + timedelta(hours=1),
            False,
            "contract location",
            "contract description",
            "action_required",
            "user_rejected",
        ),
        "reopen_event_change_proposal": (
            context.event_id,
            context.user_id,
            context.attachment_id,
            None,
            None,
            None,
            None,
            False,
        ),
        "request_email_sync_now": (context.gmail_integration_id,),
        "requeue_calendar_recovery_batch": (context.recovery_id, worker, 10, 1),
        "undo_event_and_enqueue_calendar_work": (
            context.event_id, context.user_id, None, None, None, False,
        ),
        "unsync_event_and_enqueue_calendar_work": (
            context.event_id, context.user_id, None, False,
        ),
        "queue_event_cancellation": (context.event_id, context.user_id),
        "save_email_with_attachment_descriptors": (
            context.user_id,
            {
                "email_provider": "gmail",
                "provider_message_id": f"schema-contract-{context.email_id}",
                "subject": "schema contract probe",
                "from_email": "schema-contract@example.com",
                "provider_labels": ["INBOX"],
                "body_text": "contract probe",
            },
            [{
                "provider_attachment_id": f"schema-contract-{context.attachment_id}",
                "filename": "contract.txt",
                "mime_type": "text/plain",
                "size_bytes": 1,
            }],
        ),
        "set_event_review_status": (context.event_id, "active", context.user_id),
        "claim_calendar_work": ("schema-contract-worker", 60),
        "claim_calendar_work_item": ("schema-contract-worker", 60),
        "complete_calendar_work": (context.event_id, worker, 1, "schema-contract-google", None),
        "defer_calendar_work": (context.event_id, worker, 1, now + timedelta(minutes=5), "probe"),
        "enqueue_calendar_work": (
            context.event_id, context.user_id, "upsert", {"title": "schema contract event"}, None, False,
        ),
        "fail_calendar_work": (context.event_id, worker, 1, "schema_contract", "probe", True),
        "heartbeat_calendar_work": (context.event_id, worker, 1, 60),
        "set_email_folder_preference": (context.folder_id, True),
        "unlock_expired_integration_recoveries": (),
        "unlock_expired_event_locks": (),
        "unlock_expired_photo_locks": (),
        "upsert_discovered_email_items": (
            context.gmail_integration_id,
            context.sync_run_id,
            [{"provider_message_id": f"schema-contract-item-{context.email_id}", "provider_folder_ids": [], "change_kind": "upsert"}],
            "schema-contract-cursor",
            None,
        ),
    }


@pytest.mark.asyncio
async def test_every_security_definer_function_has_a_contract(contract_connection):
    conn, context = contract_connection
    contracts = _function_arguments(context)
    rows = await conn.fetch(
        """
        SELECT p.proname AS name
        FROM pg_proc AS p
        JOIN pg_namespace AS n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public' AND p.prosecdef
        ORDER BY p.proname
        """
    )
    actual_names = {row["name"] for row in rows}
    assert actual_names == set(contracts) | TRIGGER_ONLY_FUNCTIONS, (
        f"missing={sorted(actual_names - set(contracts) - TRIGGER_ONLY_FUNCTIONS)}, "
        f"stale={sorted(set(contracts) | TRIGGER_ONLY_FUNCTIONS - actual_names)}"
    )

    worker = "schema-contract-worker"
    for name, args in contracts.items():
        call_args = list(args)
        if name in {
            "apply_event_change_proposal",
            "reject_event_change_proposal",
            "reopen_event_change_proposal",
        }:
            await conn.execute(
                """
                INSERT INTO public.event_sources
                    (id, event_id, email_id, source_type, extracted_data)
                VALUES ($1, $2, $3, 'update', '{}'::jsonb)
                ON CONFLICT (id) DO NOTHING
                """,
                context.attachment_id,
                context.event_id,
                context.email_id,
            )
            await conn.execute(
                """
                INSERT INTO public.event_change_proposals
                    (id, event_id, user_id, source_id, kind, status, change_set, event_snapshot_before)
                VALUES ($1, $2, $3, $4, 'material_update', 'pending',
                        '{"kind":"material_update","changes":[{"field":"title","before":"before","after":"after"}]}'::jsonb,
                        '{"status":"approved","title":"before"}'::jsonb)
                ON CONFLICT (id) DO NOTHING
                """,
                context.attachment_id,
                context.event_id,
                context.user_id,
                context.attachment_id,
            )
        if name == "unsync_event_and_enqueue_calendar_work":
            await conn.execute(
                """
                UPDATE public.events
                SET review_status = 'active', google_calendar_event_id = 'contract-google-event'
                WHERE id = $1
                """,
                context.event_id,
            )
            await conn.execute(
                """
                INSERT INTO public.calendar_work_items
                    (event_id, user_id, action, generation, status, provider_event_id)
                VALUES ($1, $2, 'upsert', 99, 'succeeded', 'contract-google-event')
                """,
                context.event_id,
                context.user_id,
            )
        if name == "reopen_event_change_proposal":
            await conn.execute("UPDATE public.events SET review_status = 'active' WHERE id = $1", context.event_id)
            await conn.execute(
                "UPDATE public.event_change_proposals SET status = 'applied', resolution_reason = 'contract' WHERE source_id = $1",
                context.attachment_id,
            )
        elif name in {"apply_event_change_proposal", "reject_event_change_proposal"}:
            await conn.execute("UPDATE public.events SET review_status = 'active' WHERE id = $1", context.event_id)
            await conn.execute(
                "UPDATE public.event_change_proposals SET status = 'pending', resolution_reason = NULL WHERE source_id = $1",
                context.attachment_id,
            )
        if name in {"requeue_calendar_recovery_batch", "refresh_waiting_calendar_recoveries"}:
            # Earlier calls in this same loop (claim_integration_recovery,
            # complete_integration_reauthorization) leave their own recovery
            # rows behind, and integration_recoveries_one_active_idx allows one
            # active row per integration. Terminate the others and re-lease the
            # fixture row, so the call under test is both legal and meaningful:
            # without the lease requeue returns -1 and asserts nothing.
            await conn.execute(
                """
                UPDATE public.integration_recoveries
                SET status = 'completed', locked_by = NULL, locked_until = NULL
                WHERE integration_id = $1 AND id <> $2
                  AND status IN ('pending', 'processing', 'waiting')
                """,
                context.calendar_integration_id, context.recovery_id,
            )
            await conn.execute(
                """
                UPDATE public.integration_recoveries
                SET status = 'processing', locked_by = $2,
                    locked_until = now() + interval '5 minutes'
                WHERE id = $1
                """,
                context.recovery_id, worker,
            )
        if name in {
            "heartbeat_calendar_work",
            "complete_calendar_work",
            "defer_calendar_work",
            "fail_calendar_work",
        }:
            work_item = await conn.fetchrow(
                "SELECT id, generation FROM public.calendar_work_items WHERE event_id = $1 ORDER BY generation DESC LIMIT 1",
                context.event_id,
            )
            assert work_item is not None, f"no calendar work item for {name} contract"
            await conn.execute(
                """
                UPDATE public.calendar_work_items
                SET status = 'processing', locked_by = $2, locked_until = now() + interval '5 minutes', attempts = greatest(attempts, 1)
                WHERE id = $1
                """,
                work_item["id"], worker,
            )
            call_args[0] = work_item["id"]
            call_args[1] = worker
            call_args[2] = work_item["generation"]
        if name in {"apply_event_change_proposal", "reject_event_change_proposal", "reopen_event_change_proposal"}:
            call_args[2] = await conn.fetchval(
                "SELECT id FROM public.event_change_proposals WHERE source_id = $1",
                context.attachment_id,
            )
        encoded_args = [
            json.dumps(value)
            if isinstance(value, (dict, list))
                and name in {
                    "_enqueue_calendar_work",
                    "commit_email_extraction",
                    "enqueue_calendar_work",
                    "save_email_with_attachment_descriptors",
                    "undo_event_and_enqueue_calendar_work",
                    "unsync_event_and_enqueue_calendar_work",
                    "upsert_discovered_email_items",
                }
            else value
            for value in call_args
        ]
        placeholders = ", ".join(f"${index}" for index in range(1, len(call_args) + 1))
        try:
            await conn.fetch(f"SELECT * FROM public.{name}({placeholders})", *encoded_args)
        except Exception as exc:
            pytest.fail(f"{name}({args!r}) is not callable: {exc}")


@pytest.mark.asyncio
async def test_event_delivery_state_has_no_legacy_status_column(contract_connection):
    conn, _ = contract_connection
    assert await conn.fetchval(
        """
        SELECT NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'events' AND column_name = 'status'
        )
        """
    ) is True


@pytest.mark.asyncio
async def test_every_public_table_has_rls_enabled(pg_pool):
    rows = await pg_pool.fetch(
        """
        SELECT c.relname AS table_name, c.relrowsecurity AS rls_enabled
        FROM pg_class AS c
        JOIN pg_namespace AS n ON n.oid = c.relnamespace
        WHERE n.nspname = 'public' AND c.relkind = 'r'
        ORDER BY c.relname
        """
    )
    deliberate_exceptions: set[str] = set()
    failures = [row["table_name"] for row in rows if not row["rls_enabled"]]
    assert not failures, f"public tables without RLS: {failures}"
    assert not deliberate_exceptions


@pytest.mark.asyncio
async def test_security_definer_functions_are_not_executable_by_api_roles(pg_pool):
    """The roles PostgREST authenticates as may execute only the contract set.

    The predecessor of this test asserted ``has_function_privilege('public',
    ...)``. ``public`` is the pseudo-role. Supabase installs ``ALTER DEFAULT
    PRIVILEGES IN SCHEMA public GRANT EXECUTE ON FUNCTIONS TO anon,
    authenticated``, so every function is granted to those roles *directly* and
    a revoke aimed at the pseudo-role changes nothing. The old assertion passed
    in every environment while 56 SECURITY DEFINER functions -- including
    ``commit_email_extraction`` and ``claim_unprocessed_email`` -- were callable
    with the published anon key.
    """
    rows = await pg_pool.fetch(
        """
        SELECT p.proname AS name,
               pg_get_function_identity_arguments(p.oid) AS identity_arguments,
               has_function_privilege('anon', p.oid, 'EXECUTE') AS anon_executes,
               has_function_privilege('authenticated', p.oid, 'EXECUTE')
                   AS authenticated_executes
        FROM pg_proc AS p
        JOIN pg_namespace AS n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public' AND p.prosecdef
        ORDER BY p.proname, identity_arguments
        """
    )
    assert rows, "no SECURITY DEFINER functions found; the query is wrong"

    anon_executable = [
        f"{row['name']}({row['identity_arguments']})"
        for row in rows
        if row["anon_executes"]
    ]
    assert not anon_executable, (
        "anon may execute SECURITY DEFINER functions; there is no unauthenticated "
        f"RPC in this product: {anon_executable}"
    )

    authenticated_executable = {
        row["name"] for row in rows if row["authenticated_executes"]
    }
    expected = set(AUTHENTICATED_EXECUTABLE_FUNCTIONS)
    assert authenticated_executable == expected, (
        f"unexpected={sorted(authenticated_executable - expected)}, "
        f"missing={sorted(expected - authenticated_executable)}"
    )


@pytest.mark.asyncio
async def test_default_function_privileges_do_not_grant_api_roles(pg_pool):
    """Close the hole at the source, not one function at a time.

    Revoking each function individually is a treadmill: the next migration that
    does ``DROP FUNCTION`` + ``CREATE`` silently re-grants from the default ACL.
    This asserts the default itself is closed, so a new function is private on
    creation.
    """
    rows = await pg_pool.fetch(
        """
        SELECT defaclrole::regrole::text AS grantor, defaclacl::text AS acl
        FROM pg_default_acl AS d
        WHERE d.defaclobjtype = 'f'
          AND d.defaclnamespace = 'public'::regnamespace
          -- Only grantors that actually own SECURITY DEFINER functions here can
          -- reopen the hole; supabase_admin's default applies to objects it
          -- creates in its own schemas and is not ours to alter.
          AND EXISTS (
              SELECT 1
              FROM pg_proc AS p
              JOIN pg_namespace AS n ON n.oid = p.pronamespace
              WHERE n.nspname = 'public' AND p.prosecdef AND p.proowner = d.defaclrole
          )
        """
    )
    offenders = [
        f"{row['grantor']}: {row['acl']}"
        for row in rows
        if "anon=" in (row["acl"] or "") or "authenticated=" in (row["acl"] or "")
    ]
    assert not offenders, (
        f"default privileges still grant EXECUTE to the API roles: {offenders}"
    )


@pytest.mark.asyncio
async def test_live_triggers_for_every_triggered_table(contract_connection):
    conn, context = contract_connection
    rows = await conn.fetch(
        """
        SELECT DISTINCT event_object_table AS table_name
        FROM information_schema.triggers
        WHERE trigger_schema = 'public'
        ORDER BY table_name
        """
    )
    fixtures = {
        "attachments": _exercise_attachment_triggers,
        "calendar_work_items": _exercise_calendar_work_item_triggers,
        "email_ingestion_items": _exercise_ingestion_item_triggers,
        "emails": _exercise_email_triggers,
        "event_change_proposals": _exercise_event_change_proposal_triggers,
        "event_sources": _exercise_event_source_triggers,
        "events": _exercise_event_triggers,
        "global_limits": _exercise_global_limit_triggers,
        "integrations": _exercise_integration_triggers,
        "sender_rules": _exercise_sender_rule_triggers,
        "usage_quotas": _exercise_usage_quota_triggers,
        "user_calendar_settings": _exercise_calendar_settings_triggers,
        "users": _exercise_user_triggers,
    }
    actual_tables = {row["table_name"] for row in rows}
    assert actual_tables == set(fixtures), (
        f"missing={sorted(actual_tables - set(fixtures))}, "
        f"stale={sorted(set(fixtures) - actual_tables)}"
    )
    for table_name in sorted(actual_tables):
        await fixtures[table_name](conn, context)


async def _exercise_calendar_work_item_triggers(conn, context):
    item_id = uuid4()
    await conn.execute(
        """
        INSERT INTO public.calendar_work_items
            (id, event_id, user_id, action, generation, desired_event)
        VALUES ($1, $2, $3, 'upsert', 1, '{"title":"trigger probe"}'::jsonb)
        """,
        item_id, context.event_id, context.user_id,
    )
    await conn.execute(
        "UPDATE public.calendar_work_items SET failure_detail = 'trigger probe' WHERE id = $1",
        item_id,
    )


async def _exercise_attachment_triggers(conn, context):
    row_id = uuid4()
    await conn.execute(
        "INSERT INTO public.attachments (id, user_id, email_id, provider_attachment_id, filename) VALUES ($1, $2, $3, $4, 'trigger.txt')",
        row_id, context.user_id, context.email_id, str(row_id),
    )
    await conn.execute("UPDATE public.attachments SET attempts = attempts + 1 WHERE id = $1", row_id)


async def _exercise_ingestion_item_triggers(conn, context):
    row_id = uuid4()
    await conn.execute(
        "INSERT INTO public.email_ingestion_items (id, integration_id, user_id, provider, provider_message_id) VALUES ($1, $2, $3, 'gmail', $4)",
        row_id, context.gmail_integration_id, context.user_id, str(row_id),
    )
    await conn.execute("UPDATE public.email_ingestion_items SET acquisition_status = 'processing' WHERE id = $1", row_id)


async def _exercise_email_triggers(conn, context):
    row_id = uuid4()
    await conn.execute(
        "INSERT INTO public.emails (id, user_id, integration_id, provider_message_id, email_provider, provider_labels) VALUES ($1, $2, $3, $4, 'gmail', ARRAY['INBOX'])",
        row_id, context.user_id, context.gmail_integration_id, str(row_id),
    )
    await conn.execute("UPDATE public.emails SET provider_labels = ARRAY['STARRED'] WHERE id = $1", row_id)


async def _exercise_event_source_triggers(conn, context):
    row_id = uuid4()
    trigger_email_id = uuid4()
    await conn.execute(
        """
        INSERT INTO public.emails
            (id, user_id, integration_id, provider_message_id, email_provider, provider_labels, processing_status)
        VALUES ($1, $2, $3, $4, 'gmail', ARRAY['INBOX'], 'processed')
        """,
        trigger_email_id, context.user_id, context.gmail_integration_id, str(trigger_email_id),
    )
    await conn.execute(
        "INSERT INTO public.event_sources (id, event_id, email_id, extracted_data) VALUES ($1, $2, $3, '{}'::jsonb)",
        row_id, context.event_id, trigger_email_id,
    )
    await conn.execute("UPDATE public.event_sources SET extracted_data = '{\"updated\": true}'::jsonb WHERE id = $1", row_id)


async def _exercise_event_change_proposal_triggers(conn, context):
    source_id = uuid4()
    await conn.execute(
        """
        INSERT INTO public.event_sources
            (id, event_id, email_id, source_type, extracted_data)
        VALUES ($1, $2, $3, 'update', '{}'::jsonb)
        """,
        source_id, context.event_id, context.email_id,
    )
    proposal_id = await conn.fetchval(
        """
        INSERT INTO public.event_change_proposals
            (event_id, user_id, source_id, kind, status, change_set, event_snapshot_before)
        VALUES ($1, $2, $3, 'material_update', 'pending',
                '{"kind":"material_update","changes":[{"field":"title","before":"trigger before","after":"trigger after"}]}'::jsonb,
                '{"status":"approved","title":"trigger before"}'::jsonb)
        RETURNING id
        """,
        context.event_id, context.user_id, source_id,
    )
    await conn.execute(
        "UPDATE public.event_change_proposals SET status = 'closed_legacy', resolution_reason = 'trigger probe' WHERE id = $1",
        proposal_id,
    )


async def _exercise_event_triggers(conn, context):
    row_id = uuid4()
    await conn.execute(
        "INSERT INTO public.events (id, user_id, title, review_status) VALUES ($1, $2, 'trigger event', 'pending_review')",
        row_id, context.user_id,
    )
    await conn.execute("UPDATE public.events SET title = 'updated trigger event', review_status = 'rejected' WHERE id = $1", row_id)
    await conn.execute("DELETE FROM public.events WHERE id = $1", row_id)


async def _exercise_global_limit_triggers(conn, _context):
    limit_type = f"schema_contract_{uuid4().hex}"
    await conn.execute("INSERT INTO public.global_limits (limit_type, default_limit, max_allowed) VALUES ($1, 1, 2)", limit_type)
    await conn.execute("UPDATE public.global_limits SET default_limit = 2 WHERE limit_type = $1", limit_type)


async def _exercise_integration_triggers(conn, context):
    row_id = uuid4()
    await conn.execute(
        "INSERT INTO public.integrations (id, user_id, provider, access_token) VALUES ($1, $2, 'google_photos', 'trigger-token')",
        row_id, context.user_id,
    )
    await conn.execute("UPDATE public.integrations SET access_token = 'updated-trigger-token' WHERE id = $1", row_id)


async def _exercise_sender_rule_triggers(conn, context):
    row_id = uuid4()
    await conn.execute(
        "INSERT INTO public.sender_rules (id, user_id, sender_email, action) VALUES ($1, $2, 'trigger@example.com', 'ignore')",
        row_id, context.user_id,
    )
    await conn.execute("UPDATE public.sender_rules SET action = 'auto_approve' WHERE id = $1", row_id)
    await conn.execute("DELETE FROM public.sender_rules WHERE id = $1", row_id)


async def _exercise_usage_quota_triggers(conn, context):
    await conn.execute("INSERT INTO public.usage_quotas (user_id) VALUES ($1)", context.user_id)
    await conn.execute("UPDATE public.usage_quotas SET llm_calls_count = 1 WHERE user_id = $1", context.user_id)


async def _exercise_calendar_settings_triggers(conn, context):
    await conn.execute("INSERT INTO public.user_calendar_settings (user_id) VALUES ($1)", context.user_id)
    await conn.execute("UPDATE public.user_calendar_settings SET timezone = 'UTC' WHERE user_id = $1", context.user_id)


async def _exercise_user_triggers(conn, context):
    await conn.execute("UPDATE public.users SET display_name = 'updated trigger user' WHERE id = $1", context.user_id)


@pytest.mark.asyncio
async def test_pending_proposal_requires_active_review_status(contract_connection):
    conn, context = contract_connection
    source_id = uuid4()
    await conn.execute(
        """
        INSERT INTO public.event_sources
            (id, event_id, email_id, source_type, extracted_data)
        VALUES ($1, $2, $3, 'update', '{}'::jsonb)
        """,
        source_id,
        context.event_id,
        context.email_id,
    )
    await conn.execute(
        """
        INSERT INTO public.event_change_proposals
            (event_id, user_id, source_id, kind, status, change_set, event_snapshot_before)
        VALUES ($1, $2, $3, 'material_update', 'pending',
                '{"kind":"material_update","changes":[]}'::jsonb,
                '{"status":"approved","title":"before"}'::jsonb)
        """,
        context.event_id, context.user_id, source_id,
    )
    with pytest.raises(asyncpg.CheckViolationError, match="must have active review status"):
        await conn.execute("SET CONSTRAINTS ALL IMMEDIATE")


@pytest.mark.asyncio
async def test_reject_event_change_proposal_is_one_atomic_transition(contract_connection):
    conn, context = contract_connection
    source_id = uuid4()
    await conn.execute(
        """
        INSERT INTO public.event_sources (id, event_id, email_id, source_type, extracted_data)
        VALUES ($1, $2, $3, 'update', '{}'::jsonb)
        """,
        source_id, context.event_id, context.email_id,
    )
    await conn.execute(
        """
        INSERT INTO public.event_change_proposals
            (event_id, user_id, source_id, kind, status, change_set, event_snapshot_before)
        VALUES ($1, $2, $3, 'material_update', 'pending',
                '{"kind":"material_update","changes":[]}'::jsonb,
                '{"status":"approved","title":"before"}'::jsonb)
        """,
        context.event_id, context.user_id, source_id,
    )
    await conn.execute("UPDATE public.events SET review_status = 'active' WHERE id = $1", context.event_id)

    result = await conn.fetchval(
        """
        SELECT public.reject_event_change_proposal(
            $1, $2, $3, NULL, false, 'before', NULL, NULL,
            false, NULL, NULL, 'action_required', 'user_rejected'
        )
        """,
        context.event_id, context.user_id, await conn.fetchval(
            "SELECT id FROM public.event_change_proposals WHERE source_id = $1", source_id
        ),
    )
    await conn.execute("SET CONSTRAINTS ALL IMMEDIATE")

    if isinstance(result, str):
        result = json.loads(result)
    assert result["status"] == "active"
    assert await conn.fetchval(
        "SELECT status FROM public.event_change_proposals WHERE source_id = $1",
        source_id,
    ) == "rejected"
    assert await conn.fetchval(
        "SELECT review_status FROM public.events WHERE id = $1",
        context.event_id,
    ) == "active"


@pytest.mark.asyncio
async def test_check_constraint_domains_are_pinned(pg_pool):
    rows = await pg_pool.fetch(
        """
        SELECT rel.relname AS table_name,
               att.attname AS column_name,
               pg_get_constraintdef(con.oid) AS definition
        FROM pg_constraint con
        JOIN pg_class rel ON rel.oid = con.conrelid
        JOIN pg_namespace nsp ON nsp.oid = rel.relnamespace
        JOIN unnest(con.conkey) AS k(attnum) ON true
        JOIN pg_attribute att ON att.attrelid = rel.oid AND att.attnum = k.attnum
        WHERE nsp.nspname = 'public'
          AND con.contype = 'c'
          AND pg_get_constraintdef(con.oid) LIKE '%ANY (ARRAY[%'
        ORDER BY 1, 2
        """
    )
    actual = {
        (row["table_name"], row["column_name"]): set(re.findall(r"'([^']*)'::text", row["definition"]))
        for row in rows
    }
    assert set(actual) == set(EXPECTED_CHECK_DOMAINS), (
        f"missing={sorted(set(EXPECTED_CHECK_DOMAINS) - set(actual))}, "
        f"unexpected={sorted(set(actual) - set(EXPECTED_CHECK_DOMAINS))}"
    )
    assert actual == EXPECTED_CHECK_DOMAINS


@pytest.mark.asyncio
async def test_status_literals_in_python_are_permitted():
    allowed_by_column: dict[str, set[str]] = {}
    for (_, column), values in EXPECTED_CHECK_DOMAINS.items():
        allowed_by_column.setdefault(column, set()).update(values)
    # integrations.status is a PostgreSQL enum rather than a CHECK domain.
    allowed_by_column["status"].update({"active", "expired", "revoked", "error"})

    backend_root = Path(__file__).resolve().parents[2]
    writers: list[tuple[Path, str, str]] = []
    for source_path in sorted((backend_root / "selko").rglob("*.py")):
        tree = ast.parse(source_path.read_text(), filename=str(source_path))
        for key, value in _status_literals_in_write(tree):
            writers.append((source_path, key, value))

    violations = [
        f"{path}:{key}={value!r}"
        for path, key, value in writers
        if value not in allowed_by_column.get(key, set())
    ]
    assert not violations, "status literals are outside their pinned domains: " + ", ".join(violations)


# Every column a web client asks PostgREST for is part of the schema contract,
# and it is the half no other gate covers. The frontend unit tests stub
# ``supabase.from`` wholesale, so a select string is only ever asserted against
# itself: it stays green after the column it names is dropped.
#
# email-history.js kept requesting ``event_sources.is_undone`` after
# 20260826000001 dropped it. PostgREST names embedded relations
# ``<relation>_1``, so every History load answered
# "column event_sources_1.is_undone does not exist" and the whole processed
# email list rendered empty. Nothing went red: the frontend lane mocks the
# database and the backend never issues that query.
#
# The regression arrived by stale branch rather than by bad edit. #332 removed
# the column; #342 branched before that, and its squash rewrote the same line
# and restored it. Only the live schema can catch that.
_SUPABASE_CALL = re.compile(r"\.(from|select)\(")
_MODULE_CONSTANT = re.compile(
    r"^\s*(?:export\s+)?const\s+([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(['\"`])(.*?)\2\s*;?\s*$",
    re.MULTILINE | re.DOTALL,
)
_ALIAS = re.compile(r"^([A-Za-z_][A-Za-z0-9_]*)\s*:(?!:)")
_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _first_call_argument(text: str, start: int) -> str | None:
    """Return the source of the first argument of a call opened at ``start``.

    ``start`` points just past the opening parenthesis. Quotes are tracked so a
    comma or parenthesis inside a select string does not end the argument.
    """
    depth = 1
    quote: str | None = None
    index = start
    while index < len(text):
        char = text[index]
        if quote is not None:
            if char == "\\":
                index += 2
                continue
            if char == quote:
                quote = None
        elif char in "'\"`":
            quote = char
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth == 0:
                return text[start:index]
        elif char == "," and depth == 1:
            return text[start:index]
        index += 1
    return None


def _split_top_level(select: str) -> list[str]:
    parts: list[str] = []
    depth = 0
    current: list[str] = []
    for char in select:
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
        if char == "," and depth == 0:
            parts.append("".join(current))
            current = []
            continue
        current.append(char)
    parts.append("".join(current))
    return [part.strip() for part in parts if part.strip()]


def _referenced_columns(table: str, select: str, origin: str) -> list[tuple[str, str]]:
    """Resolve a PostgREST select string to the (table, column) pairs it needs.

    An unrecognised token raises rather than being skipped. A parser that
    quietly ignores what it cannot read is the same green-by-omission failure
    this test exists to remove.
    """
    references: list[tuple[str, str]] = []
    for token in _split_top_level(select):
        if token == "*":
            continue
        if token.startswith("..."):
            token = token[3:].strip()
        alias = _ALIAS.match(token)
        if alias:
            token = token[alias.end() :].strip()
        if token.endswith(")"):
            head, _, inner = token.partition("(")
            relation = head.split("!", 1)[0].strip()
            if not _IDENTIFIER.match(relation):
                raise AssertionError(f"{origin}: unreadable embedded relation {head!r}")
            references.extend(_referenced_columns(relation, inner[:-1], origin))
            continue
        column = token.split("::", 1)[0].split("->", 1)[0].split("!", 1)[0].strip()
        if column == "*" or not column:
            continue
        if not _IDENTIFIER.match(column):
            raise AssertionError(f"{origin}: unreadable select token {token!r}")
        references.append((table, column))
    return references


def _frontend_column_references() -> list[tuple[str, str, str]]:
    """Every (table, column, origin) a frontend PostgREST select depends on.

    Each ``.select()`` is attributed to the nearest preceding ``.from()`` in the
    same file, which is how the Supabase JS builder chains. A select string held
    in a module constant is resolved through that constant.
    """
    repo_root = Path(__file__).resolve().parents[3]
    frontend_root = repo_root / "frontend" / "src"
    sources = sorted(frontend_root.rglob("*.js")) + sorted(frontend_root.rglob("*.svelte"))
    references: list[tuple[str, str, str]] = []
    for path in sources:
        if "__tests__" in path.parts:
            continue
        text = path.read_text()
        constants = {
            match.group(1): match.group(3) for match in _MODULE_CONSTANT.finditer(text)
        }
        table: str | None = None
        for match in _SUPABASE_CALL.finditer(text):
            argument = _first_call_argument(text, match.end())
            if argument is None:
                continue
            argument = argument.strip()
            line = text.count("\n", 0, match.start()) + 1
            origin = f"{path.relative_to(repo_root)}:{line}"
            if match.group(1) == "from":
                # A non-literal argument is not a Supabase table selection --
                # Array.from(...) reads identically here. Leave the current
                # table alone rather than inventing one.
                if len(argument) > 1 and argument[0] in "'\"`" and argument[-1] == argument[0]:
                    table = argument[1:-1].strip()
                continue
            if not argument:
                continue
            if len(argument) > 1 and argument[0] in "'\"`" and argument[-1] == argument[0]:
                select = argument[1:-1]
            elif argument in constants:
                select = constants[argument]
            else:
                # A computed select string cannot be checked here. Fail rather
                # than skip: an unverifiable query is exactly what this gate is
                # for, and the fix is to hoist it into a constant.
                raise AssertionError(f"{origin}: select argument {argument!r} is not a literal")
            if table is None:
                raise AssertionError(f"{origin}: select has no resolvable .from() table")
            references.extend(
                (found_table, found_column, origin)
                for found_table, found_column in _referenced_columns(table, select, origin)
            )
    return references


@pytest.mark.asyncio
async def test_frontend_select_columns_exist_in_the_live_schema(pg_pool):
    rows = await pg_pool.fetch(
        """
        SELECT table_name, column_name
        FROM information_schema.columns
        WHERE table_schema = 'public'
        """
    )
    live_columns = {(row["table_name"], row["column_name"]) for row in rows}
    live_tables = {table for table, _ in live_columns}

    missing: list[str] = []
    for table, column, origin in _frontend_column_references():
        if table not in live_tables:
            missing.append(f"{origin}: table public.{table} does not exist")
        elif (table, column) not in live_columns:
            missing.append(f"{origin}: public.{table}.{column} does not exist")

    assert not missing, "frontend queries request columns the schema does not have:\n" + "\n".join(
        sorted(set(missing))
    )
