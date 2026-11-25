"""Every data-layer function that touches a user-owned table takes ``user_id``.

This replaces row-level security (docs/specs/sqlite-single-process/02-data-layer.md
§1.1; 05-verification.md §A.2 rows 11, 23, 35): with no database roles, the only
thing standing between one user and another user's rows is that every
user-scoped read and write is handed the caller's id. The test reads the
source (AST), so a new function cannot slip past it by never being called in a
test.

A function "touches" a table when its body, or a module-level constant or
private helper it references (transitively), names the table after ``FROM``,
``JOIN``, ``INTO``, ``UPDATE`` or ``DELETE FROM``. User-owned tables are read
from the applied schema: every table with a ``user_id`` column, plus
``accounts`` and ``users`` (keyed by the user id itself).

Service-wide functions exist by design (workers claim any user's work; health
counts everything). They are listed in ``SERVICE_WIDE`` with the reason, or
matched by ``SERVICE_WIDE_PREFIXES``. An entry that no longer exists fails the
test, so the allowlist cannot rot.
"""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

import pytest

DB_PACKAGE = Path(__file__).resolve().parents[2] / "selko" / "db"

# Infrastructure, not data functions.
SKIP_MODULES = {"__init__", "connection", "codec", "errors", "bus", "runtime", "migrate"}

# The parameter names that carry the owner.
OWNER_PARAMS = {"user_id", "user_ids", "account_id"}

# Worker coordination is service-wide by design (02 §1.1 WORKER_SCOPED):
# every claim, heartbeat, complete/fail/defer, unlock and startup reset acts
# on whichever user's work is due, fenced by its lease, never by its owner.
SERVICE_WIDE_PREFIXES = (
    "claim_", "heartbeat_", "complete_", "fail_", "finish_", "defer_", "unlock_",
    "reset_", "requeue_", "refresh_waiting_",
)

# Operational incidents are operator records keyed by incident key, not user data.
SERVICE_WIDE_SUBSTRINGS = ("incident",)

SERVICE_WIDE: dict[str, str] = {
    # worker functions keyed by a row the worker already claimed or owns by
    # lease (an email, an integration, an ingestion item): the claim chose the
    # row service-wide, and the row carries its owner
    "attachments.for_email": "attachment worker, keyed by a claimed email",
    "calendar_work.get_leased_item": "calendar worker, fenced by its own lease",
    "email_sync.upsert_discovered_email_items": "discovery worker, fenced by its sync lease",
    "email_sync.known_provider_message_ids": "discovery worker, keyed by a leased integration",
    "email_sync.remove_ingestion_item": "acquisition worker, fenced by its item lease",
    "email_sync.dead_letter_item_integration_ids": "health evaluator: integration ids only",
    "email_sync.dead_letter_attachment_integration_ids": "health evaluator: integration ids only",
    "email_sync.get_sync_state": "ingestion coordinator, keyed by a leased integration",
    "email_sync.all_states": "ingestion health evaluator",
    "email_sync.folders_refreshed_at": "discovery worker, keyed by a leased integration",
    "email_sync.mark_folders_refreshed": "discovery worker, keyed by a leased integration",
    "email_sync.folders_for_integration": "discovery worker, keyed by a leased integration",
    "email_sync.folder_ids": "discovery worker, keyed by a leased integration",
    "email_sync.upsert_folders": "discovery worker, keyed by a leased integration",
    "email_sync.delete_folder": "discovery worker, keyed by a leased integration",
    "email_sync.get_integration_by_id": "discovery worker, keyed by a leased integration",
    "email_sync.integration_statuses": "health evaluator: integration ids and statuses only",
    "email_sync.active_calendar_integrations": "calendar mirror floor fan-out over every active calendar",
    "emails.acquisition_context": "attachment worker, keyed by a claimed attachment's email",
    "attachments.store_result": "attachment worker, fenced by its own lock (locked_by)",
    "emails.email_is_claimable": "claim predicate probe, keyed by email id",
    "emails.get_for_extraction": "extraction worker, keyed by a claimed email",
    "emails.request_poll": "ingestion nudge, keyed by integration",
    "events.commit_email_extraction": "extraction worker; the owner is the claimed email's",
    "events.source_email_dates": "extraction worker, keyed by event sources it already read",
    "events.sources_with_emails": "extraction worker, keyed by event sources it already read",
    "events.mark_email_status": "extraction worker, keyed by its claimed email",
    "events.email_identity_context": "extraction worker, keyed by its claimed email",
    "events.email_calendar_components": "extraction worker, keyed by its claimed email",
    "events.email_has_component_method": "extraction worker, keyed by its claimed email",
    "events.email_outcome": "late-match relabel, keyed by sources of the user's retired event",
    "events.event_owner": "owner lookup only; every read after it is scoped by the owner it returns",
    # health and observability: counts across users, no row leaves
    "health.health_work_state": "health roll-up counts every user's work",
    "health.pending_email_metrics": "/health gauges: a count and an age",
    "integrations.count_active_mailboxes": "/health/egress divisor: a count",
    # operational incidents and ledgers are operator records, not user data
    "ops.raise_incident": "operator incident ledger",
    "ops.record_graph_failure": "Graph failure ledger, keyed by integration",
    "ops.graph_failures_for_run": "Graph failure ledger, keyed by sync run",
    # OAuth state rows are keyed by the unguessable state token
    "integrations.consume_oauth_state": "keyed by the one-time state token",
    "integrations.delete_expired_oauth_states": "expiry sweep",
    # account administration (operator and auth flows, keyed by account)
    "accounts.get_account_by_email": "sign-in looks the account up by email",
    "accounts.rotate_refresh_token": "keyed by the refresh token's hash",
    "accounts.session_for_refresh_token": "keyed by the refresh token's hash",
    "accounts.session_is_active": "keyed by the session id from a verified token",
    "demo.seed_demo": "CI/operator tool keyed by an account's email; refuses a used account",
}


def _module_names() -> list[str]:
    names = sorted(p.stem for p in DB_PACKAGE.glob("*.py") if p.stem not in SKIP_MODULES)
    assert names, f"no data-layer modules found under {DB_PACKAGE}"
    return names


def _user_owned_tables(db) -> set[str]:
    tables = {
        r[0] for r in db.query("SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%'")
    }
    owned = {"accounts", "users"}
    for table in tables:
        columns = {r[1] for r in db.query(f"PRAGMA table_info({table})")}
        if "user_id" in columns:
            owned.add(table)
    return owned


def _top_level(tree: ast.Module) -> dict[str, ast.AST]:
    out: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out[node.name] = node
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name):
                    out[target.id] = node
    return out


def _closure_strings(name: str, top: dict[str, ast.AST]) -> str:
    """Every string literal in ``name`` and the module-level names it reaches."""
    seen: set[str] = set()
    pending = [name]
    parts: list[str] = []
    while pending:
        current = pending.pop()
        if current in seen or current not in top:
            continue
        seen.add(current)
        for node in ast.walk(top[current]):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                parts.append(node.value)
            elif isinstance(node, ast.Name) and node.id in top and node.id not in seen:
                # Public functions are checked on their own; follow only the
                # private helpers and constants this function relies on.
                if node.id.startswith("_") or node.id.isupper():
                    pending.append(node.id)
    return "\n".join(parts)


def _tables_named(sql: str, tables: set[str]) -> set[str]:
    found = set()
    for table in tables:
        if re.search(rf"\b(FROM|JOIN|INTO|UPDATE)\s+{re.escape(table)}\b", sql, re.IGNORECASE):
            found.add(table)
    return found


def _public_functions(module: str) -> list[tuple[str, ast.FunctionDef, dict[str, ast.AST]]]:
    path = DB_PACKAGE / f"{module}.py"
    tree = ast.parse(path.read_text(), filename=str(path))
    top = _top_level(tree)
    imported = importlib.import_module(f"selko.db.{module}")
    out = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            if getattr(imported, node.name, None) is not None:
                out.append((node.name, node, top))
    return out


def _params(node: ast.FunctionDef) -> set[str]:
    args = node.args
    return {a.arg for a in (*args.posonlyargs, *args.args, *args.kwonlyargs)}


def _service_wide(module: str, name: str) -> bool:
    return (
        f"{module}.{name}" in SERVICE_WIDE
        or name.startswith(SERVICE_WIDE_PREFIXES)
        or any(part in name for part in SERVICE_WIDE_SUBSTRINGS)
    )


def test_every_function_touching_a_user_owned_table_takes_user_id(db):
    owned = _user_owned_tables(db)
    assert {"integrations", "emails", "events", "accounts"} <= owned, owned

    checked = 0
    missing: list[str] = []
    for module in _module_names():
        for name, node, top in _public_functions(module):
            touched = _tables_named(_closure_strings(name, top), owned)
            if not touched:
                continue
            checked += 1
            if _params(node) & OWNER_PARAMS or _service_wide(module, name):
                continue
            missing.append(f"selko.db.{module}.{name} touches {sorted(touched)} without user_id")

    # The scan must find real functions, or it proves nothing.
    assert checked >= 50, f"only {checked} data functions were found; the scan is broken"
    assert not missing, "\n".join(missing)


def test_the_allowlist_names_only_existing_functions():
    stale = []
    for entry in SERVICE_WIDE:
        module, name = entry.split(".", 1)
        if not hasattr(importlib.import_module(f"selko.db.{module}"), name):
            stale.append(entry)
    assert not stale, f"SERVICE_WIDE names functions that no longer exist: {stale}"


def test_the_scan_can_fail(db):
    """A function reading a user-owned table without user_id is caught."""
    source = (
        "def leaky(db, integration_id):\n"
        "    return db.query('SELECT * FROM integrations WHERE id = ?', (integration_id,))\n"
    )
    tree = ast.parse(source)
    top = _top_level(tree)
    node = top["leaky"]
    touched = _tables_named(_closure_strings("leaky", top), _user_owned_tables(db))
    assert touched == {"integrations"}
    assert not (_params(node) & OWNER_PARAMS)
    assert not _service_wide("integrations", "leaky")


@pytest.mark.parametrize("module", ["integrations", "recovery", "health", "quotas", "ops"])
def test_owned_modules_are_scanned(module):
    assert module in _module_names()
    assert _public_functions(module), f"selko.db.{module} has no public functions"
