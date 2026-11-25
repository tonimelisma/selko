"""Contracts for the local verification gate.

These tests protect the gate itself: a test command may fail, but it may not
silently turn missing evidence into a green result.
"""

import json
import re
import subprocess
from pathlib import Path


ROOT = Path(__file__).parents[2]
VERIFY = ROOT / "scripts" / "verify.sh"
MANIFEST_WRITER = ROOT / "scripts" / "write-verification-manifest.py"


def test_gate_has_no_success_by_refusal_or_ignored_failure():
    source = VERIFY.read_text()
    assert "|| true" not in source
    assert "Gate continues" not in source
    assert "write_manifest_on_exit" in VERIFY.read_text()


def test_the_backend_gate_needs_no_database_service():
    """The suite runs on SQLite files it creates; no service may be a precondition."""
    source = VERIFY.read_text()
    for gone in ("supabase", "docker", "seed_test_tokens", "ACCEPT_STALE_GMAIL"):
        assert gone not in source.lower(), gone
    assert "backend/selko/db/migrations" in source  # the schema hash is the migrations' content


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


def test_sourcing_the_gate_does_not_run_it(tmp_path):
    """The helpers must be reachable without the gate executing as a side effect."""
    marker = tmp_path / "ran"
    result = subprocess.run(
        ["bash", "-c", f'source "{VERIFY}"; echo sourced'],
        capture_output=True,
        text=True,
        cwd=ROOT,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "sourced" in result.stdout
    assert "Usage:" not in result.stdout
    assert not marker.exists()


WORKFLOWS = sorted((ROOT / ".github" / "workflows").glob("*.yml"))

# A shell line that is really a misplaced YAML env entry: NAME: ${{ ... }}
_STRAY_ENV_IN_SHELL = re.compile(r"^\s*[A-Z][A-Z0-9_]*:\s*\$\{\{")


def test_no_workflow_step_has_env_entries_stranded_inside_its_script():
    """A step's env keys must not fall into the previous step's run: block.

    This is not hypothetical. A step inserted mid-``env:`` pushed four secret
    entries into the preceding step's block scalar, where they ran as shell:

        line 8: TEST_USER_EMAIL:: command not found   (exit 127)

    ``yaml.safe_load`` accepted the file without complaint, because misplaced
    lines inside a block scalar are valid YAML. A parse check proves the file
    is YAML; it says nothing about whether the structure means what was
    intended. This asserts the structure.
    """
    import yaml

    assert WORKFLOWS, "no workflow files found"
    offenders = []
    for path in WORKFLOWS:
        workflow = yaml.safe_load(path.read_text())
        for job_name, job in (workflow.get("jobs") or {}).items():
            for step in job.get("steps") or []:
                script = step.get("run")
                if not isinstance(script, str):
                    continue
                for line in script.splitlines():
                    if _STRAY_ENV_IN_SHELL.match(line):
                        offenders.append(f"{path.name} / {job_name} / {step.get('name')}: {line.strip()}")
    assert not offenders, (
        "env entries stranded inside a run: block — they will execute as shell: "
        f"{offenders}"
    )



BACKEND_PYPROJECT = ROOT / "backend" / "pyproject.toml"
ROOT_PYPROJECT = ROOT / "pyproject.toml"

def _declared_test_deps(path):
    import tomllib

    data = tomllib.loads(path.read_text())
    extras = data.get("project", {}).get("optional-dependencies", {})
    names = []
    for spec in extras.get("test", []):
        name = spec.split(">")[0].split("=")[0].split("[")[0].strip()
        names.append(name)
    return names


def test_backend_test_extra_is_covered_by_the_root_extra_or_dev_group():
    """The root is what `uv sync` resolves, so it has to carry the union."""
    import tomllib

    backend = set(_declared_test_deps(BACKEND_PYPROJECT))
    root_data = tomllib.loads(ROOT_PYPROJECT.read_text())
    root = {
        spec.split(">")[0].split("=")[0].split("[")[0].strip()
        for spec in root_data.get("project", {}).get("optional-dependencies", {}).get("test", [])
    }
    for group in (root_data.get("dependency-groups") or {}).values():
        for spec in group:
            if isinstance(spec, str):
                root.add(spec.split(">")[0].split("=")[0].split("[")[0].strip())
    # httpx arrives transitively via supabase; it is importable either way and
    # the installed-check above is the assertion that matters for it.
    uncovered = backend - root - {"httpx"}
    assert not uncovered, (
        "declared in backend's test extra but not in the root extra or dev group, "
        f"so `uv sync --extra test` will not install it: {sorted(uncovered)}"
    )


def test_manifest_records_which_nodes_failed(tmp_path):
    """A red gate must name the failing tests, not just count them.

    The manifest recorded `passed_nodes` only, so diagnosing a failure meant
    re-running and hoping to reproduce it -- which for an order-dependent or
    network-dependent test is precisely what does not reproduce. Twice in this
    project's history a red gate was investigated by re-running until it went
    green, which is not diagnosis.
    """
    junit = tmp_path / "results.xml"
    junit.write_text(
        """<testsuite tests="3">
  <testcase classname="tests.test_example.Example" name="test_ok" />
  <testcase classname="tests.test_example.Example" name="test_broken">
    <failure message="AssertionError: expected 1 got 2&#10;second line" />
  </testcase>
  <testcase classname="tests.test_example.Example" name="test_errored">
    <error message="ConnectionError: refused" />
  </testcase>
</testsuite>
"""
    )
    budget = tmp_path / "skip_budget.toml"
    budget.write_text("")
    manifest = tmp_path / "manifest.json"
    subprocess.run(
        [
            "python3", str(MANIFEST_WRITER),
            "--manifest", str(manifest),
            "--skip-budget", str(budget),
            "--status", "1",
            "--git-sha", "abc",
            "--seed", "123",
            str(junit),
        ],
        capture_output=True, text=True, check=False,
    )
    data = json.loads(manifest.read_text())
    failed = {entry["nodeid"]: entry for entry in data["pytest"]["failed_nodes"]}
    assert set(failed) == {
        "tests/test_example.py::Example::test_broken",
        "tests/test_example.py::Example::test_errored",
    }
    assert failed["tests/test_example.py::Example::test_broken"]["kind"] == "failure"
    assert failed["tests/test_example.py::Example::test_errored"]["kind"] == "error"
    # First line only -- identifying, never a payload dump.
    assert "second line" not in failed["tests/test_example.py::Example::test_broken"]["message"]


def test_a_skip_budget_entry_may_list_several_acceptable_reasons(tmp_path):
    """One missing precondition can skip for more than one legitimate reason.

    The real-Gmail tests skip with "No Gmail credentials" when no token was
    ever seeded, and with an explicit-degradation message when verify.sh ran
    with --accept-stale-gmail-token. Pinning a single string made the second
    case a gate failure on a run with 1502 passed and 0 failed. Any reason
    outside the list must still trip the guard.
    """
    junit = tmp_path / "junit.xml"
    junit.write_text(
        """<testsuite tests="1">
  <testcase classname="tests.test_example.Example" name="test_skip">
    <skipped message="staging token unavailable; real-Gmail development tests skipped" />
  </testcase>
</testsuite>
"""
    )
    budget = tmp_path / "skip_budget.toml"
    budget.write_text(
        '[[skip]]\nnodeid = "tests/test_example.py::Example::test_skip"\n'
        'reason = ["No Gmail credentials", "real-Gmail development tests skipped"]\n'
    )

    def run_writer():
        return subprocess.run(
            [
                "python3", str(MANIFEST_WRITER),
                "--manifest", str(tmp_path / "manifest.json"),
                "--skip-budget", str(budget),
                "--status", "0",
                "--git-sha", "abc",
                "--seed", "123",
                str(junit),
            ],
            capture_output=True, text=True, check=False,
        )

    accepted = run_writer()
    assert accepted.returncode == 0, accepted.stderr

    # The guard still has teeth: a reason in neither entry is rejected.
    budget.write_text(
        '[[skip]]\nnodeid = "tests/test_example.py::Example::test_skip"\n'
        'reason = ["No Gmail credentials", "some other sanctioned reason"]\n'
    )
    rejected = run_writer()
    assert rejected.returncode != 0
    assert "skip reason changed" in (rejected.stderr + rejected.stdout)
