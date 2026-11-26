"""Selko runs on one SQLite file: nothing may reach Supabase or Postgres.

Every import is found by walking the AST, so an import inside a function or
behind TYPE_CHECKING counts too. The one-time importer that carried the old
Postgres data across was removed after the cutover (2026-11-26); its result
lives on as backend/tests/fixtures/imported_from_postgres.sql. No Python file
in the repository and no locked package may bring a hosted-database client
back.
"""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "selko"
ROOT = Path(__file__).resolve().parents[2]
# Not Selko: the unmaintained native apps, and installed or generated trees.
SKIPPED = {"legacy", "node_modules", ".venv", ".git", ".verify", "build", ".svelte-kit"}
FORBIDDEN = {"supabase", "postgrest", "asyncpg", "gotrue", "realtime", "storage3", "psycopg", "psycopg2"}



def _offenders() -> dict[str, set[str]]:
    found: dict[str, set[str]] = {}
    for path in sorted(PACKAGE.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names.add(node.module.split(".")[0])
        hit = names & FORBIDDEN
        if hit:
            found[path.relative_to(PACKAGE).as_posix()] = hit
    return found


def test_no_module_imports_a_hosted_database_client():
    found = {m: sorted(h) for m, h in _offenders().items()}
    assert not found, f"these modules import a hosted-database client: {found}"


def test_the_check_scans_the_package():
    assert len(list(PACKAGE.rglob("*.py"))) > 50


def test_the_check_sees_imports_inside_functions(tmp_path, monkeypatch):
    module = tmp_path / "selko" / "late.py"
    module.parent.mkdir()
    module.write_text("def f():\n    import asyncpg\n    from supabase import create_client\n")
    monkeypatch.setattr(__import__(__name__, fromlist=["PACKAGE"]), "PACKAGE", module.parent)
    assert _offenders() == {"late.py": {"asyncpg", "supabase"}}


def test_no_python_file_in_the_repository_imports_one():
    found = {}
    for path in sorted(ROOT.rglob("*.py")):
        if SKIPPED & set(path.relative_to(ROOT).parts):
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                names.add(node.module.split(".")[0])
        if names & FORBIDDEN:
            found[path.relative_to(ROOT).as_posix()] = sorted(names & FORBIDDEN)
    # This file names the clients as data, never as imports.
    assert not found, f"these files import a hosted-database client: {found}"


def test_no_locked_package_is_a_hosted_database_client():
    import tomllib

    lock = tomllib.loads((ROOT / "uv.lock").read_text(encoding="utf-8"))
    names = {package["name"].replace("-", "_") for package in lock["package"]}
    assert len(names) > 20  # the lockfile was read
    assert not names & (FORBIDDEN | {"psycopg_binary", "supabase_auth", "supabase_functions"}), names & FORBIDDEN
