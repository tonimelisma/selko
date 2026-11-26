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
import time
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


def _ledger(tmp_path):
    files = sorted((tmp_path / "verify" / "ledger").glob("*.jsonl"))
    return files, [json.loads(line) for f in files for line in f.read_text().splitlines() if line.strip()]


def test_every_execution_is_recorded_in_the_ledger(probe_file, tmp_path):
    lanes = _write_lanes(tmp_path, probe_file, "true")
    _run(lanes, tmp_path)

    files, after = _ledger(tmp_path)
    assert len(after) == 1
    record = after[-1]
    assert record["lane"] == "probe"
    assert "duration_seconds" in record
    assert "executed" in record
    # One file per run, named by it: two branches never append to the same file.
    assert [f.name for f in files] == [f"{record['run_id']}.jsonl"]


def test_each_run_writes_its_own_ledger_file_and_the_report_reads_them_all(probe_file, tmp_path):
    lanes = _write_lanes(tmp_path, probe_file, "false")  # failing: executes every time
    _run(lanes, tmp_path)
    time.sleep(1.1)  # run ids have one-second resolution
    _run(lanes, tmp_path)

    files, records = _ledger(tmp_path)
    assert len(files) == 2 and len(records) == 2
    report = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify-report.py"), "--ledger", str(tmp_path / "verify" / "ledger")],
        capture_output=True, text=True, check=True,
    )
    probe = next(line for line in report.stdout.splitlines() if line.startswith("probe"))
    assert probe.split()[2:6] == ["2", "2", "0", "2"], probe  # runs, executed, reused, caught


def test_an_unmet_precondition_is_red_not_skipped(probe_file, tmp_path):
    """A lane that cannot run has verified nothing, so it must report failure.

    The iOS lane depends on the backend API being up. When that dependency was
    undeclared, the lane's result silently depended on whether someone had
    started a server by hand -- reproducible for nobody.
    """
    lanes = tmp_path / "lanes.toml"
    lanes.write_text(
        "[lanes.probe]\n"
        'gate = "prod"\n'
        'description = "probe"\n'
        'command = "true"\n'
        f'inputs = ["{probe_file.relative_to(ROOT).as_posix()}"]\n'
        "[[lanes.probe.requires]]\n"
        'name = "impossible"\n'
        'check = "false"\n'
        'remedy = "cannot be satisfied"\n'
    )
    result = _run(lanes, tmp_path)
    assert result.returncode == 1, result.stdout
    assert "BLOCKED" in result.stdout, result.stdout
    assert "cannot be satisfied" in result.stdout, result.stdout


def test_a_met_precondition_lets_the_lane_run(probe_file, tmp_path):
    lanes = tmp_path / "lanes.toml"
    lanes.write_text(
        "[lanes.probe]\n"
        'gate = "prod"\n'
        'description = "probe"\n'
        'command = "true"\n'
        f'inputs = ["{probe_file.relative_to(ROOT).as_posix()}"]\n'
        "[[lanes.probe.requires]]\n"
        'name = "always true"\n'
        'check = "true"\n'
        'remedy = "n/a"\n'
    )
    result = _run(lanes, tmp_path)
    assert result.returncode == 0, result.stdout


def _lock_dir_for(checkout: Path) -> str:
    """Ask the runner where a checkout's lane locks live."""
    probe = (
        "import importlib.util, sys;"
        "spec = importlib.util.spec_from_file_location('vl', sys.argv[1]);"
        "m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m);"
        "print(m._lock_dir())"
    )
    result = subprocess.run(
        [sys.executable, "-c", probe, str(checkout / "scripts" / "verify-lanes.py")],
        capture_output=True, text=True, check=True,
        env={"PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"},
    )
    return result.stdout.strip()


def test_every_worktree_shares_one_lock(tmp_path):
    """The database, simulator and port a lane uses belong to the machine.

    Locks lived in each checkout's .verify/, so two sessions in two worktrees
    each started `supabase db reset` under the other's integration suite and
    both runs reported failures that meant nothing.
    """
    git = ["git", "-c", "user.email=t@example.com", "-c", "user.name=t"]
    main = tmp_path / "main"
    (main / "scripts").mkdir(parents=True)
    (main / "scripts" / "verify-lanes.py").write_text(RUNNER.read_text())
    subprocess.run(["git", "init", "-q", str(main)], check=True)
    subprocess.run([*git, "-C", str(main), "add", "."], check=True)
    subprocess.run([*git, "-C", str(main), "commit", "-qm", "init"], check=True)
    other = tmp_path / "other"
    subprocess.run(["git", "-C", str(main), "worktree", "add", "-q", str(other)], check=True)

    assert _lock_dir_for(main) == _lock_dir_for(other)
    assert _lock_dir_for(main).endswith("selko-verify-locks")


def _load_runner():
    import importlib.util

    spec = importlib.util.spec_from_file_location("verify_lanes_runner", RUNNER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_trailing_double_star_fingerprints_the_files_under_it(probe_file, tmp_path):
    """`dir/**` must see the files in dir on every Python version.

    Before Python 3.13, Path.glob("dir/**") yields directories only, which the
    runner discards. `frontend/src/**` therefore fingerprinted zero files on
    Python 3.12, and the frontend lane reused its last pass whatever changed.
    """
    runner = _load_runner()
    assert runner._glob_pattern("frontend/src/**") == "frontend/src/**/*"

    scratch_dir = probe_file.parent.relative_to(ROOT).as_posix()
    lanes = tmp_path / "lanes.toml"
    lanes.write_text(
        "[lanes.probe]\n"
        'gate = "prod"\n'
        'description = "probe"\n'
        'command = "true"\n'
        f'inputs = ["{scratch_dir}/**"]\n'
    )
    first = _run(lanes, tmp_path)
    assert "pass" in first.stdout, first.stdout

    probe_file.write_text("changed\n")
    second = _run(lanes, tmp_path)
    assert "reused" not in second.stdout.splitlines()[0], second.stdout


def test_an_input_pattern_that_matches_nothing_is_red(probe_file, tmp_path):
    """A declared input that does not exist silently leaves the fingerprint.

    The frontend lane declared tsconfig.json and tailwind.config.js, neither of
    which exists, so edits to the files that replaced them never invalidated it.
    """
    lanes = tmp_path / "lanes.toml"
    lanes.write_text(
        "[lanes.probe]\n"
        'gate = "prod"\n'
        'description = "probe"\n'
        'command = "true"\n'
        f'inputs = ["{probe_file.relative_to(ROOT).as_posix()}", "no/such/file.json"]\n'
    )
    result = _run(lanes, tmp_path)
    assert result.returncode == 1, result.stdout
    assert "no/such/file.json" in result.stdout, result.stdout
    assert "match no files" in result.stdout, result.stdout


def test_the_repository_lanes_declare_only_inputs_that_exist():
    runner = _load_runner()
    lanes = runner.load_lanes(ROOT / "scripts" / "lanes.toml")
    missing = {
        name: unmatched
        for name, lane in lanes.items()
        if (unmatched := runner.unmatched_inputs(lane))
    }
    assert missing == {}, f"scripts/lanes.toml names inputs that match nothing: {missing}"
