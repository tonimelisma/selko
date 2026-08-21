#!/usr/bin/env bash
set -euo pipefail

# Generate the execution-order table from spec acceptance metadata and local
# evidence manifests. Status text is deliberately not stored in front matter:
# missing evidence is reported as missing evidence.

ROOT_DIR="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
README_PATH="${SPEC_STATUS_README:-$ROOT_DIR/docs/specs/README.md}"
EVIDENCE_DIR="${SPEC_STATUS_EVIDENCE_DIR:-$ROOT_DIR/.verify}"

if [[ "${1:-}" == "--check" ]]; then
  CHECK_ONLY=1
else
  CHECK_ONLY=0
fi

export SPEC_STATUS_ROOT="$ROOT_DIR"
export SPEC_STATUS_README_PATH="$README_PATH"
export SPEC_STATUS_EVIDENCE_PATH="$EVIDENCE_DIR"
export SPEC_STATUS_CHECK_ONLY="$CHECK_ONLY"

python3 - <<'PY'
from __future__ import annotations

import json
import os
import sys
import tempfile
import tomllib
from pathlib import Path


root = Path(os.environ["SPEC_STATUS_ROOT"])
readme_path = Path(os.environ["SPEC_STATUS_README_PATH"])
evidence_path = Path(os.environ["SPEC_STATUS_EVIDENCE_PATH"])
check_only = os.environ["SPEC_STATUS_CHECK_ONLY"] == "1"


def load_spec(path: Path) -> dict:
    text = path.read_text()
    if not text.startswith("+++\n"):
        raise SystemExit(f"{path}: missing TOML front matter")
    end = text.find("\n+++\n", 4)
    if end < 0:
        raise SystemExit(f"{path}: unterminated TOML front matter")
    metadata = tomllib.loads(text[4:end])
    metadata["path"] = path
    return metadata


specs = [
    load_spec(path)
    for path in sorted((root / "docs/specs").glob("*.md"))
    if path.name not in {"README.md"}
]
if len({spec["spec_id"] for spec in specs}) != len(specs):
    raise SystemExit("spec front matter contains duplicate spec_id values")

manifests = []
if evidence_path.exists():
    for path in sorted(evidence_path.glob("*.json")):
        try:
            data = json.loads(path.read_text())
        except (OSError, json.JSONDecodeError) as exc:
            raise SystemExit(f"cannot read evidence manifest {path}: {exc}") from exc
        if data.get("status") == "passed":
            manifests.append(data)

passed_tests = {
    node
    for manifest in manifests
    for node in manifest.get("pytest", {}).get("passed_nodes", [])
}
health_assertions = {
    assertion
    for manifest in manifests
    for assertion in manifest.get("health_assertions", [])
}
drills = {
    drill
    for manifest in manifests
    for drill in manifest.get("drills", [])
}


def criterion_status(values: list[str], evidence: set[str]) -> tuple[int, int]:
    return sum(value in evidence for value in values), len(values)


def status_for(spec: dict) -> str:
    tests_ok, tests_total = criterion_status(spec.get("tests", []), passed_tests)
    health_ok, health_total = criterion_status(spec.get("health", []), health_assertions)
    drills_ok, drills_total = criterion_status(spec.get("drills", []), drills)
    proven = tests_ok + health_ok + drills_ok
    total = tests_total + health_total + drills_total
    if total == 0:
        return "No executable acceptance criteria declared"
    detail = (
        f"tests {tests_ok}/{tests_total}; "
        f"health {health_ok}/{health_total}; "
        f"drills {drills_ok}/{drills_total}"
    )
    if proven == total:
        return f"Verified by evidence ({detail})"
    if proven:
        return f"Partial evidence ({detail})"
    return f"Evidence pending ({detail})"


listed = sorted(
    (spec for spec in specs if spec.get("readme_order") is not None),
    key=lambda spec: spec["readme_order"],
)
if [spec["readme_order"] for spec in listed] != sorted(spec["readme_order"] for spec in listed):
    raise SystemExit("spec readme_order values are not sortable")

table = [
    "| # | Plan | Increments | Status | Gate to start |",
    "|---|---|---|---|---|",
]
for spec in listed:
    display_order = spec.get("display_order", str(spec["readme_order"]))
    table.append(
        f"| {display_order} | [{spec['title']}]({spec['path'].name}) | "
        f"{spec['increments']} | {status_for(spec)} | {spec['gate']} |"
    )

readme = readme_path.read_text()
lines = readme.splitlines()
try:
    execution_index = lines.index("## Execution order")
except ValueError as exc:
    raise SystemExit(f"{readme_path}: missing Execution order heading") from exc
table_start = next(
    index for index in range(execution_index + 1, len(lines)) if lines[index].startswith("| # | Plan |")
)
table_end = next(
    index for index in range(table_start, len(lines)) if index > table_start and lines[index].startswith("### ")
)
replacement = lines[:table_start] + table + [""] + lines[table_end:]
generated = "\n".join(replacement) + "\n"

if check_only:
    if generated != readme:
        print(f"ERROR: {readme_path} is not generated from spec evidence", file=sys.stderr)
        with tempfile.NamedTemporaryFile("w", suffix=".md", delete=False) as handle:
            handle.write(generated)
            generated_path = handle.name
        print(f"Generated output: {generated_path}", file=sys.stderr)
        raise SystemExit(1)
else:
    readme_path.write_text(generated)
    print(f"Generated {readme_path}")
PY
