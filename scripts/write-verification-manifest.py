#!/usr/bin/env python3
"""Write and validate the evidence manifest for a local verification gate."""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
import xml.etree.ElementTree as ET
from pathlib import Path


def _node_id(testcase: ET.Element) -> str:
    classname = testcase.attrib.get("classname", "")
    name = testcase.attrib.get("name", "")
    module, separator, owner = classname.rpartition(".")
    if not separator:
        return f"{classname}::{name}"
    return f"{module.replace('.', '/')}.py::{owner}::{name}"


def _collect_xml(paths: list[Path]) -> dict[str, object]:
    totals = {"tests": 0, "passed": 0, "failed": 0, "errors": 0, "skipped": 0}
    skipped: list[dict[str, str]] = []
    passed_nodes: list[str] = []
    # A red gate has to say WHAT failed. Without this the manifest recorded only
    # passed_nodes, so diagnosing a failure meant re-running the suite and
    # hoping to reproduce it -- which for an order- or network-dependent test is
    # exactly what does not reproduce. The seed is already recorded; the failing
    # node id is the other half of making a failure investigable after the fact.
    failed_nodes: list[dict[str, str]] = []
    suites: list[dict[str, object]] = []
    for path in paths:
        if not path.exists():
            continue
        root = ET.parse(path).getroot()
        cases = list(root.iter("testcase"))
        suite_counts = {key: 0 for key in totals if key != "tests"}
        for testcase in cases:
            totals["tests"] += 1
            failure = testcase.find("failure")
            error = testcase.find("error")
            skip = testcase.find("skipped")
            if failure is not None:
                totals["failed"] += 1
                suite_counts["failed"] += 1
                failed_nodes.append({
                    "nodeid": _node_id(testcase),
                    "kind": "failure",
                    # First line only: enough to identify, never a payload dump.
                    "message": (failure.attrib.get("message") or "").splitlines()[:1][0]
                    if failure.attrib.get("message") else "",
                })
            elif error is not None:
                totals["errors"] += 1
                suite_counts["errors"] += 1
                failed_nodes.append({
                    "nodeid": _node_id(testcase),
                    "kind": "error",
                    "message": (error.attrib.get("message") or "").splitlines()[:1][0]
                    if error.attrib.get("message") else "",
                })
            elif skip is not None:
                totals["skipped"] += 1
                suite_counts["skipped"] += 1
                skipped.append(
                    {
                        "nodeid": _node_id(testcase),
                        "reason": skip.attrib.get("message") or (skip.text or "").strip(),
                    }
                )
            else:
                totals["passed"] += 1
                suite_counts["passed"] += 1
                passed_nodes.append(_node_id(testcase))
        suites.append({"file": str(path), **suite_counts, "tests": len(cases)})
    return {
        **totals,
        "skips": skipped,
        "passed_nodes": passed_nodes,
        "failed_nodes": failed_nodes,
        "suites": suites,
    }


def _load_budget(path: Path) -> dict[str, dict[str, str]]:
    raw = tomllib.loads(path.read_text())
    entries = raw.get("skip", [])
    return {entry["nodeid"]: entry for entry in entries}


def _validate_skips(skips: list[dict[str, str]], budget: dict[str, dict[str, str]]) -> list[str]:
    problems: list[str] = []
    seen: set[str] = set()
    for item in skips:
        nodeid = item["nodeid"]
        seen.add(nodeid)
        entry = budget.get(nodeid)
        if entry is None:
            problems.append(f"skip is outside budget: {nodeid}")
            continue
        expected = entry.get("reason", "")
        if expected and expected not in item["reason"]:
            problems.append(
                f"skip reason changed for {nodeid}: expected {expected!r}, got {item['reason']!r}"
            )
    # A budget entry is PERMISSION to skip, not a requirement to.
    #
    # These entries name a test that skips when its precondition is missing --
    # no LLM key, no live Gmail token, no real Google Calendar. When the
    # precondition is satisfied the test runs, which is strictly better, and
    # treating that as a gate failure punishes exactly the improvement the
    # budget exists to track. Observed: refreshing the Gmail token made three
    # real-Gmail tests execute and pass, and the gate reported "failed" on a
    # run with 1364 passed and 0 failed.
    #
    # Entries that go permanently unobserved are still worth pruning; they are
    # reported so they cannot rot silently, but they do not fail the gate.
    unobserved = sorted(set(budget) - seen)
    if unobserved:
        print(
            "NOTE: budgeted skips that did not skip this run (their precondition "
            "was available, so they ran). Prune the entry if that is now permanent:",
            file=sys.stderr,
        )
        for nodeid in unobserved:
            print(f"  {nodeid}", file=sys.stderr)
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--skip-budget", type=Path, required=True)
    parser.add_argument("--status", type=int, required=True)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--dirty-tree", action="store_true")
    parser.add_argument("--schema-hash", default=None)
    parser.add_argument("--seed", required=True)
    parser.add_argument("--accepted-degradation", action="append", default=[])
    parser.add_argument("junit", type=Path, nargs="*")
    args = parser.parse_args()

    pytest = _collect_xml(args.junit)
    budget = _load_budget(args.skip_budget)
    evidence_files = [path for path in args.junit if path.exists()]
    problems = _validate_skips(pytest["skips"], budget) if evidence_files else []
    if problems:
        for problem in problems:
            print(f"ERROR: {problem}", file=sys.stderr)

    manifest = {
        "gate": "backend",
        "status": "passed" if args.status == 0 and not problems else "failed",
        "exit_code": args.status if args.status else (1 if problems else 0),
        "git_sha": args.git_sha,
        "dirty_tree": args.dirty_tree,
        "schema_hash": args.schema_hash,
        "pytest_randomly_seed": args.seed,
        "accepted_degradations": args.accepted_degradation,
        "pytest": pytest,
        "skip_budget": {
            "path": str(args.skip_budget),
            "valid": not problems,
            "problems": problems,
        },
    }
    args.manifest.parent.mkdir(parents=True, exist_ok=True)
    args.manifest.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    if problems:
        return 1
    return args.status


if __name__ == "__main__":
    raise SystemExit(main())
