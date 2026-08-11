#!/usr/bin/env bash
# Prune superseded LLM evaluation artifacts without risking an accidental delete.
# Default is a report-only dry run; pass --apply to remove candidates.
set -euo pipefail

KEEP_SUPERSEDED=1
APPLY=false
RESULTS_ROOT="${EVAL_RESULTS_ROOT:-backend/tests/eval/results}"

usage() {
  echo "Usage: ./scripts/prune-eval-results.sh [--dry-run|--apply] [--keep-superseded N]"
}

while (($#)); do
  case "$1" in
    --dry-run) APPLY=false ;;
    --apply) APPLY=true ;;
    --keep-superseded)
      shift
      [[ "${1:-}" =~ ^[0-9]+$ ]] || { echo "--keep-superseded requires a non-negative integer" >&2; exit 2; }
      KEEP_SUPERSEDED="$1"
      ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

[[ -d "$RESULTS_ROOT" ]] || { echo "ERROR: results directory not found: $RESULTS_ROOT" >&2; exit 1; }

CURRENT_HASHES_JSON="${EVAL_CURRENT_PROMPT_HASHES:-}"
if [[ -z "$CURRENT_HASHES_JSON" ]]; then
  CURRENT_HASHES_JSON=$(uv run python - <<'PY'
import json
from backend.tests.eval.run_eval import get_prompt_hash

print(json.dumps({operation: get_prompt_hash(operation) for operation in ("extract", "compare", "merge")}))
PY
)
fi

export RESULTS_ROOT KEEP_SUPERSEDED APPLY CURRENT_HASHES_JSON
python3 - <<'PY'
import json
import os
from collections import defaultdict
from pathlib import Path

root = Path(os.environ["RESULTS_ROOT"]).resolve()
keep_superseded = int(os.environ["KEEP_SUPERSEDED"])
apply = os.environ["APPLY"] == "true"
current = json.loads(os.environ["CURRENT_HASHES_JSON"])

def load(path):
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None

def metadata(path, data):
    relative = path.relative_to(root).parts
    if relative and relative[0] == "scores":
        inference_key = (data.get("identity") or {}).get("inference_key")
        if inference_key:
            inference_path = root / "inference" / inference_key[:2] / f"{inference_key}.json"
            inference = load(inference_path)
            if inference:
                data = {**inference, **data, "identity": inference.get("identity")}
    identity = data.get("identity") or {}
    prompt_hash = data.get("prompt_hash") or identity.get("prompt_contract_hash")
    operation = data.get("operation") or identity.get("operation")
    provider = data.get("provider") or identity.get("provider")
    model = data.get("model") or identity.get("model")
    thinking = data.get("thinking") or identity.get("thinking")
    fixture = data.get("fixture_name") or identity.get("fixture_name")
    run_at = data.get("run_at") or data.get("stored_at") or ""
    if not all((prompt_hash, operation, provider, model, fixture)):
        return None
    return (operation, provider, model, json.dumps(thinking, sort_keys=True), fixture, str(prompt_hash), str(run_at))

groups = defaultdict(list)
for path in root.rglob("*.json"):
    data = load(path)
    if not data:
        continue
    item = metadata(path, data)
    if item:
        operation, provider, model, thinking, fixture, prompt_hash, run_at = item
        groups[(operation, provider, model, thinking, fixture)].append((prompt_hash, run_at, path))

delete = []
for group, records in groups.items():
    operation = group[0]
    current_prefix = str(current.get(operation, ""))
    hashes = {record[0] for record in records}
    current_hashes = {value for value in hashes if current_prefix and value.startswith(current_prefix)}
    ordered = sorted(records, key=lambda record: (record[1], str(record[2])), reverse=True)
    keep = set(current_hashes)
    for prompt_hash, _, _ in ordered:
        if prompt_hash not in keep:
            keep.add(prompt_hash)
        if len(keep - current_hashes) >= keep_superseded:
            break
    delete.extend(path for prompt_hash, _, path in records if prompt_hash not in keep)

before_files = sum(1 for path in root.rglob("*") if path.is_file())
before_bytes = sum(path.stat().st_size for path in root.rglob("*") if path.is_file())
reclaimed = sum(path.stat().st_size for path in delete if path.exists())

if apply:
    for path in delete:
        path.unlink()

after_files = before_files - len(delete) if apply else before_files
after_bytes = before_bytes - reclaimed if apply else before_bytes
mode = "applied" if apply else "dry-run"
print(f"{mode}: candidates={len(delete)} files={before_files}->{after_files} bytes={before_bytes}->{after_bytes} reclaimed={reclaimed if apply else 0}")
for path in sorted(delete):
    print(f"  {'deleted' if apply else 'would delete'} {path.relative_to(root)}")
PY
