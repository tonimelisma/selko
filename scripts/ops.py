#!/usr/bin/env python3
"""Typed operations that run in GitHub Actions instead of on a workstation.

A cloud session cannot open a Postgres connection (TCP 5432/6543 is refused),
cannot push tags, and holds no production credential. Everything that needs one
of those is an operation of `.github/workflows/ops.yml`, started by a
`repository_dispatch` event whose payload this module defines and checks on
both sides: `dispatch` validates before sending, and the workflow's first job
runs `validate` on what actually arrived. A payload that does not match its
schema never reaches a step that holds a secret.

    scripts/ops.py dispatch schema-compat                      # pre-deploy, production
    scripts/ops.py dispatch schema-compat when=post-deploy
    scripts/ops.py dispatch deploy-production sha=<40-hex> confirm="deploy <40-hex>"
    scripts/ops.py dispatch rehearse-cutover
    scripts/ops.py dispatch repair-review-queue --payload-file manifest-request.json
    scripts/ops.py dispatch staging-tier2                      # staging is paused today

`dispatch` waits for the run, prints each job's conclusion and the tail of any
failed job's log, and exits 0 only when the run concluded `success`. The run's
conclusion is the result; nothing here prints a verdict of its own.

The repository is public, so its workflow logs are too. `redact` is the filter
every production-reading step pipes through: it replaces UUIDs and email
addresses before a line reaches the log.

Standard library only: it runs before `uv sync` in the workflow.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SHA_RE = re.compile(r"^[0-9a-f]{40}$")
UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
REQUEST_ID_RE = re.compile(r"^[0-9a-f]{32}$")


class PayloadError(ValueError):
    pass


def _choice(*options: str) -> Callable[[Any], str]:
    def check(value: Any) -> str:
        if value not in options:
            raise PayloadError(f"must be one of {', '.join(options)}")
        return value

    return check


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if value in ("true", "false"):
        return value == "true"
    raise PayloadError("must be true or false")


def _pattern(regex: re.Pattern[str], what: str) -> Callable[[Any], str]:
    def check(value: Any) -> str:
        if not isinstance(value, str) or not regex.match(value):
            raise PayloadError(f"must be {what}")
        return value

    return check


def _text(value: Any) -> str:
    if not isinstance(value, str):
        raise PayloadError("must be a string")
    return value


def _manifest(value: Any) -> dict:
    # The repair script validates the manifest in depth; this only refuses a
    # shape it could never accept, before a production credential is in scope.
    if not isinstance(value, dict):
        raise PayloadError("must be an object")
    if not isinstance(value.get("user_id"), str) or not UUID_RE.fullmatch(value["user_id"]):
        raise PayloadError("must carry a user_id UUID")
    if not isinstance(value.get("actions"), list) or not value["actions"]:
        raise PayloadError("must carry a non-empty actions list")
    return value


# field -> (validator, default). A default of REQUIRED means the field must be
# sent. Unknown fields are refused: a typo must not silently fall back to a
# default, least of all on a production operation.
REQUIRED = object()
SCHEMAS: dict[str, dict[str, tuple[Callable[[Any], Any], Any]]] = {
    "schema-compat": {
        "target": (_choice("production", "staging"), "production"),
        # pre-deploy: `supabase db push --dry-run` must succeed (remote has no
        # migration the repo lacks) and lists what a deploy would apply.
        # post-deploy: every repo migration is applied remotely (R5).
        "when": (_choice("pre-deploy", "post-deploy"), "pre-deploy"),
    },
    "deploy-production": {
        "sha": (_pattern(SHA_RE, "a 40-character lowercase commit SHA"), REQUIRED),
        "confirm": (_text, REQUIRED),
    },
    "rehearse-cutover": {
        "faithful": (_bool, True),
    },
    "repair-review-queue": {
        "manifest": (_manifest, REQUIRED),
        "apply": (_bool, False),
        "confirm_user": (_pattern(UUID_RE, "a user UUID"), ""),
        "confirm": (_text, ""),
    },
    "staging-tier2": {
        "require_workers": (_bool, True),
    },
}


def validate(operation: str, payload: Any) -> dict[str, Any]:
    """Return the normalized payload, or raise PayloadError naming every problem."""
    if operation not in SCHEMAS:
        raise PayloadError(f"unknown operation {operation!r}; known: {', '.join(sorted(SCHEMAS))}")
    if not isinstance(payload, dict):
        raise PayloadError("payload must be a JSON object")
    schema = SCHEMAS[operation]
    problems: list[str] = []
    request_id = payload.get("request_id", "")
    if request_id and not (isinstance(request_id, str) and REQUEST_ID_RE.match(request_id)):
        problems.append("request_id: must be 32 lowercase hex characters")
    unknown = sorted(set(payload) - set(schema) - {"request_id"})
    if unknown:
        problems.append(f"unknown field(s): {', '.join(unknown)}")
    normalized: dict[str, Any] = {"request_id": request_id}
    for field, (check, default) in schema.items():
        if field not in payload:
            if default is REQUIRED:
                problems.append(f"{field}: required")
            else:
                normalized[field] = default
            continue
        try:
            normalized[field] = check(payload[field])
        except PayloadError as exc:
            problems.append(f"{field}: {exc}")
    if not problems:
        problems.extend(_cross_field_problems(operation, normalized))
    if problems:
        raise PayloadError("; ".join(problems))
    return normalized


def _cross_field_problems(operation: str, p: dict[str, Any]) -> list[str]:
    if operation == "deploy-production" and p["confirm"] != f"deploy {p['sha']}":
        # Not an authorization -- the owner's yes is given in the conversation
        # (CLAUDE.md). It makes the request name exactly the commit that yes
        # was for, so a stale or mistyped SHA cannot ride along.
        return ["confirm: must be exactly 'deploy <sha>' for the sha being deployed"]
    if operation == "repair-review-queue":
        if p["apply"]:
            problems = []
            if not p["confirm_user"]:
                problems.append("confirm_user: required with apply=true")
            elif p["confirm_user"] != p["manifest"]["user_id"]:
                problems.append("confirm_user: does not match manifest.user_id")
            if p["confirm"] != f"apply {p['confirm_user']}":
                problems.append("confirm: must be exactly 'apply <confirm_user>' with apply=true")
            return problems
        if p["confirm_user"] or p["confirm"]:
            return ["confirm_user/confirm: only meaningful with apply=true"]
    return []


def redact(line: str) -> str:
    line = UUID_RE.sub(lambda m: f"<uuid:{m.group(0)[:8]}>", line)
    return EMAIL_RE.sub("<email>", line)


# --- GitHub side ----------------------------------------------------------


def _gh(*args: str, input_text: str | None = None) -> str:
    completed = subprocess.run(
        ["gh", "api", *args], input=input_text, capture_output=True, text=True, check=False
    )
    if completed.returncode != 0:
        raise RuntimeError(f"gh api {' '.join(args)} failed: {completed.stderr.strip()}")
    return completed.stdout


def _repository() -> str:
    if os.environ.get("GITHUB_REPOSITORY"):
        return os.environ["GITHUB_REPOSITORY"]
    url = subprocess.run(
        ["git", "remote", "get-url", "origin"], capture_output=True, text=True, check=True
    ).stdout.strip()
    # https://github.com/o/r(.git), git@github.com:o/r.git, or a session proxy
    # URL ending in /o/r -- the last two path components either way.
    parts = re.split(r"[/:]", url.removesuffix(".git"))
    return f"{parts[-2]}/{parts[-1]}"


def _find_run(repo: str, request_id: str, deadline: float) -> dict:
    while time.time() < deadline:
        runs = json.loads(_gh(f"repos/{repo}/actions/runs?event=repository_dispatch&per_page=30"))
        for run in runs.get("workflow_runs", []):
            if request_id in (run.get("display_title") or ""):
                return run
        time.sleep(5)
    raise RuntimeError(f"no workflow run appeared for request {request_id}")


def _report_jobs(repo: str, run_id: int) -> None:
    jobs = json.loads(_gh(f"repos/{repo}/actions/runs/{run_id}/jobs?per_page=100"))["jobs"]
    for job in jobs:
        print(f"  {job['conclusion'] or job['status']:<10} {job['name']}")
    for job in jobs:
        if job["conclusion"] in ("failure", "timed_out", "cancelled"):
            log = _gh(f"repos/{repo}/actions/jobs/{job['id']}/logs")
            tail = log.splitlines()[-80:]
            print(f"\n--- last {len(tail)} log lines of '{job['name']}' ---")
            print("\n".join(tail))


def _download_artifacts(repo: str, run_id: int, dest: Path) -> None:
    artifacts = json.loads(_gh(f"repos/{repo}/actions/runs/{run_id}/artifacts"))["artifacts"]
    dest.mkdir(parents=True, exist_ok=True)
    for artifact in artifacts:
        archive = dest / f"{artifact['name']}.zip"
        with archive.open("wb") as handle:
            subprocess.run(
                ["gh", "api", f"repos/{repo}/actions/artifacts/{artifact['id']}/zip"],
                stdout=handle, check=True,
            )
        subprocess.run(["unzip", "-o", "-q", str(archive), "-d", str(dest)], check=True)
        archive.unlink()
        print(f"downloaded artifact {artifact['name']} into {dest}")


def _parse_fields(pairs: list[str]) -> dict[str, Any]:
    fields: dict[str, Any] = {}
    for pair in pairs:
        key, sep, value = pair.partition("=")
        if not sep:
            raise PayloadError(f"expected key=value, got {pair!r}")
        fields[key] = value
    return fields


def cmd_dispatch(args: argparse.Namespace) -> int:
    payload: dict[str, Any] = {}
    if args.payload_file:
        payload.update(json.loads(Path(args.payload_file).read_text()))
    payload.update(_parse_fields(args.fields))
    payload["request_id"] = uuid.uuid4().hex
    normalized = validate(args.operation, payload)
    repo = _repository()
    sent_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    _gh(
        "-X", "POST", f"repos/{repo}/dispatches", "--input", "-",
        input_text=json.dumps({"event_type": args.operation, "client_payload": normalized}),
    )
    print(f"dispatched {args.operation} (request {normalized['request_id']}) at {sent_at}")
    if args.no_wait:
        return 0
    deadline = time.time() + args.timeout
    run = _find_run(repo, normalized["request_id"], time.time() + 120)
    print(f"run {run['id']}: {run['html_url']}")
    while run["status"] != "completed":
        if time.time() > deadline:
            print(f"run still {run['status']} after {args.timeout}s; follow it at {run['html_url']}")
            return 1
        time.sleep(15)
        run = json.loads(_gh(f"repos/{repo}/actions/runs/{run['id']}"))
    print(f"run {run['id']} concluded: {run['conclusion']}")
    _report_jobs(repo, run["id"])
    if args.download:
        _download_artifacts(repo, run["id"], Path(args.download))
    return 0 if run["conclusion"] == "success" else 1


# Fields that identify a user or event. They never become step outputs or
# step env: GitHub prints every step's `env:` block in the (public) log.
SENSITIVE_FIELDS = {"manifest", "confirm_user", "confirm"}


def _load_request() -> tuple[str, Any]:
    """The operation and raw payload this workflow run was started with.

    Read from the event file rather than from step env, so the payload never
    appears in a log. OPS_OPERATION/OPS_PAYLOAD override it for tests.
    """
    if "OPS_OPERATION" in os.environ:
        return os.environ["OPS_OPERATION"], json.loads(os.environ.get("OPS_PAYLOAD") or "{}")
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text())
    if "client_payload" in event:  # repository_dispatch
        return event.get("action", ""), event["client_payload"]
    inputs = event.get("inputs") or {}  # workflow_dispatch
    payload = json.loads(inputs.get("payload") or "{}")
    if inputs.get("request_id"):
        payload.setdefault("request_id", inputs["request_id"])
    return inputs.get("operation", ""), payload


def cmd_validate(args: argparse.Namespace) -> int:
    """Workflow side: validate the run's payload; write outputs and, optionally, the payload."""
    operation = ""
    try:
        operation, payload = _load_request()
        if args.operation and operation != args.operation:
            raise PayloadError(f"this job serves {args.operation}, the run is {operation}")
        normalized = validate(operation, payload)
    except (json.JSONDecodeError, PayloadError) as exc:
        # The message names fields, never echoes values.
        print(f"::error::invalid {operation or '<no operation>'} payload: {redact(str(exc))}")
        return 1
    if args.write_payload:
        Path(args.write_payload).write_text(json.dumps(normalized, sort_keys=True))
    lines = [f"operation={operation}"]
    for key, value in normalized.items():
        if key in SENSITIVE_FIELDS:
            continue
        lines.append(f"{key}={'true' if value is True else 'false' if value is False else value}")
    output = os.environ.get("GITHUB_OUTPUT")
    if output:
        with open(output, "a", encoding="utf-8") as handle:
            handle.write("\n".join(lines) + "\n")
    print(" ".join(lines))
    return 0


def cmd_redact(_args: argparse.Namespace) -> int:
    for line in sys.stdin:
        sys.stdout.write(redact(line))
        sys.stdout.flush()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    dispatch = sub.add_parser("dispatch", help="send a repository_dispatch and wait for its run")
    dispatch.add_argument("operation", choices=sorted(SCHEMAS))
    dispatch.add_argument("fields", nargs="*", help="payload fields as key=value")
    dispatch.add_argument("--payload-file", help="JSON object merged under the key=value fields")
    dispatch.add_argument("--no-wait", action="store_true")
    dispatch.add_argument("--timeout", type=int, default=3600, help="seconds to wait for the run")
    dispatch.add_argument("--download", help="directory to unpack the run's artifacts into")
    dispatch.set_defaults(func=cmd_dispatch)
    check = sub.add_parser("validate", help="workflow side: check this run's payload")
    check.add_argument("--operation", help="fail unless the run is this operation")
    check.add_argument("--write-payload", help="write the normalized payload (sensitive fields included) here")
    check.set_defaults(func=cmd_validate)
    sub.add_parser("redact", help="stdin -> stdout with UUIDs and emails masked").set_defaults(func=cmd_redact)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except (PayloadError, RuntimeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
