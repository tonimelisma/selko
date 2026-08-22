#!/usr/bin/env python3
"""Summarise .verify/ledger.jsonl: what each lane costs and what it has caught.

The point of the ledger is to make verification subject to evidence rather than
belief. For each lane it answers:

  yield  -- how many times this lane has actually failed, i.e. caught something
  cost   -- total wall-clock seconds spent executing it
  saved  -- how many times it was reused instead of re-run

A lane with zero yield over many runs and a high cost is not protecting us; it
is a tax. A lane that fails constantly may be flaky rather than valuable. Both
judgements need history, which is why every run appends here.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER_PATH = ROOT / ".verify" / "ledger.jsonl"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ledger", type=Path, default=LEDGER_PATH)
    parser.add_argument("--last", type=int, default=0, help="only the N most recent records")
    args = parser.parse_args()

    if not args.ledger.exists():
        print(f"No ledger yet at {args.ledger}. Run ./scripts/verify-lanes.py first.")
        return 0

    records = []
    for line in args.ledger.read_text().splitlines():
        if line.strip():
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if args.last:
        records = records[-args.last :]

    stats: dict[str, dict] = defaultdict(
        lambda: {
            "runs": 0,
            "executed": 0,
            "reused": 0,
            "failures": 0,
            "seconds": 0.0,
            "last_failure": None,
            "gate": "",
        }
    )
    for record in records:
        entry = stats[record["lane"]]
        entry["gate"] = record.get("gate", "")
        entry["runs"] += 1
        if record.get("executed"):
            entry["executed"] += 1
            entry["seconds"] += float(record.get("duration_seconds", 0.0))
        else:
            entry["reused"] += 1
        if record.get("status") != "pass":
            entry["failures"] += 1
            entry["last_failure"] = record.get("timestamp")

    print(f"{'LANE':<18}{'GATE':<8}{'RUNS':>6}{'RUN':>6}{'REUSE':>7}{'CAUGHT':>8}{'MINUTES':>9}  LAST FAILURE")
    total_seconds = 0.0
    for name, entry in sorted(stats.items(), key=lambda kv: -kv[1]["seconds"]):
        total_seconds += entry["seconds"]
        last = (entry["last_failure"] or "never")[:19]
        print(
            f"{name:<18}{entry['gate']:<8}{entry['runs']:>6}{entry['executed']:>6}"
            f"{entry['reused']:>7}{entry['failures']:>8}{entry['seconds'] / 60:>9.1f}  {last}"
        )
    print()
    print(f"total executed time: {total_seconds / 60:.1f} min across {len(records)} lane records")

    dead_weight = [
        name
        for name, entry in stats.items()
        if entry["failures"] == 0 and entry["executed"] >= 10 and entry["seconds"] > 300
    ]
    if dead_weight:
        print()
        print("Lanes that have never caught anything despite real cost — review:")
        for name in dead_weight:
            print(f"  {name}: {stats[name]['seconds'] / 60:.1f} min, 0 failures")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
