"""Guards that keep `events` writable only through the data layer's named transitions.

Successor of `test_workers.py::test_event_writes_go_through_commit_rpc` (and its
shadowed copy), which looked for supabase-py `.table("events").insert(` calls.
No SQLite code contains that shape, so left as it was the old guard would pass
forever (docs/specs/sqlite-single-process/05-verification.md §A.7).

The rule it keeps: event rows are created and changed only by the fenced
extraction commit and the named review / calendar transitions. Any SQL text in
`backend/selko/` that inserts into, updates or deletes from `events` must live
in one of the modules below, each with its reason.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

SELKO = Path(__file__).resolve().parents[1] / "selko"

# Modules allowed to hold SQL that writes `events`, and why.
EVENT_WRITERS = {
    "db/events.py": "commit_email_extraction, set_event_review_status and the late-match retirement",
    "db/proposals.py": "apply / reject / reopen of change proposals",
    "db/calendar_work.py": "calendar work transitions stamp delivery fields and updated_at",
    "db/startup.py": "the startup lease reset",
    "db/recovery.py": "reconnect recovery tags the events whose calendar work it requeues",
    # Interim, owned by the API group: E4's whitelisted field edit belongs in
    # db/events.py next to the other user transitions.
    "db/client.py": "E4 update_event: the user edits an owned event's own fields (no review state)",
    "db/demo.py": "the image CI's demo account seed (refuses an account that already has events)",
}

_EVENT_WRITE = re.compile(r"\b(INSERT\s+(OR\s+\w+\s+)?INTO|UPDATE|DELETE\s+FROM|REPLACE\s+INTO)\s+events\b",
                          re.IGNORECASE)


def _sql_strings(tree: ast.AST):
    """Every string constant, with the pieces of each f-string joined."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value
        elif isinstance(node, ast.JoinedStr):
            text = "".join(v.value for v in node.values if isinstance(v, ast.Constant))
            yield node.lineno, text


def _python_files() -> list[Path]:
    files = sorted(p for p in SELKO.rglob("*.py") if "__pycache__" not in p.parts)
    assert files, f"no Python files under {SELKO}: the guard would pass vacuously"
    return files


def test_events_are_written_only_by_the_commit_function():
    offenders = []
    writers_seen = set()
    for path in _python_files():
        relative = path.relative_to(SELKO).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for lineno, text in _sql_strings(tree):
            if not _EVENT_WRITE.search(text):
                continue
            if relative in EVENT_WRITERS:
                writers_seen.add(relative)
            else:
                offenders.append(f"{relative}:{lineno}")

    assert not offenders, "SQL writing `events` outside the data layer's transitions: " + ", ".join(offenders)
    # The guard can fail: the commit's own writes are found, so the scan sees SQL at all.
    assert "db/events.py" in writers_seen


def test_the_guard_recognizes_every_shape_of_event_write():
    for sql in (
        "INSERT INTO events (id) VALUES (?)",
        "insert or replace into events (id) values (?)",
        "UPDATE events SET title = ?",
        "DELETE FROM events WHERE id = ?",
    ):
        assert _EVENT_WRITE.search(sql), sql
    for sql in (
        "UPDATE event_sources SET x = 1",
        "INSERT INTO events_archive (id) VALUES (?)",
        "SELECT * FROM events",
        "DELETE FROM event_change_proposals WHERE event_id = ?",
    ):
        assert not _EVENT_WRITE.search(sql), sql


def test_the_allowlist_names_only_modules_that_exist():
    for relative in EVENT_WRITERS:
        assert (SELKO / relative).is_file(), f"{relative} is allowed to write events but does not exist"
