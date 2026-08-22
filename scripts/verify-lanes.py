#!/usr/bin/env python3
"""Lane-based verification runner with input fingerprinting and an audit ledger.

Two problems this solves.

Idempotency: a lane whose declared inputs have not changed since it last passed
is reused, not re-run. One broken lane no longer costs a full-suite re-run --
fix it, run again, and only that lane executes. Fingerprints hash file contents,
not mtimes, so a touched-but-unchanged file does not invalidate a lane and a
reverted edit correctly restores the cached result.

Auditability: every lane execution appends a record to .verify/ledger.jsonl with
its duration, outcome, and whether it was executed or reused. scripts/
verify-report.py turns that history into the question we actually care about --
which lanes have ever caught anything, and what each one costs us. A lane that
has never failed across many runs and costs minutes is a candidate for removal;
without this ledger that judgement is guesswork.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
import tomllib
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# Overridable so tests (and parallel CI jobs) get their own cache and ledger
# instead of racing the repository's.
VERIFY_DIR = Path(os.environ.get("SELKO_VERIFY_DIR", ROOT / ".verify"))
STATE_PATH = VERIFY_DIR / "lane-state.json"
LEDGER_PATH = VERIFY_DIR / "ledger.jsonl"
LOG_DIR = VERIFY_DIR / "logs"
RUN_DIR = VERIFY_DIR / "runs"
MAX_HASHED_BYTES = 5 * 1024 * 1024


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_lanes(path: Path) -> dict[str, dict]:
    with path.open("rb") as handle:
        return tomllib.load(handle)["lanes"]


def _iter_input_files(patterns: list[str]) -> list[Path]:
    seen: set[Path] = set()
    for pattern in patterns:
        for match in ROOT.glob(pattern):
            if match.is_file():
                seen.add(match)
    return sorted(seen)


def fingerprint(lane: dict) -> tuple[str, int]:
    """Hash a lane's command and the content of every file it declares as input.

    Content, not mtime: `git checkout` and editor saves both change mtimes
    without changing what the lane would verify, and a timestamp-based cache
    re-runs the suite for neither reason.

    The command is hashed too. A lane whose command changes is a different
    check, even against identical inputs -- without this, fixing a lane's
    command would reuse the verdict from the command it replaced, reporting
    green for something that never ran.
    """
    patterns = lane["inputs"]
    digest = hashlib.blake2b(digest_size=16)
    digest.update(b"command:")
    digest.update(lane["command"].encode())
    digest.update(b"\ninputs:")
    count = 0
    for path in _iter_input_files(patterns):
        rel = path.relative_to(ROOT).as_posix()
        digest.update(rel.encode())
        try:
            size = path.stat().st_size
            if size > MAX_HASHED_BYTES:
                digest.update(f":size:{size}".encode())
            else:
                digest.update(path.read_bytes())
        except OSError as exc:
            digest.update(f":unreadable:{exc.errno}".encode())
        count += 1
    return digest.hexdigest(), count


def load_state() -> dict:
    if STATE_PATH.exists():
        try:
            return json.loads(STATE_PATH.read_text())
        except json.JSONDecodeError:
            return {}
    return {}


def save_state(state: dict) -> None:
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def append_ledger(record: dict) -> None:
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)
    with LEDGER_PATH.open("a") as handle:
        handle.write(json.dumps(record, sort_keys=True) + "\n")


def git_sha() -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, capture_output=True, text=True
    )
    return result.stdout.strip() or "unknown"


def run_lane(name: str, lane: dict, run_id: str) -> dict:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    log_path = LOG_DIR / f"{run_id}-{name}.log"
    started = time.monotonic()
    with log_path.open("w") as log:
        completed = subprocess.run(
            lane["command"], shell=True, cwd=ROOT, stdout=log, stderr=subprocess.STDOUT
        )
    duration = round(time.monotonic() - started, 2)
    return {
        "exit_code": completed.returncode,
        "duration_seconds": duration,
        "log": _display_path(log_path),
    }


def _display_path(path: Path) -> str:
    """Repo-relative when inside the repo, absolute otherwise.

    SELKO_VERIFY_DIR may point outside the repository (tests, CI scratch), and
    an unconditional relative_to() raises there.
    """
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _tail(path: Path, lines: int = 15) -> list[str]:
    try:
        return path.read_text(errors="replace").splitlines()[-lines:]
    except OSError:
        return []


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--gate",
        default="prod",
        choices=["prod", "mobile", "all"],
        help="prod blocks a production deploy; mobile ships through an app store",
    )
    parser.add_argument("--only", action="append", default=[], help="run just this lane")
    parser.add_argument(
        "--force", action="store_true", help="ignore cached results and re-run everything"
    )
    parser.add_argument(
        "--lanes", type=Path, default=ROOT / "scripts" / "lanes.toml"
    )
    args = parser.parse_args()

    lanes = load_lanes(args.lanes)
    if args.only:
        unknown = [name for name in args.only if name not in lanes]
        if unknown:
            print(f"Unknown lane(s): {', '.join(unknown)}", file=sys.stderr)
            return 2
        selected = {name: lanes[name] for name in args.only}
    else:
        selected = {
            name: lane
            for name, lane in lanes.items()
            if args.gate == "all" or lane["gate"] == args.gate
        }

    state = load_state()
    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    sha = git_sha()
    results: list[dict] = []
    run_started = time.monotonic()

    for name, lane in selected.items():
        print(f"==> {name}: ", end="", flush=True)
        fp, file_count = fingerprint(lane)
        lane_state = state.get(name, {})
        # Results are keyed by fingerprint, not just "the last run". Storing
        # only the last result meant reverting an edit re-ran the lane even
        # though that exact input set had already passed -- which defeats the
        # cache during the fix/revert cycles where it matters most.
        previous = lane_state.get("results", {}).get(fp, {})
        reusable = not args.force and previous.get("status") == "pass"

        if reusable:
            record = {
                "lane": name,
                "gate": lane["gate"],
                "status": "pass",
                "executed": False,
                "reason": "inputs unchanged since last pass",
                "duration_seconds": 0.0,
                "cached_from": previous.get("finished_at"),
                "fingerprint": fp,
                "input_files": file_count,
                "run_id": run_id,
                "git_sha": sha,
                "timestamp": _now(),
            }
            print(f"reused (unchanged, {file_count} files)")
        else:
            outcome = run_lane(name, lane, run_id)
            status = "pass" if outcome["exit_code"] == 0 else "fail"
            record = {
                "lane": name,
                "gate": lane["gate"],
                "status": status,
                "executed": True,
                "reason": "forced" if args.force else "inputs changed or last run not green",
                "duration_seconds": outcome["duration_seconds"],
                "exit_code": outcome["exit_code"],
                "log": outcome["log"],
                "fingerprint": fp,
                "input_files": file_count,
                "run_id": run_id,
                "git_sha": sha,
                "timestamp": _now(),
            }
            print(f"{status} in {outcome['duration_seconds']}s")

        results.append(record)
        append_ledger(record)
        results_by_fp = lane_state.get("results", {})
        results_by_fp[fp] = {
            "status": record["status"],
            "finished_at": record["timestamp"],
            "duration_seconds": record["duration_seconds"],
        }
        # Bound the history so the state file cannot grow without limit.
        if len(results_by_fp) > 20:
            oldest = sorted(results_by_fp.items(), key=lambda kv: kv[1]["finished_at"])
            for stale_fp, _ in oldest[: len(results_by_fp) - 20]:
                results_by_fp.pop(stale_fp, None)
        state[name] = {
            "last_fingerprint": fp,
            "last_status": record["status"],
            "results": results_by_fp,
        }
        save_state(state)

    total = round(time.monotonic() - run_started, 2)
    failed = [r for r in results if r["status"] != "pass"]
    executed = [r for r in results if r["executed"]]
    reused = [r for r in results if not r["executed"]]

    RUN_DIR.mkdir(parents=True, exist_ok=True)
    summary = {
        "run_id": run_id,
        "git_sha": sha,
        "gate": args.gate,
        "total_seconds": total,
        "executed": len(executed),
        "reused": len(reused),
        "failed": [r["lane"] for r in failed],
        "lanes": results,
    }
    (RUN_DIR / f"{run_id}.json").write_text(json.dumps(summary, indent=2) + "\n")

    print()
    print(f"{'LANE':<18}{'GATE':<8}{'STATUS':<8}{'TIME':>9}  SOURCE")
    for record in results:
        source = "executed" if record["executed"] else "cached"
        print(
            f"{record['lane']:<18}{record['gate']:<8}{record['status']:<8}"
            f"{record['duration_seconds']:>8.1f}s  {source}"
        )
    print()
    print(
        f"gate={args.gate}  executed={len(executed)}  reused={len(reused)}  "
        f"wall={total}s  run={run_id}"
    )

    for record in failed:
        print()
        print(f"--- {record['lane']} failed; last lines of {record.get('log')}:")
        for line in _tail(Path(record["log"]) if Path(record["log"]).is_absolute() else ROOT / record["log"]):
            print(f"    {line}")

    if failed:
        print()
        print(
            "Re-run after fixing; passing lanes are cached, so only the failed "
            f"lane(s) will execute: ./scripts/verify-lanes.py --gate {args.gate}"
        )
        return 1

    print(f"ALL {args.gate.upper()} LANES GREEN")
    return 0


if __name__ == "__main__":
    sys.exit(main())
