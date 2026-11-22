"""scripts/ops.py and .github/workflows/ops.yml must describe the same operations.

ops.py is the client a cloud session dispatches production and Postgres work
through, and the validator the workflow runs before any job holding a secret
starts. These tests pin the payload contract on both sides, and that the two
files cannot drift: an operation the workflow accepts but ops.py does not (or
the reverse) is a dispatch that either never runs or runs unvalidated.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
OPS_SCRIPT = ROOT / "scripts" / "ops.py"
OPS_WORKFLOW = ROOT / ".github" / "workflows" / "ops.yml"

_spec = importlib.util.spec_from_file_location("selko_ops_script", OPS_SCRIPT)
ops = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = ops
_spec.loader.exec_module(ops)

SHA = "0123456789abcdef0123456789abcdef01234567"
USER = "11111111-2222-3333-4444-555555555555"
MANIFEST = {"version": 1, "user_id": USER, "actions": [{"action": "cancel_event"}]}


def _workflow() -> dict:
    data = yaml.safe_load(OPS_WORKFLOW.read_text())
    # PyYAML reads the bare key `on` as the boolean True.
    data["on"] = data.pop(True, data.get("on"))
    return data


def test_workflow_and_client_name_the_same_operations():
    workflow = _workflow()
    dispatch_types = set(workflow["on"]["repository_dispatch"]["types"])
    manual_options = set(workflow["on"]["workflow_dispatch"]["inputs"]["operation"]["options"])
    assert dispatch_types == set(ops.SCHEMAS)
    assert manual_options == set(ops.SCHEMAS)


def test_every_operation_has_a_job_and_every_field_reaches_the_jobs():
    workflow = _workflow()
    jobs = workflow["jobs"]
    gated = {
        op
        for job in jobs.values()
        for op in ops.SCHEMAS
        if f"needs.request.outputs.operation == '{op}'" in str(job.get("if", ""))
    }
    assert gated == set(ops.SCHEMAS), "an operation with no job would dispatch and do nothing"
    outputs = set(jobs["request"]["outputs"])
    fields = {field for schema in ops.SCHEMAS.values() for field in schema} - ops.SENSITIVE_FIELDS
    assert fields <= outputs, f"validated but never handed to a job: {sorted(fields - outputs)}"
    assert not (ops.SENSITIVE_FIELDS & outputs), "a user-identifying field would reach the public log"


def test_no_step_puts_the_payload_in_its_env():
    """GitHub prints every step's env block in the log, and this repo's logs are public."""
    offenders = [
        f"{name} / {step.get('name')}"
        for name, job in _workflow()["jobs"].items()
        for step in job.get("steps", [])
        if "client_payload" in json.dumps(step.get("env", {})) or "inputs.payload" in json.dumps(step.get("env", {}))
    ]
    assert not offenders, offenders


def test_production_jobs_never_run_concurrently():
    jobs = _workflow()["jobs"]
    for name in ("deploy-production", "repair-review-queue"):
        assert jobs[name]["concurrency"] == {"group": "production", "cancel-in-progress": False}


def test_every_action_is_pinned_by_full_sha():
    for path in (ROOT / ".github" / "workflows").glob("*.yml"):
        for line in path.read_text().splitlines():
            stripped = line.strip().removeprefix("- ")
            if stripped.startswith("uses:"):
                ref = stripped.split("@", 1)[1].split()[0]
                assert len(ref) == 40 and all(c in "0123456789abcdef" for c in ref), (
                    f"{path.name}: {stripped} is not pinned by commit SHA"
                )


def test_defaults_fill_in_and_request_id_passes_through():
    normalized = ops.validate("schema-compat", {"request_id": "a" * 32})
    assert normalized == {
        "request_id": "a" * 32,
        "target": "production",
        "when": "pre-deploy",
    }


@pytest.mark.parametrize(
    ("operation", "payload", "problem"),
    [
        ("schema-compat", {"target": "prod"}, "target"),
        ("schema-compat", {"tagret": "staging"}, "unknown field"),
        ("deploy-production", {"confirm": f"deploy {SHA}"}, "sha: required"),
        ("deploy-production", {"sha": SHA.upper(), "confirm": f"deploy {SHA}"}, "sha"),
        ("deploy-production", {"sha": SHA, "confirm": "yes"}, "confirm"),
        ("deploy-production", {"sha": SHA, "confirm": f"deploy {'f' * 40}"}, "confirm"),
        ("rehearse-cutover", {"faithful": "yes"}, "faithful"),
        ("repair-review-queue", {}, "manifest: required"),
        ("repair-review-queue", {"manifest": {"user_id": "nope", "actions": [{}]}}, "manifest"),
        ("repair-review-queue", {"manifest": MANIFEST, "apply": True}, "confirm_user: required"),
        (
            "repair-review-queue",
            {
                "manifest": MANIFEST,
                "apply": True,
                "confirm_user": "99999999-2222-3333-4444-555555555555",
                "confirm": "apply 99999999-2222-3333-4444-555555555555",
            },
            "does not match manifest.user_id",
        ),
        (
            "repair-review-queue",
            {"manifest": MANIFEST, "apply": True, "confirm_user": USER, "confirm": "yes"},
            "confirm",
        ),
        ("repair-review-queue", {"manifest": MANIFEST, "confirm_user": USER}, "only meaningful"),
        ("android-emulator", {"ref": "main; rm -rf /"}, "ref"),
        ("schema-compat", {"request_id": "not-hex"}, "request_id"),
        ("unknown-op", {}, "unknown operation"),
    ],
)
def test_bad_payloads_are_refused(operation, payload, problem):
    with pytest.raises(ops.PayloadError, match=problem):
        ops.validate(operation, payload)


def test_deploy_names_exactly_its_commit():
    normalized = ops.validate("deploy-production", {"sha": SHA, "confirm": f"deploy {SHA}"})
    assert normalized["sha"] == SHA


def test_repair_apply_requires_the_matching_user_and_phrase():
    normalized = ops.validate(
        "repair-review-queue",
        {"manifest": MANIFEST, "apply": True, "confirm_user": USER, "confirm": f"apply {USER}"},
    )
    assert normalized["apply"] is True
    assert ops.validate("repair-review-queue", {"manifest": MANIFEST})["apply"] is False


def test_redact_masks_uuids_and_emails():
    line = f"event id={USER} owner=someone.real@example.com status=active\n"
    assert ops.redact(line) == "event id=<uuid:11111111> owner=<email> status=active\n"


def _run_validate(event: dict, tmp_path: Path, *extra: str) -> tuple[subprocess.CompletedProcess, str]:
    output = tmp_path / "github_output"
    event_path = tmp_path / "event.json"
    event_path.write_text(json.dumps(event))
    env = {k: v for k, v in os.environ.items() if not k.startswith("OPS_")}
    env.update({"GITHUB_EVENT_PATH": str(event_path), "GITHUB_OUTPUT": str(output)})
    completed = subprocess.run(
        [sys.executable, str(OPS_SCRIPT), "validate", *extra],
        capture_output=True, text=True, env=env, check=False,
    )
    return completed, output.read_text() if output.exists() else ""


def _dispatch_event(operation: str, payload: dict) -> dict:
    return {"action": operation, "client_payload": payload}


def test_validate_reads_the_event_and_keeps_user_ids_out_of_outputs_and_log(tmp_path):
    event = _dispatch_event(
        "repair-review-queue",
        {"manifest": MANIFEST, "apply": True, "confirm_user": USER, "confirm": f"apply {USER}"},
    )
    request = tmp_path / "request.json"
    completed, outputs = _run_validate(
        event, tmp_path, "--operation", "repair-review-queue", "--write-payload", str(request)
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "operation=repair-review-queue" in outputs
    assert "apply=true" in outputs
    assert USER not in outputs
    assert USER not in completed.stdout
    written = json.loads(request.read_text())
    assert written["manifest"] == MANIFEST
    assert written["confirm_user"] == USER


def test_validate_reads_a_manual_run_too(tmp_path):
    event = {"inputs": {"operation": "schema-compat", "payload": '{"target": "staging"}', "request_id": ""}}
    completed, outputs = _run_validate(event, tmp_path)
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert "target=staging" in outputs
    assert "when=pre-deploy" in outputs


def test_validate_refuses_a_job_serving_another_operation(tmp_path):
    completed, outputs = _run_validate(
        _dispatch_event("schema-compat", {}), tmp_path, "--operation", "repair-review-queue"
    )
    assert completed.returncode == 1
    assert outputs == ""


def test_validate_fails_closed_on_a_bad_payload(tmp_path):
    completed, outputs = _run_validate(_dispatch_event("deploy-production", {"sha": SHA}), tmp_path)
    assert completed.returncode == 1
    assert "::error::" in completed.stdout
    assert outputs == ""
    bad_json = {"inputs": {"operation": "schema-compat", "payload": "{not json"}}
    completed, _ = _run_validate(bad_json, tmp_path)
    assert completed.returncode == 1
