"""Regression tests for the safe-by-default eval-result retention script."""

import json
import subprocess
from pathlib import Path


SCRIPT = Path(__file__).parents[2] / "scripts" / "prune-eval-results.sh"


def _write_result(root: Path, prompt_hash: str, name: str, run_at: str) -> Path:
    path = root / "extract" / "provider_model_low" / "fixture" / f"result_{prompt_hash}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({
        "operation": "extract",
        "provider": "provider",
        "model": "model",
        "thinking": "low",
        "fixture_name": "fixture",
        "prompt_hash": prompt_hash,
        "run_at": run_at,
        "name": name,
    }))
    return path


def _run(root: Path, *args: str) -> subprocess.CompletedProcess:
    env = {
        "PATH": "/usr/bin:/bin:/opt/homebrew/bin",
        "EVAL_RESULTS_ROOT": str(root),
        "EVAL_CURRENT_PROMPT_HASHES": json.dumps({"extract": "current"}),
    }
    return subprocess.run(
        ["bash", str(SCRIPT), *args], capture_output=True, text=True, env=env, timeout=20
    )


def test_prune_defaults_to_dry_run(tmp_path):
    current = _write_result(tmp_path, "current123456", "current", "2026-08-01")
    recent = _write_result(tmp_path, "recent123456", "recent", "2026-07-15")
    old = _write_result(tmp_path, "old12345678", "old", "2026-07-01")

    result = _run(tmp_path, "--dry-run")

    assert result.returncode == 0
    assert "would delete" in result.stdout
    assert current.exists()
    assert recent.exists()
    assert old.exists()


def test_apply_keeps_current_and_one_superseded_hash(tmp_path):
    current = _write_result(tmp_path, "current123456", "current", "2026-08-03")
    recent = _write_result(tmp_path, "recent123456", "recent", "2026-08-02")
    old = _write_result(tmp_path, "old12345678", "old", "2026-07-01")

    result = _run(tmp_path, "--apply", "--keep-superseded", "1")

    assert result.returncode == 0
    assert current.exists()
    assert recent.exists()
    assert not old.exists()
