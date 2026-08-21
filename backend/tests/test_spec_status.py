"""Contracts for derived spec status generation."""

import json
import os
import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "scripts" / "spec-status.sh"
README = ROOT / "docs/specs/README.md"


def _env(tmp_path: Path, readme: Path | None = None) -> dict[str, str]:
    environment = os.environ.copy()
    environment["SPEC_STATUS_EVIDENCE_DIR"] = str(tmp_path / "evidence")
    if readme is not None:
        environment["SPEC_STATUS_README"] = str(readme)
    return environment


def test_every_spec_has_machine_checkable_acceptance_metadata():
    for path in sorted((ROOT / "docs/specs").glob("*.md")):
        if path.name == "README.md":
            continue
        assert path.read_text().startswith("+++\n"), path
        assert "tests = [" in path.read_text(), path
        assert "health = [" in path.read_text(), path
        assert "drills = [" in path.read_text(), path


def test_generated_status_table_is_current(tmp_path):
    result = subprocess.run(
        [str(SCRIPT), "--check"],
        cwd=ROOT,
        env=_env(tmp_path),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_hand_editing_a_status_cell_fails(tmp_path):
    edited = tmp_path / "README.md"
    content = README.read_text()
    content = content.replace("Evidence pending", "Hand-authored status", 1)
    edited.write_text(content)
    result = subprocess.run(
        [str(SCRIPT), "--check"],
        cwd=ROOT,
        env=_env(tmp_path, edited),
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1
    assert "not generated" in result.stderr


def test_passed_manifest_proves_matching_test_nodes(tmp_path):
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    manifest = {
        "status": "passed",
        "pytest": {
            "passed_nodes": [
                "tests/test_spec_status.py::test_generated_status_table_is_current",
            ]
        },
    }
    (evidence / "backend.json").write_text(json.dumps(manifest))
    generated_readme = tmp_path / "README.md"
    generated_readme.write_text(README.read_text())
    generated = subprocess.run(
        [str(SCRIPT)],
        cwd=ROOT,
        env=_env(tmp_path, generated_readme),
        capture_output=True,
        text=True,
        check=False,
    )
    assert generated.returncode == 0, generated.stderr
    assert "Partial evidence (tests 1/2" in generated_readme.read_text()
