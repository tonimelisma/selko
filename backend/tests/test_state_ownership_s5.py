"""Static ownership guards for the S5 state-owner cutover."""

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _functions(path: Path) -> dict[str, ast.FunctionDef | ast.AsyncFunctionDef]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    return {
        node.name: node
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }


def _function(path: Path, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef:
    return _functions(path)[name]


def _arg_names(node: ast.FunctionDef | ast.AsyncFunctionDef) -> list[str]:
    return [arg.arg for arg in node.args.args]


def test_s5_removes_dead_direct_event_mutators() -> None:
    names = set(_functions(ROOT / "backend/selko/services/events.py"))
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
    assert "process_calendar_sync_job" not in _functions(
        ROOT / "backend/selko/workers/calendar_sync.py"
    )


def test_calendar_write_helpers_accept_only_typed_leases() -> None:
    path = ROOT / "backend/selko/services/events.py"
    functions = _functions(path)
    expected = {
        "complete_event_sync": ["pool", "lease", "google_event_id"],
        "complete_event_cancellation": ["pool", "lease"],
        "defer_event_sync_for_quota": ["pool", "lease", "next_retry_at"],
        "park_event_for_oauth_reauth": ["pool", "lease", "sync_failure_code", "user_message"],
        "fail_event_sync": ["pool", "lease", "error"],
    }
    for name, args in expected.items():
        node = functions[name]
        assert _arg_names(node) == args
        assert ast.unparse(node.args.args[1].annotation) == "WorkItemLease"

    resolver = functions["_resolve_calendar_work_item"]
    assert _arg_names(resolver) == ["pool", "lease"]
    assert ast.unparse(resolver.args.args[1].annotation) == "WorkItemLease"


def test_calendar_worker_dispatches_every_write_with_the_claimed_lease() -> None:
    path = ROOT / "backend/selko/workers/pool.py"
    node = _function(path, "_process_event_sync")
    names = {
        call.func.id
        for call in ast.walk(node)
        if isinstance(call, ast.Call)
        and isinstance(call.func, ast.Name)
        and call.func.id in {
            "complete_event_sync",
            "complete_event_cancellation",
            "defer_event_sync_for_quota",
            "fail_event_sync",
            "park_event_for_oauth_reauth",
        }
    }
    assert names == {
        "complete_event_sync",
        "complete_event_cancellation",
        "defer_event_sync_for_quota",
        "fail_event_sync",
        "park_event_for_oauth_reauth",
    }
    for call in ast.walk(node):
        if (
            isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id in names
        ):
            assert isinstance(call.args[1], ast.Name)
            assert call.args[1].id == "lease"

    assigned_lease = any(
        isinstance(statement, ast.Assign)
        and any(isinstance(target, ast.Name) and target.id == "lease" for target in statement.targets)
        and isinstance(statement.value, ast.Subscript)
        and isinstance(statement.value.value, ast.Name)
        and statement.value.value.id == "event"
        for statement in ast.walk(node)
    )
    assert assigned_lease
    assert not any(
        isinstance(value, ast.Constant) and value.value in {
            "calendar_work_generation",
            "calendar_work_item_generation",
            "fenced_claim",
        }
        for value in ast.walk(node)
    )


def test_calendar_worker_claim_payload_is_lease_owned() -> None:
    worker_pool = (ROOT / "backend/selko/workers/pool.py").read_text(encoding="utf-8")
    assert "calendar_work_lease" in worker_pool
    assert "calendar_work_item_generation" not in worker_pool
    assert "calendar_sync_action" not in worker_pool
