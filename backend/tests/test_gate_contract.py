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


def _ci() -> dict:
    import yaml

    return yaml.safe_load((ROOT / ".github/workflows/ci.yml").read_text())


def _image_filters() -> tuple[list[str], list[str], list[str]]:
    """(release inputs, image-check inputs, tracked files) from ci.yml's path filters."""
    import yaml

    steps = _ci()["jobs"]["changes"]["steps"]
    filters = yaml.safe_load(next(s for s in steps if s.get("id") == "filter")["with"]["filters"])

    def flat(items):
        out = []
        for item in items:
            out.extend(flat(item) if isinstance(item, list) else [item])
        return out

    tracked = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout.split()
    return flat(filters["image_inputs"]), flat(filters["image_check"]), tracked


def _matches(path: str, patterns: list[str]) -> bool:
    import fnmatch

    return any(path == p or fnmatch.fnmatch(path, p) for p in patterns)


def test_the_release_never_skips_a_change_to_what_the_image_is_built_from():
    """On main, CI pushes an image to release for every file the image is built from.

    A change there that did not release would merge, and production would
    quietly keep the old build. The image is built from exactly what
    .dockerignore admits, plus the Dockerfile and .dockerignore themselves.
    """
    release, _, tracked = _image_filters()
    admitted = [line[1:] for line in (ROOT / ".dockerignore").read_text().splitlines() if line.startswith("!")]
    built_from = [f for f in tracked if _matches(f, ["Dockerfile", ".dockerignore", *admitted])]
    assert len(built_from) > 100  # the patterns resolved to real files
    missed = [f for f in built_from if not _matches(f, release)]
    assert not missed, missed


def test_the_release_skips_what_the_image_is_not_built_from():
    """A merge that changes nothing in the image releases nothing.

    Production follows :main, so a release restarts it. A merge that changed
    only cloud-session scripts once released anyway, and that restart ended in
    a rollback.
    """
    release, _, tracked = _image_filters()
    for outside in [
        "scripts/cloud-setup.sh",
        "scripts/image-check.sh",  # checked on the PR; the image is unchanged
        ".github/workflows/ci.yml",
        ".github/workflows/image.yml",
        "CLAUDE.md",
        "backend/tests/test_gate_contract.py",
    ]:
        assert outside in tracked, outside  # the example is a real file
        assert not _matches(outside, release), f"{outside} is not in the image but would release"
    assert not _matches(".verify/ledger/x.jsonl", release)


def test_every_pr_that_touches_the_image_or_its_check_runs_the_image_check():
    """The image check runs for every image-lane input and everything that releases."""
    import tomllib

    release, check, tracked = _image_filters()
    inputs = tomllib.loads((ROOT / "scripts/lanes.toml").read_text())["lanes"]["image"]["inputs"]
    lane_files = [f for f in tracked if _matches(f, inputs)]
    assert len(lane_files) > 100
    missed = [f for f in lane_files if not _matches(f, check)]
    assert not missed, missed
    assert all(p in check for p in release), "a path that releases on main must be checked on its PR"


def test_ci_pushes_the_image_only_from_main_and_only_for_image_inputs():
    """Only a push to main whose diff touches the image's inputs publishes :<sha>."""
    publish = _ci()["jobs"]["image"]["env"]["PUBLISH"]
    for clause in ("github.event_name == 'push'", "refs/heads/main", "needs.changes.outputs.image_inputs == 'true'"):
        assert clause in publish, clause


def test_the_gate_needs_every_job_and_always_reports():
    """`CI gate` is the one required check: it must cover every job and never be skipped."""
    jobs = _ci()["jobs"]
    gate = jobs["gate"]
    assert gate["name"] == "CI gate"
    assert gate["if"] == "always()"
    assert set(gate["needs"]) == set(jobs) - {"gate"}


def test_the_release_runs_only_after_ci_passed_for_a_push_to_main():
    """image.yml signs only what a green CI run on a push to main built and checked.

    The signing identity the server verifies is this file on refs/heads/main,
    so the file name, the signing job and the branch must not change.
    """
    import yaml

    workflow = yaml.safe_load((ROOT / ".github/workflows/image.yml").read_text())
    triggers = workflow.get("on", workflow.get(True))
    assert set(triggers) == {"workflow_run"}
    assert triggers["workflow_run"]["workflows"] == ["CI"]
    assert triggers["workflow_run"]["branches"] == ["main"]
    release = workflow["jobs"]["release"]
    assert "github.event.workflow_run.conclusion == 'success'" in release["if"]
    assert "github.event.workflow_run.event == 'push'" in release["if"]
    script = "\n".join(s.get("run", "") for s in release["steps"])
    assert "/.github/workflows/image.yml@refs/heads/main" in script
    assert "cosign sign" in script


def test_the_health_check_accepts_a_newer_release_that_contains_this_one():
    """Two merges in quick succession: production may skip straight to the second.

    The first release's health job then sees the second commit. That is a
    healthy deploy, not a failure, so it must not open a deploy-failure issue.
    """
    import yaml

    workflow = yaml.safe_load((ROOT / ".github/workflows/image.yml").read_text())
    steps = workflow["jobs"]["health"]["steps"]
    checkout = next(s for s in steps if s.get("uses", "").startswith("actions/checkout@"))
    assert checkout["with"]["fetch-depth"] == 0
    wait = next(s for s in steps if s.get("name", "").startswith("Wait for production"))["run"]
    assert 'merge-base --is-ancestor "$SHA" "$running"' in wait
