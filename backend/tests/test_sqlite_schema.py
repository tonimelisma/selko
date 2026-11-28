"""The applied SQLite schema's enumerated CHECK domains, and the literals the code writes into them.

Successors of integration/test_schema_contract.py's
`test_check_constraint_domains_are_pinned` and
`test_status_literals_in_python_are_permitted` (05-verification §A.7 item a/b).
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from tests.schema_domains import EXPECTED_CHECK_DOMAINS

SELKO = Path(__file__).resolve().parents[1] / "selko"
_IN_LIST = re.compile(r"(\w+) IN \(((?:'[^']*'(?:, )?)+)\)")


def _actual_domains(db) -> dict[tuple[str, str], set[str]]:
    actual: dict[tuple[str, str], set[str]] = {}
    for row in db.query("SELECT name, sql FROM sqlite_master WHERE type = 'table' AND sql IS NOT NULL"):
        for column, values in _IN_LIST.findall(row["sql"]):
            actual.setdefault((row["name"], column), set()).update(re.findall(r"'([^']*)'", values))
    return actual


# Validates: SEL-623
def test_check_constraint_domains_are_pinned(db):
    actual = _actual_domains(db)

    assert len(actual) > 30, "the parser found almost no CHECK domains: it is not reading the schema"
    assert set(actual) == set(EXPECTED_CHECK_DOMAINS), (
        f"missing={sorted(set(EXPECTED_CHECK_DOMAINS) - set(actual))}, "
        f"unexpected={sorted(set(actual) - set(EXPECTED_CHECK_DOMAINS))}"
    )
    assert actual == EXPECTED_CHECK_DOMAINS


# The columns whose values the data layer's SQL writes or compares as literals.
# Each literal must be in that column's domain (in some table that has it). The
# Postgres-era check scanned supabase-py `.update({...})` dicts; all SQL now
# lives in `selko/db/`, so the SQL text is what is scanned.
_STATUS_KEYS = {"processing_status", "status", "acquisition_status", "ingestion_status",
                "review_status", "processing_outcome"}
_SQL_ASSIGN = re.compile(r"\b(" + "|".join(sorted(_STATUS_KEYS)) + r")\s*(?:=|<>|!=)\s*'([a-z_]+)'")
_SQL_IN = re.compile(r"\b(" + "|".join(sorted(_STATUS_KEYS)) + r")\s+(?:NOT\s+)?IN\s*\(((?:\s*'[a-z_]+'\s*,?)+)\)")


def _strings(tree: ast.AST):
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.value
        elif isinstance(node, ast.JoinedStr):
            yield "".join(v.value for v in node.values if isinstance(v, ast.Constant))


# Validates: SEL-623
def test_status_literals_in_python_are_permitted():
    allowed: dict[str, set[str]] = {}
    for (_, column), values in EXPECTED_CHECK_DOMAINS.items():
        allowed.setdefault(column, set()).update(values)

    files = sorted(p for p in (SELKO / "db").rglob("*.py") if "__pycache__" not in p.parts)
    assert files, "no data-layer modules found: the scan would pass vacuously"
    found: list[tuple[str, str, str]] = []
    for path in files:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for text in _strings(tree):
            for column, value in _SQL_ASSIGN.findall(text):
                found.append((path.name, column, value))
            for column, values in _SQL_IN.findall(text):
                found.extend((path.name, column, v) for v in re.findall(r"'([a-z_]+)'", values))

    assert len(found) > 20, "the scan found almost no status literals: it is not reading the code"
    violations = [f"{name}:{column}={value!r}" for name, column, value in found
                  if value not in allowed.get(column, set())]
    assert not violations, "status literals are outside their pinned domains: " + ", ".join(violations)
