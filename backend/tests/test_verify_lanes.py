"""Contract tests for the lane runner's cache semantics.

The cache is the part that can silently make verification meaningless: if a lane
is reused when its inputs actually changed, the runner reports green for work it
never did. These tests pin the four behaviours that matter, because a caching
gate that is wrong is worse than no gate.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
RUNNER = ROOT / "scripts" / "verify-lanes.py"


def _write_lanes(tmp_path: Path, probe: Path, command: str) -> Path:
    lanes = tmp_path / "lanes.toml"
    lanes.write_text(
        "[lanes.probe]\n"
        'gate = "prod"\n'
        'description = "probe"\n'
        f'command = "{command}"\n'
        f'inputs = ["{probe.relative_to(ROOT).as_posix()}"]\n'
    )
    return lanes


def _run(lanes: Path, state_dir: Path) -> subprocess.CompletedProcess:
    # Each test gets its own cache and ledger; sharing the repository's made
    # these tests order-dependent, passing alone and failing in company.
    env = {
        "HOME": str(state_dir),
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "SELKO_VERIFY_DIR": str(state_dir / "verify"),
    }
    return subprocess.run(
        [sys.executable, str(RUNNER), "--lanes", str(lanes), "--only", "probe"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
    )


@pytest.fixture
def probe_file(request):
    """A real file inside the repo, since lane globs are repo-relative.

    Named per test so concurrent or reordered tests cannot glob each other's
    probe and invalidate one another's fingerprints.
    """
    scratch = ROOT / ".verify" / "pytest-scratch"
    scratch.mkdir(parents=True, exist_ok=True)
    probe = scratch / f"{request.node.name}.txt"
    probe.write_text("one\n")
    yield probe
    probe.unlink(missing_ok=True)


def test_unchanged_inputs_are_reused_and_changed_inputs_re_execute(probe_file, tmp_path):
    lanes = _write_lanes(tmp_path, probe_file, "true")

    first = _run(lanes, tmp_path)
    assert "pass" in first.stdout, first.stdout

    second = _run(lanes, tmp_path)
    assert "reused" in second.stdout, second.stdout

    probe_file.write_text("two\n")
    third = _run(lanes, tmp_path)
    assert "reused" not in third.stdout.splitlines()[0], third.stdout


def test_reverting_an_edit_restores_the_cached_result(probe_file, tmp_path):
    lanes = _write_lanes(tmp_path, probe_file, "true")
    _run(lanes, tmp_path)

    probe_file.write_text("changed\n")
    _run(lanes, tmp_path)

    # Results are keyed by fingerprint, not by "the last run", so returning to a
    # previously-verified input set must not force a re-run.
    probe_file.write_text("one\n")
    reverted = _run(lanes, tmp_path)
    assert "reused" in reverted.stdout.splitlines()[0], reverted.stdout


def test_a_failing_lane_is_never_cached_as_passing(probe_file, tmp_path):
    lanes = _write_lanes(tmp_path, probe_file, "exit 3")

    first = _run(lanes, tmp_path)
    assert first.returncode == 1, first.stdout

    # Same inputs, still failing: it must execute again rather than report the
    # cached outcome, otherwise a red lane would turn green by standing still.
    second = _run(lanes, tmp_path)
    assert second.returncode == 1, second.stdout
    assert "reused" not in second.stdout.splitlines()[0], second.stdout


def test_every_execution_is_recorded_in_the_ledger(probe_file, tmp_path):
    ledger = tmp_path / "verify" / "ledger.jsonl"

    lanes = _write_lanes(tmp_path, probe_file, "true")
    _run(lanes, tmp_path)

    after = [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()]
    assert len(after) == 1
    record = after[-1]
    assert record["lane"] == "probe"
    assert "duration_seconds" in record
    assert "executed" in record
