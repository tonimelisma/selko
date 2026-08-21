"""Regression tests for the content-free, fail-closed repair tool."""

import asyncio
import json
import sys
from argparse import Namespace
from datetime import datetime, timezone
from pathlib import Path

import pytest

# ``scripts/`` is intentionally a directory of operator entry points rather
# than an installed package.  Add the repository root only for this import.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.repair_review_queue_integrity import (
    RepairError,
    _load_manifest,
    _run,
    event_field_hash,
)


def test_repair_migration_secures_audit_and_centralizes_cancellation() -> None:
    migration = (
        Path(__file__).resolve().parents[2]
        / "supabase/migrations/20260818000001_repair_event_cancellation.sql"
    ).read_text(encoding="utf-8")
    assert "ALTER TABLE public.event_repair_audit ENABLE ROW LEVEL SECURITY" in migration
    assert "GRANT ALL ON TABLE public.event_repair_audit TO service_role" in migration
    assert "CREATE OR REPLACE FUNCTION public.queue_event_cancellation" in migration
    assert "status = 'cancel_queued'" in migration
    assert "calendar_sync_action = 'cancel'" in migration


def sample_event() -> dict[str, object]:
    return {
        "id": "11111111-1111-1111-1111-111111111111",
        "user_id": "22222222-2222-2222-2222-222222222222",
        "title": "ignored by the hash consumer",
        "start_datetime": datetime(2026, 8, 1, tzinfo=timezone.utc),
        "end_datetime": datetime(2026, 8, 1, 1, tzinfo=timezone.utc),
        "all_day": False,
        "location": None,
        "description": None,
        "importance": "action_required",
        "review_status": "pending_review",
        "recurrence_rule": None,
        "google_calendar_event_id": None,
        "source_attribution": None,
        "created_at": datetime(2026, 8, 1, tzinfo=timezone.utc),
        "updated_at": datetime(2026, 8, 1, tzinfo=timezone.utc),
    }


def test_event_hash_changes_when_any_guarded_field_changes() -> None:
    event = sample_event()
    original = event_field_hash(event)
    event["updated_at"] = datetime(2026, 8, 2, tzinfo=timezone.utc)
    assert event_field_hash(event) != original


def test_manifest_accepts_only_exact_cancellation_authority(tmp_path) -> None:
    event = sample_event()
    manifest = {
        "version": 1,
        "user_id": event["user_id"],
        "actions": [
            {
                "action": "cancel_event",
                "event_id": event["id"],
                "reason": "authoritative_user_report",
                "exact_match": True,
                "expected_field_hash": event_field_hash(event),
            }
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    user_id, actions = _load_manifest(str(path))
    assert user_id == event["user_id"]
    assert actions[0].kind == "cancel_event"


def test_manifest_rejects_ambiguous_cancellation(tmp_path) -> None:
    manifest = {
        "version": 1,
        "user_id": "22222222-2222-2222-2222-222222222222",
        "actions": [
            {
                "action": "cancel_event",
                "event_id": "11111111-1111-1111-1111-111111111111",
                "reason": "authoritative_user_report",
                "exact_match": False,
                "expected_field_hash": "0" * 64,
            }
        ],
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RepairError, match="exact_match=true"):
        _load_manifest(str(path))


def test_manifest_resolves_a_proposal_by_id_and_hash(tmp_path) -> None:
    manifest = {
        "version": 1,
        "user_id": "22222222-2222-2222-2222-222222222222",
        "actions": [{
            "action": "resolve_proposal",
            "event_id": "11111111-1111-1111-1111-111111111111",
            "proposal_id": "33333333-3333-3333-3333-333333333333",
            "reason": "historical_proposal_cleanup",
            "expected_proposal_hash": "0" * 64,
        }],
    }
    path = tmp_path / "proposal-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    user_id, actions = _load_manifest(str(path))
    assert user_id == manifest["user_id"]
    assert actions[0].kind == "resolve_proposal"


def test_manifest_rejects_legacy_source_resolution(tmp_path) -> None:
    manifest = {
        "version": 1,
        "user_id": "22222222-2222-2222-2222-222222222222",
        "actions": [{
            "action": "mark_source_resolved",
            "source_id": "33333333-3333-3333-3333-333333333333",
            "expected_source_hash": "0" * 64,
        }],
    }
    path = tmp_path / "legacy-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(RepairError, match="not supported"):
        _load_manifest(str(path))


def test_apply_requires_production_and_all_operator_guards() -> None:
    args = Namespace(
        environment="staging",
        manifest=None,
        apply=True,
        confirm_user=None,
        artifact=None,
    )
    with pytest.raises(RepairError, match="production"):
        asyncio.run(_run(args))
