"""Selko runs on one SQLite file: no module may reach Supabase or Postgres.

Every import is found by walking the AST, so an import inside a function or
behind TYPE_CHECKING counts too. The importer (selko_import, outside the
package) is the one place a Postgres driver is allowed: it reads the old
database once, at cutover.

"""

from __future__ import annotations

import ast
from pathlib import Path

PACKAGE = Path(__file__).resolve().parents[1] / "selko"
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
    assert len(list(PACKAGE.rglob("*.py"))) > 100


def test_the_check_sees_imports_inside_functions(tmp_path, monkeypatch):
    module = tmp_path / "selko" / "late.py"
    module.parent.mkdir()
    module.write_text("def f():\n    import asyncpg\n    from supabase import create_client\n")
    monkeypatch.setattr(__import__(__name__, fromlist=["PACKAGE"]), "PACKAGE", module.parent)
    assert _offenders() == {"late.py": {"asyncpg", "supabase"}}
