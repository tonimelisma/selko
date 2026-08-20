#!/usr/bin/env python3
"""Safely rehearse and, only with explicit authorization, repair known events.

The manifest is an operator-owned file and is deliberately content-free:
UUIDs, actions, and hashes only.  Dry-run is the default.  ``--apply`` is
fail-closed and requires an explicit production environment, user UUID, and
redacted artifact path.  No command in this module discovers or mutates a
production target implicitly.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any
from uuid import UUID

import asyncpg

from selko.config import load_config

MANIFEST_VERSION = 1
ALLOWED_ACTIONS = {
    "merge_duplicate_group",
    "cancel_event",
    "resolve_proposal",
}
ALLOWED_MERGE_STATUSES = {
    "pending_review",
    "pending_change",
    "approved",
    "synced",
    "sync_failed",
    "cancel_queued",
}
EVENT_HASH_FIELDS = (
    "id",
    "user_id",
    "title",
    "start_datetime",
    "end_datetime",
    "all_day",
    "location",
    "description",
    "importance",
    "status",
    "recurrence_rule",
    "google_calendar_event_id",
    "source_attribution",
    "created_at",
    "updated_at",
)
SOURCE_HASH_FIELDS = (
    "id",
    "event_id",
    "email_id",
    "source_origin",
    "source_type",
    "extracted_data",
    "event_snapshot_before",
    "change_set",
    "is_undone",
    "created_at",
)


class RepairError(Exception):
    """A manifest or database precondition failed."""


@dataclass(frozen=True)
class RepairAction:
    kind: str
    payload: dict[str, Any]


def _uuid(value: Any, field: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise RepairError(f"{field} is not a UUID") from exc


def _absolute_file(value: str, field: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise RepairError(f"{field} must be an absolute path")
    if not path.is_file():
        raise RepairError(f"{field} is not a regular file")
    return path


def _absolute_output(value: str, field: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise RepairError(f"{field} must be an absolute path")
    if path.exists() and not path.is_file():
        raise RepairError(f"{field} must name a file, not a directory")
    if not path.parent.is_dir():
        raise RepairError(f"{field} parent directory does not exist")
    return path


def _load_manifest(path_value: str) -> tuple[str, list[RepairAction]]:
    path = _absolute_file(path_value, "--manifest")
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RepairError(f"could not read manifest: {exc}") from exc
    if not isinstance(document, dict) or document.get("version") != MANIFEST_VERSION:
        raise RepairError(f"manifest version must be {MANIFEST_VERSION}")
    user_id = _uuid(document.get("user_id"), "manifest.user_id")
    raw_actions = document.get("actions")
    if not isinstance(raw_actions, list) or not raw_actions:
        raise RepairError("manifest.actions must be a non-empty array")

    actions: list[RepairAction] = []
    for index, raw in enumerate(raw_actions):
        if not isinstance(raw, dict):
            raise RepairError(f"actions[{index}] must be an object")
        kind = raw.get("action")
        if kind not in ALLOWED_ACTIONS:
            raise RepairError(f"actions[{index}].action is not supported")
        payload = dict(raw)
        if kind == "merge_duplicate_group":
            payload["survivor_id"] = _uuid(payload.get("survivor_id"), f"actions[{index}].survivor_id")
            duplicate_ids = payload.get("duplicate_ids")
            if not isinstance(duplicate_ids, list) or not duplicate_ids:
                raise RepairError(f"actions[{index}].duplicate_ids must be non-empty")
            payload["duplicate_ids"] = [_uuid(item, f"actions[{index}].duplicate_ids") for item in duplicate_ids]
            expected = payload.get("expected_field_hashes", {})
            if not isinstance(expected, dict):
                raise RepairError(f"actions[{index}].expected_field_hashes must be an object")
            for event_id in [payload["survivor_id"], *payload["duplicate_ids"]]:
                if not isinstance(expected.get(event_id), str) or len(expected[event_id]) != 64:
                    raise RepairError(f"actions[{index}] is missing a SHA-256 field hash")
        elif kind == "cancel_event":
            payload["event_id"] = _uuid(payload.get("event_id"), f"actions[{index}].event_id")
            if payload.get("reason") != "authoritative_user_report":
                raise RepairError("cancel_event reason must be authoritative_user_report")
            if payload.get("exact_match") is not True:
                raise RepairError("cancel_event requires exact_match=true")
            if not isinstance(payload.get("expected_field_hash"), str) or len(payload["expected_field_hash"]) != 64:
                raise RepairError(f"actions[{index}] is missing expected_field_hash")
        else:
            payload["event_id"] = _uuid(payload.get("event_id"), f"actions[{index}].event_id")
            payload["proposal_id"] = _uuid(payload.get("proposal_id"), f"actions[{index}].proposal_id")
            if payload.get("reason") not in {"historical_proposal_cleanup", "operator_confirmed_rejection"}:
                raise RepairError("resolve_proposal reason is not an enumerated operator reason")
            if not isinstance(payload.get("expected_proposal_hash"), str) or len(payload["expected_proposal_hash"]) != 64:
                raise RepairError(f"actions[{index}] is missing expected_proposal_hash")
        actions.append(RepairAction(kind, payload))
    return user_id, actions


def _json_value(value: Any) -> Any:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    return value


def _safe_hash(row: dict[str, Any], fields: tuple[str, ...]) -> str:
    values = {field: _json_value(row.get(field)) for field in fields}
    encoded = json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def event_field_hash(row: dict[str, Any]) -> str:
    """Return a content-free hash used to detect stale operator manifests."""
    return _safe_hash(row, EVENT_HASH_FIELDS)


def source_field_hash(row: dict[str, Any]) -> str:
    return _safe_hash(row, SOURCE_HASH_FIELDS)


def _event_ids(actions: list[RepairAction], additional_ids: set[str] | None = None) -> set[str]:
    ids: set[str] = set()
    for action in actions:
        if action.kind == "merge_duplicate_group":
            ids.add(action.payload["survivor_id"])
            ids.update(action.payload["duplicate_ids"])
        elif action.kind == "cancel_event":
            ids.add(action.payload["event_id"])
        elif action.kind == "resolve_proposal":
            ids.add(action.payload["event_id"])
    ids.update(additional_ids or set())
    return ids


async def _lock_events(conn: asyncpg.Connection, user_id: str, actions: list[RepairAction], additional_ids: set[str] | None = None) -> dict[str, dict[str, Any]]:
    ids = sorted(_event_ids(actions, additional_ids))
    if not ids:
        return {}
    rows = await conn.fetch(
        "SELECT * FROM public.events WHERE id = ANY($1::uuid[]) ORDER BY id FOR UPDATE",
        ids,
    )
    events = {str(row["id"]): dict(row) for row in rows}
    for event_id in ids:
        row = events.get(event_id)
        if row is None:
            raise RepairError(f"event {event_id} does not exist")
        if str(row["user_id"]) != user_id:
            raise RepairError(f"event {event_id} is not owned by the confirmed user")
    return events


async def _active_source_locks(conn: asyncpg.Connection, event_ids: list[str]) -> list[str]:
    if not event_ids:
        return []
    rows = await conn.fetch(
        """
        SELECT DISTINCT e.id
        FROM public.events e
        JOIN public.event_sources s ON s.event_id = e.id
        JOIN public.emails m ON m.id = s.email_id
        WHERE e.id = ANY($1::uuid[])
          AND m.locked_by IS NOT NULL
          AND m.locked_until > now()
        ORDER BY e.id
        """,
        event_ids,
    )
    return [str(row["id"]) for row in rows]


def _event_is_locked(row: dict[str, Any]) -> bool:
    locked_until = row.get("locked_until")
    return bool(row.get("locked_by") and locked_until and locked_until > datetime.now(locked_until.tzinfo or timezone.utc))


async def _check_merge(action: RepairAction, events: dict[str, dict[str, Any]], user_id: str, conn: asyncpg.Connection) -> list[str]:
    payload = action.payload
    survivor_id = payload["survivor_id"]
    duplicate_ids = payload["duplicate_ids"]
    failures: list[str] = []
    survivor = events[survivor_id]
    expected = payload["expected_field_hashes"]
    if event_field_hash(survivor) != expected[survivor_id]:
        failures.append(f"event {survivor_id} field hash changed")
    if survivor["status"] not in ALLOWED_MERGE_STATUSES:
        failures.append(f"survivor {survivor_id} has disallowed status {survivor['status']}")
    if _event_is_locked(survivor):
        failures.append(f"event {survivor_id} has an active worker lock")
    for duplicate_id in duplicate_ids:
        duplicate = events[duplicate_id]
        if duplicate_id == survivor_id:
            failures.append("survivor cannot also be a duplicate")
        if event_field_hash(duplicate) != expected[duplicate_id]:
            failures.append(f"event {duplicate_id} field hash changed")
        if duplicate["status"] not in ALLOWED_MERGE_STATUSES:
            failures.append(f"duplicate {duplicate_id} has disallowed status {duplicate['status']}")
        if _event_is_locked(duplicate):
            failures.append(f"event {duplicate_id} has an active worker lock")
        if duplicate["google_calendar_event_id"] and survivor["google_calendar_event_id"] not in (None, duplicate["google_calendar_event_id"]):
            failures.append(f"duplicate {duplicate_id} has a conflicting calendar identity")
    locked = await _active_source_locks(conn, [survivor_id, *duplicate_ids])
    failures.extend(f"event {event_id} has an active email worker lock" for event_id in locked)
    # The merge code explicitly reconciles same-email conflicts before moving
    # rows, so a unique(event_id,email_id) violation cannot be silent.
    return failures


async def _check_cancel(action: RepairAction, events: dict[str, dict[str, Any]]) -> list[str]:
    payload = action.payload
    row = events[payload["event_id"]]
    failures: list[str] = []
    if event_field_hash(row) != payload["expected_field_hash"]:
        failures.append(f"event {payload['event_id']} field hash changed")
    if row["status"] in {"cancelled", "rejected", "syncing"}:
        failures.append(f"event {payload['event_id']} cannot be cancelled from status {row['status']}")
    if _event_is_locked(row):
        failures.append(f"event {payload['event_id']} has an active worker lock")
    return failures


async def _check_proposal(action: RepairAction, proposal_rows: dict[str, dict[str, Any]], conn: asyncpg.Connection) -> tuple[dict[str, Any] | None, list[str]]:
    proposal_id = action.payload["proposal_id"]
    row = proposal_rows.get(proposal_id)
    failures: list[str] = []
    if row is None:
        failures.append(f"proposal {proposal_id} is missing or not owned by the confirmed user")
        return None, failures
    data = dict(row)
    actual_hash = await conn.fetchval(
        "SELECT public.event_change_proposal_hash(p) FROM public.event_change_proposals p WHERE p.id = $1::uuid",
        proposal_id,
    )
    if actual_hash != action.payload["expected_proposal_hash"]:
        failures.append(f"proposal {proposal_id} hash changed")
    if data["status"] != "closed_legacy":
        failures.append(f"proposal {proposal_id} is not a closed legacy proposal")
    return data, failures


async def _preconditions(conn: asyncpg.Connection, user_id: str, actions: list[RepairAction]) -> tuple[dict[str, dict[str, Any]], list[str], dict[str, Any]]:
    proposal_ids = sorted(
        action.payload["proposal_id"]
        for action in actions
        if action.kind == "resolve_proposal"
    )
    proposal_rows = {
        str(row["id"]): dict(row)
        for row in await conn.fetch(
            """
            SELECT p.* FROM public.event_change_proposals p
            WHERE p.id = ANY($1::uuid[]) AND p.user_id = $2::uuid
            ORDER BY p.id FOR UPDATE
            """,
            proposal_ids,
            user_id,
        )
    } if proposal_ids else {}
    proposal_event_ids = {str(row["event_id"]) for row in proposal_rows.values()}
    events = await _lock_events(conn, user_id, actions, proposal_event_ids)
    failures: list[str] = []
    proposals: dict[str, Any] = {}
    for action in actions:
        if action.kind == "merge_duplicate_group":
            failures.extend(await _check_merge(action, events, user_id, conn))
        elif action.kind == "cancel_event":
            failures.extend(await _check_cancel(action, events))
        else:
            proposal, source_failures = await _check_proposal(action, proposal_rows, conn)
            failures.extend(source_failures)
            if proposal is not None:
                proposals[action.payload["proposal_id"]] = proposal
    return events, failures, proposals


async def _audit(conn: asyncpg.Connection, user_id: str, event_id: str | None, action: str, reason: str, pre_change: dict[str, Any]) -> None:
    await conn.execute(
        """
        INSERT INTO public.event_repair_audit (user_id, event_id, action, reason, actor, pre_change)
        VALUES ($1::uuid, $2::uuid, $3, $4, 'repair_review_queue_integrity', $5::jsonb)
        """,
        user_id,
        event_id,
        action,
        reason,
        json.dumps(pre_change, sort_keys=True),
    )


async def _regenerate_attribution(conn: asyncpg.Connection, event_id: str) -> None:
    # Keep source content out of logs/manifests while using the canonical
    # attribution implementation shared by normal event writes.
    from selko.services.event_processing import generate_source_attribution

    rows = await conn.fetch(
        """
        SELECT s.source_type, s.is_undone, s.created_at,
               m.from_email, m.from_name, m.date_sent
        FROM public.event_sources s
        LEFT JOIN public.emails m ON m.id = s.email_id
        WHERE s.event_id = $1::uuid
        ORDER BY s.created_at
        """,
        event_id,
    )
    sources = [dict(row) for row in rows]
    attribution = generate_source_attribution(sources)
    await conn.execute("UPDATE public.events SET source_attribution = $2, updated_at = now() WHERE id = $1::uuid", event_id, attribution or None)


async def _merge(conn: asyncpg.Connection, user_id: str, action: RepairAction, events: dict[str, dict[str, Any]]) -> int:
    survivor_id = action.payload["survivor_id"]
    changed = 0
    for duplicate_id in sorted(action.payload["duplicate_ids"]):
        sources = [
            dict(row)
            for row in await conn.fetch(
                "SELECT * FROM public.event_sources WHERE event_id = ANY($1::uuid[]) ORDER BY id FOR UPDATE",
                [survivor_id, duplicate_id],
            )
        ]
        survivor_by_email = {str(row["email_id"]): row for row in sources if str(row["event_id"]) == survivor_id}
        duplicate_rows = [row for row in sources if str(row["event_id"]) == duplicate_id]
        moved = 0
        for source in duplicate_rows:
            email_id = str(source["email_id"])
            existing = survivor_by_email.get(email_id)
            if existing is None:
                await conn.execute("UPDATE public.event_sources SET event_id = $1::uuid WHERE id = $2::uuid", survivor_id, str(source["id"]))
                moved += 1
                continue
            def richness(row: dict[str, Any]) -> tuple[int, int, str]:
                return (int(not row["is_undone"]), len(json.dumps(row.get("extracted_data") or {}, sort_keys=True)), str(row.get("created_at") or ""))
            winner, loser = (source, existing) if richness(source) > richness(existing) else (existing, source)
            await _audit(conn, user_id, survivor_id, "merge_source", "duplicate_event_merge", {
                "survivor_source_id": str(existing["id"]),
                "duplicate_source_id": str(source["id"]),
                "winner_source_id": str(winner["id"]),
                "loser_source_id": str(loser["id"]),
                "survivor_event_id": survivor_id,
                "duplicate_event_id": duplicate_id,
            })
            if str(winner["id"]) == str(source["id"]):
                await conn.execute("UPDATE public.event_sources SET event_id = $1::uuid WHERE id = $2::uuid", survivor_id, str(source["id"]))
            await conn.execute("DELETE FROM public.event_sources WHERE id = $1::uuid", str(loser["id"]))
            moved += 1
        await _audit(conn, user_id, survivor_id, "merge_duplicate_group", "duplicate_event_merge", {
            "survivor_event_id": survivor_id,
            "duplicate_event_id": duplicate_id,
            "sources_considered": len(duplicate_rows),
            "sources_moved_or_reconciled": moved,
            "survivor_field_hash": event_field_hash(events[survivor_id]),
            "duplicate_field_hash": event_field_hash(events[duplicate_id]),
        })
        await conn.execute("DELETE FROM public.events WHERE id = $1::uuid AND user_id = $2::uuid", duplicate_id, user_id)
        changed += 1
    await _regenerate_attribution(conn, survivor_id)
    return changed


async def _apply(conn: asyncpg.Connection, user_id: str, actions: list[RepairAction], events: dict[str, dict[str, Any]], proposals: dict[str, Any]) -> tuple[int, list[dict[str, Any]]]:
    changed = 0
    reverse_ops: list[dict[str, Any]] = []
    for action in actions:
        if action.kind == "merge_duplicate_group":
            changed += await _merge(conn, user_id, action, events)
            reverse_ops.append({"action": "restore_duplicate_event", "survivor_id": action.payload["survivor_id"], "duplicate_ids": action.payload["duplicate_ids"]})
        elif action.kind == "cancel_event":
            event_id = action.payload["event_id"]
            before = events[event_id]
            result = await conn.fetchval("SELECT public.queue_event_cancellation($1::uuid, $2::uuid)", event_id, user_id)
            result_data = json.loads(result) if isinstance(result, str) else dict(result)
            if result_data.get("already_cancelled"):
                continue
            await _audit(conn, user_id, event_id, "cancel_event", action.payload["reason"], {
                "event_id": event_id,
                "before_status": before["status"],
                "before_calendar_sync_action": before.get("calendar_sync_action"),
                "before_calendar_work_generation": before.get("calendar_work_generation"),
            })
            changed += 1
            reverse_ops.append({"action": "restore_event_state", "event_id": event_id, "before_status": before["status"], "before_calendar_sync_action": before.get("calendar_sync_action"), "before_calendar_work_generation": before.get("calendar_work_generation")})
        else:
            proposal_id = action.payload["proposal_id"]
            proposal = proposals[proposal_id]
            await conn.fetchval(
                "SELECT public.resolve_event_change_proposal($1::uuid, $2::uuid, $3::uuid, $4, $5)",
                str(proposal["event_id"]), user_id, proposal_id,
                action.payload["expected_proposal_hash"], action.payload["reason"],
            )
            await _audit(conn, user_id, str(proposal["event_id"]), "resolve_proposal", action.payload["reason"], {
                "proposal_id": proposal_id,
                "before_status": proposal["status"],
            })
            changed += 1
            reverse_ops.append({"action": "restore_closed_legacy_proposal", "proposal_id": proposal_id})
    return changed, reverse_ops


async def _run(args: argparse.Namespace) -> int:
    if args.apply:
        if args.environment != "production":
            raise RepairError("--apply requires --environment production")
        if not args.manifest:
            raise RepairError("--apply requires --manifest <absolute path>")
        if not args.confirm_user:
            raise RepairError("--apply requires --confirm-user <uuid>")
        if not args.artifact:
            raise RepairError("--apply requires --artifact <absolute path>")
        artifact_path = _absolute_output(args.artifact, "--artifact")
    else:
        artifact_path = None
    if args.confirm_user:
        confirmed_user = _uuid(args.confirm_user, "--confirm-user")
    else:
        confirmed_user = None

    config = load_config(env_override=args.environment)
    if config.environment != args.environment:
        raise RepairError("loaded environment does not match --environment")
    if not config.supabase_db_url:
        raise RepairError("SUPABASE_DB_URL is required")
    manifest_user: str | None = None
    actions: list[RepairAction] = []
    if args.manifest:
        manifest_user, actions = _load_manifest(args.manifest)
        if confirmed_user and manifest_user != confirmed_user:
            raise RepairError("--confirm-user does not match manifest.user_id")
    user_id = confirmed_user or manifest_user
    if args.apply and user_id is None:
        raise RepairError("a confirmed user is required")

    conn = await asyncpg.connect(config.supabase_db_url, timeout=10, command_timeout=30)
    artifact_document: dict[str, Any] | None = None
    try:
        # Dry-run preconditions use deterministic row locks too.  The command
        # performs no writes unless --apply is set, but PostgreSQL must allow
        # those locks to make the inspection coherent.
        async with conn.transaction(isolation="serializable"):
            if not actions:
                rows = await conn.fetch("SELECT id, user_id, status FROM public.events WHERE status IN ('pending_review', 'pending_change') ORDER BY id LIMIT 1000")
                print(f"DRY-RUN candidates={len(rows)}")
                for row in rows:
                    print(f"event id={row['id']} user_id={row['user_id']} status={row['status']}")
                return 0
            events, failures, proposals = await _preconditions(conn, user_id, actions)
            if failures:
                print("PRECONDITION FAILED")
                for failure in failures:
                    print(f"- {failure}")
                return 2
            for event_id, row in sorted(events.items()):
                print(f"target event id={event_id} status={row['status']}")
            print(f"DRY-RUN actions={len(actions)} events={len(events)}")
            if not args.apply:
                return 0
            changed, reverse_ops = await _apply(conn, user_id, actions, events, proposals)
            if changed == 0:
                raise RepairError("--apply completed without mutating any row")
            artifact_document = {
                "version": 1,
                "user_id": user_id,
                "changed": changed,
                "reverse_operations": reverse_ops,
            }
            artifact_path.write_text(json.dumps(artifact_document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
            print(f"APPLIED changed={artifact_document['changed']} artifact={artifact_path}")
    finally:
        await conn.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--environment", choices=("development", "staging", "production"), default="development")
    parser.add_argument("--manifest")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--confirm-user")
    parser.add_argument("--artifact")
    return parser


def main() -> int:
    try:
        return asyncio.run(_run(build_parser().parse_args()))
    except (RepairError, OSError, asyncpg.PostgresError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
