"""Contracts for the local verification gate.

These tests protect the gate itself: a test command may fail, but it may not
silently turn missing evidence into a green result.
"""

import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[2]
VERIFY = ROOT / "scripts" / "verify.sh"
VERIFY_STAGING = ROOT / "scripts" / "verify-staging.sh"
MANIFEST_WRITER = ROOT / "scripts" / "write-verification-manifest.py"


def test_gate_has_no_success_by_refusal_or_ignored_failure():
    for path in (VERIFY, VERIFY_STAGING):
        source = path.read_text()
        assert "|| true" not in source
        assert "Gate continues" not in source
    assert "write_manifest_on_exit" in VERIFY.read_text()


def test_missing_gmail_token_requires_explicit_degradation_flag():
    source = VERIFY.read_text()
    assert "--accept-stale-gmail-token" in source
    assert "ACCEPT_STALE_GMAIL" in source
    assert 'VERIFY_ACCEPTED_DEGRADATIONS="real-gmail-token-unavailable"' in source


def test_manifest_writer_records_every_skip_and_rejects_unbudgeted_nodes(tmp_path):
    junit = tmp_path / "results.xml"
    junit.write_text(
        """<testsuite tests="2">
  <testcase classname="tests.test_example.Example" name="test_ok" />
  <testcase classname="tests.test_example.Example" name="test_skip">
    <skipped message="requires a real token" />
  </testcase>
</testsuite>
"""
    )
    budget = tmp_path / "skip_budget.toml"
    budget.write_text(
        '[[skip]]\nnodeid = "tests/test_example.py::Example::test_skip"\n'
        'reason = "requires a real token"\n'
    )
    manifest = tmp_path / "manifest.json"
    result = subprocess.run(
        [
            "python3",
            str(MANIFEST_WRITER),
            "--manifest",
            str(manifest),
            "--skip-budget",
            str(budget),
            "--status",
            "0",
            "--git-sha",
            "abc",
            "--seed",
            "123",
            str(junit),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    data = json.loads(manifest.read_text())
    assert data["status"] == "passed"
    assert data["pytest"]["skips"] == [
        {"nodeid": "tests/test_example.py::Example::test_skip", "reason": "requires a real token"}
    ]
    assert data["pytest"]["passed"] == 1

    budget.write_text(
        '[[skip]]\nnodeid = "tests/test_example.py::Example::other"\nreason = "other"\n'
    )
    rejected = subprocess.run(
        [
            "python3",
            str(MANIFEST_WRITER),
            "--manifest",
            str(manifest),
            "--skip-budget",
            str(budget),
            "--status",
            "0",
            "--git-sha",
            "abc",
            "--seed",
            "123",
            str(junit),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert rejected.returncode == 1
    assert "outside budget" in rejected.stderr
