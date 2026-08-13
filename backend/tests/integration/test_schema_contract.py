"""Executable contracts for the live public database schema."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
import ast
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
    "ensure_email_sync_state",
    "handle_new_user",
    "notify_work_available",
    "reset_skipped_emails_for_sender_rule",
    "trg_emails_broadcast",
    "trg_event_sources_broadcast",
    "trg_events_broadcast",
    "trg_integrations_broadcast",
}


# Every enumerated CHECK domain in public is pinned here. Adding a value is a
# one-line edit, while removing one requires checking every writer first.
EXPECTED_CHECK_DOMAINS: dict[tuple[str, str], set[str]] = {
    ("action_history", "action_type"): {"create", "update", "delete"},
    ("action_history", "entity_type"): {"event", "sender_rule"},
    ("attachments", "ingestion_status"): {
        "pending", "processing", "stored", "unsupported", "retry", "dead_letter",
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
    },
    ("emails", "processing_status"): {"pending", "processing", "processed", "failed", "skipped"},
    ("event_sources", "source_origin"): {"email", "google_calendar", "google_photos"},
    ("event_sources", "source_type"): {"new_invitation", "update", "cancellation", "reminder", "unknown"},
    ("events", "calendar_sync_action"): {"upsert", "cancel"},
    ("events", "importance"): {"action_required", "fyi"},
    ("events", "status"): {
        "pending_review", "pending_change", "approved", "rejected", "cancelled",
        "cancel_queued", "syncing", "synced", "sync_failed",
    },
    ("events", "sync_failure_code"): {
        "oauth_required", "oauth_scope_required", "provider_transient", "rate_limited",
        "invalid_event", "permission_denied", "unknown",
    },
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
        "INSERT INTO public.events (id, user_id, title, status) VALUES ($1, $2, 'schema contract event', 'pending_review')",
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
        "broadcast_user_ui_change": (context.user_id, "events", "updated", context.event_id),
        "check_and_increment_quota": (context.user_id, "llm_calls", 1),
        "claim_due_email_reconciliation": (worker, 60),
        "claim_due_email_sync": (worker, 60),
        "claim_email_attachment": (worker, 60),
        "claim_email_ingestion_item": (worker, 60),
        "claim_integration_recovery": (worker, 60),
        "claim_pending_photo": (worker, 60),
        "claim_unprocessed_email": (worker, 60),
        "complete_email_ingestion_item": (context.ingestion_item_id, worker, context.email_id),
        "complete_email_sync": (context.gmail_integration_id, context.sync_run_id, worker, 60, False),
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
        "fail_email_sync": (context.gmail_integration_id, context.sync_run_id, worker, "schema_contract", "probe", 5, 60, False),
        "finish_email_attachment": (context.attachment_id, worker, "stored", "schema_contract"),
        "get_llm_usage_summary": (context.user_id, date.today() - timedelta(days=1), date.today()),
        "get_user_quota_usage": (context.user_id, date.today()),
        "health_dead_letter_counts": (),
        "health_poll_slo": (60,),
        "heartbeat_email_sync": (context.gmail_integration_id, worker, 60),
        "reconcile_outlook_email_folders": (context.outlook_integration_id, []),
        "refresh_waiting_calendar_recoveries": (10,),
        "reprocess_email": (context.user_id, context.email_id),
        "request_email_sync_now": (context.gmail_integration_id,),
        "requeue_calendar_recovery_batch": (context.recovery_id, worker, 10, 1),
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
        "claim_calendar_work": ("schema-contract-worker", 60),
        "claim_approved_event": ("schema-contract-worker", 60),
        "set_email_folder_preference": (context.folder_id, True),
        "unlock_expired_integration_recoveries": (),
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

    for name, args in contracts.items():
        encoded_args = [
            json.dumps(value)
            if isinstance(value, (dict, list))
            and name in {"save_email_with_attachment_descriptors", "upsert_discovered_email_items"}
            else value
            for value in args
        ]
        placeholders = ", ".join(f"${index}" for index in range(1, len(args) + 1))
        try:
            await conn.fetch(f"SELECT * FROM public.{name}({placeholders})", *encoded_args)
        except Exception as exc:
            pytest.fail(f"{name}({args!r}) is not callable: {exc}")


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
async def test_security_definer_functions_are_not_executable_by_public(pg_pool):
    rows = await pg_pool.fetch(
        """
        SELECT p.proname AS name,
               pg_get_function_identity_arguments(p.oid) AS identity_arguments
        FROM pg_proc AS p
        JOIN pg_namespace AS n ON n.oid = p.pronamespace
        WHERE n.nspname = 'public'
          AND p.prosecdef
          AND has_function_privilege('public', p.oid, 'EXECUTE')
        ORDER BY p.proname, identity_arguments
        """
    )
    assert not rows, [f"{row['name']}({row['identity_arguments']})" for row in rows]


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
        "email_ingestion_items": _exercise_ingestion_item_triggers,
        "emails": _exercise_email_triggers,
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
    await conn.execute(
        "INSERT INTO public.event_sources (id, event_id, email_id, extracted_data) VALUES ($1, $2, $3, '{}'::jsonb)",
        row_id, context.event_id, context.email_id,
    )
    await conn.execute("UPDATE public.event_sources SET extracted_data = '{\"updated\": true}'::jsonb WHERE id = $1", row_id)


async def _exercise_event_triggers(conn, context):
    row_id = uuid4()
    await conn.execute(
        "INSERT INTO public.events (id, user_id, title, status) VALUES ($1, $2, 'trigger event', 'pending_review')",
        row_id, context.user_id,
    )
    await conn.execute("UPDATE public.events SET title = 'updated trigger event', status = 'rejected' WHERE id = $1", row_id)
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
