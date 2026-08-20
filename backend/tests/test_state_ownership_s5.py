"""Static guards for the S5 state-owner cutover."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MIGRATION = ROOT / "supabase/migrations/20260826000001_remove_legacy_event_state.sql"


def _function_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def test_s5_migration_removes_legacy_event_and_source_columns() -> None:
    sql = MIGRATION.read_text(encoding="utf-8")
    assert "WHERE e.status = 'sync_failed'" in sql
    assert "Preserve those rows as terminal work" in sql
    for column in (
        "change_set",
        "event_snapshot_before",
        "is_undone",
        "calendar_sync_action",
        "calendar_work_generation",
        "sync_attempts",
        "max_sync_attempts",
        "sync_error",
        "sync_failure_code",
        "dead_letter_reason",
        "dead_letter_at",
    ):
        assert f"DROP COLUMN IF EXISTS {column}" in sql
    assert "status IN (\n    'pending_review', 'approved'" in sql


def test_s5_removes_dead_direct_event_mutators() -> None:
    names = _function_names(ROOT / "backend/selko/services/events.py")
    assert not names.intersection(
        {
            "create_event",
            "update_event",
            "approve_event",
            "reject_event",
            "propose_local_change",
            "undo_email_contribution",
            "redo_email_contribution",
        }
    )
    assert "process_calendar_sync_job" not in _function_names(
        ROOT / "backend/selko/workers/calendar_sync.py"
    )


def test_calendar_worker_pool_uses_work_item_state() -> None:
    worker_pool = (ROOT / "backend/selko/workers/pool.py").read_text(encoding="utf-8")
    assert "calendar_work_item_generation" in worker_pool
    assert "calendar_work_item_attempts" in worker_pool
    assert "calendar_sync_action" not in worker_pool
