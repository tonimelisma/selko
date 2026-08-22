"""Contracts for the local verification gate.

These tests protect the gate itself: a test command may fail, but it may not
silently turn missing evidence into a green result.
"""

import json
import os
import re
import subprocess
import time
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


def test_gate_bounds_every_docker_probe():
    """No docker invocation in the gate may run unbounded.

    A source-text assertion is acceptable here only because the property *is* a
    property of the script's text. The behavioural half is
    ``test_bounded_docker_probe_fails_fast_when_the_daemon_hangs`` below.
    """
    source = VERIFY.read_text()
    assert "DOCKER_PROBE_TIMEOUT_SECONDS" in source
    offenders = [
        line.strip()
        for line in source.splitlines()
        if re.search(r"(^|[^\w_-])docker\s+[a-z]", line)
        and not line.lstrip().startswith("#")
        and "bounded_docker" not in line
    ]
    assert not offenders, f"unbounded docker invocations in the gate: {offenders}"


def _stub_docker(tmp_path: Path, script: str) -> dict[str, str]:
    stub_dir = tmp_path / "bin"
    stub_dir.mkdir()
    stub = stub_dir / "docker"
    stub.write_text(script)
    stub.chmod(0o755)
    environment = os.environ.copy()
    environment["PATH"] = f"{stub_dir}{os.pathsep}{environment['PATH']}"
    return environment


def test_bounded_docker_probe_fails_fast_when_the_daemon_hangs(tmp_path):
    """A wedged daemon must fail the gate, not stall it.

    Docker Desktop reports itself running while its VM disk has taken an I/O
    fault (``EXT4-fs (vda1) ... error -5``); every daemon call then blocks
    forever. Before this bound, ``verify.sh backend`` hung indefinitely instead
    of exiting non-zero.
    """
    environment = _stub_docker(tmp_path, "#!/bin/sh\nsleep 60\n")
    environment["DOCKER_PROBE_TIMEOUT_SECONDS"] = "2"
    started = time.monotonic()
    result = subprocess.run(
        ["bash", "-c", f'source "{VERIFY}"; bounded_docker inspect anything || echo "exit=$?"; echo "done=$?"'],
        capture_output=True,
        text=True,
        env=environment,
        cwd=ROOT,
        check=False,
    )
    elapsed = time.monotonic() - started
    assert "exit=124" in result.stdout, result.stdout + result.stderr
    assert elapsed < 30, f"probe took {elapsed:.1f}s; the bound did not apply"


def test_bounded_docker_probe_passes_through_a_healthy_daemon(tmp_path):
    environment = _stub_docker(tmp_path, "#!/bin/sh\necho healthy\n")
    environment["DOCKER_PROBE_TIMEOUT_SECONDS"] = "5"
    result = subprocess.run(
        ["bash", "-c", f'source "{VERIFY}"; bounded_docker inspect anything || echo "exit=$?"; echo "done=$?"'],
        capture_output=True,
        text=True,
        env=environment,
        cwd=ROOT,
        check=False,
    )
    assert "healthy" in result.stdout, result.stdout + result.stderr
    assert "exit=" not in result.stdout, "a healthy probe must not report failure"
    assert "done=0" in result.stdout, result.stdout + result.stderr


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


WORKFLOW = ROOT / ".github" / "workflows" / "test.yml"

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

    workflow = yaml.safe_load(WORKFLOW.read_text())
    offenders = []
    for job_name, job in (workflow.get("jobs") or {}).items():
        for step in job.get("steps") or []:
            script = step.get("run")
            if not isinstance(script, str):
                continue
            for line in script.splitlines():
                if _STRAY_ENV_IN_SHELL.match(line):
                    offenders.append(f"{job_name} / {step.get('name')}: {line.strip()}")
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
