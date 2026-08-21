#!/usr/bin/env bash
# Tier 2 staging verification. This script is intentionally incapable of
# targeting production: it requires both the staging environment and ref.
set -euo pipefail

STAGING_REF="lxmysergoeaegxlyfzwk"
PRODUCTION_REF="khahcozfbnpykspvatrg"
LINKED_REF_FILE="supabase/.temp/project-ref"
VERIFY_STAGING_SHA="$(git rev-parse HEAD)"
VERIFY_STAGING_MANIFEST=".verify/staging-${VERIFY_STAGING_SHA}.json"
VERIFY_STAGING_HEALTH_ASSERTIONS=()
VERIFY_STAGING_DRILLS=()

write_staging_manifest() {
  local status="$1"
  python3 - "$VERIFY_STAGING_MANIFEST" "$status" "$VERIFY_STAGING_SHA" \
    "${VERIFY_STAGING_HEALTH_ASSERTIONS[*]}" "${VERIFY_STAGING_DRILLS[*]}" <<'PY'
import json
import sys
from pathlib import Path

manifest, status, sha, health, drills = sys.argv[1:]
Path(manifest).parent.mkdir(parents=True, exist_ok=True)
payload = {
    "gate": "staging",
    "status": "passed" if status == "0" else "failed",
    "exit_code": int(status),
    "git_sha": sha,
    "health_assertions": [item for item in health.split() if item],
    "drills": [item for item in drills.split() if item],
}
Path(manifest).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
PY
}

trap 'write_staging_manifest "$?"' EXIT

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

[[ "${ENVIRONMENT:-}" == "staging" ]] || fail "ENVIRONMENT=staging is required"
[[ -f "$LINKED_REF_FILE" ]] || fail "linked project ref is unknown; run supabase link --project-ref $STAGING_REF"
linked_ref=$(tr -d '[:space:]' < "$LINKED_REF_FILE")
[[ "$linked_ref" != "$PRODUCTION_REF" ]] || fail "production project ref detected; refusing to continue"
[[ "$linked_ref" == "$STAGING_REF" ]] || fail "linked project is not the staging project"

[[ -n "${STAGING_RENDER_DEPLOY_HOOK:-}" ]] || fail "STAGING_RENDER_DEPLOY_HOOK is required"
[[ -n "${STAGING_API_BASE_URL:-}" ]] || fail "STAGING_API_BASE_URL is required"
[[ -n "${SUPABASE_DB_PASSWORD:-}" ]] || fail "SUPABASE_DB_PASSWORD is required for staging migration verification"
[[ "${STAGING_APPLY_MIGRATIONS:-}" == "1" ]] || fail "set STAGING_APPLY_MIGRATIONS=1 after reviewing the migration dry-run"
case "${STAGING_REQUIRE_WORKERS:-1}" in
  0|1) ;;
  *) fail "STAGING_REQUIRE_WORKERS must be 0 or 1" ;;
esac
if [[ "${STAGING_REQUIRE_WORKERS:-1}" == "1" ]]; then
  [[ -n "${SUPABASE_DB_URL:-}" ]] || fail "SUPABASE_DB_URL is required for worker and drill verification"
fi

echo "Tier 2: staging ref verified"
uv run python -m cli.cli_seed_tokens --sync --provider gmail

if ! gate_output=$(./scripts/assert-schema-code-compat.sh --linked 2>&1); then
  if ! grep -q "these migrations exist in the repo but not on the remote" <<<"$gate_output"; then
    echo "Schema gate failed for a reason other than pending migrations; refusing to continue." >&2
    fail "schema gate could not verify staging"
  fi
  echo "Schema gate reports pending migrations; showing the dry-run before applying them."
fi
supabase db push --dry-run
supabase db push
./scripts/assert-schema-code-compat.sh --linked

# Do not print the hook URL or response: it is a secret-bearing deployment
# credential. A successful POST is sufficient evidence that the deploy began.
curl --fail --silent --show-error --output /dev/null -X POST "$STAGING_RENDER_DEPLOY_HOOK"

health_url="${STAGING_API_BASE_URL%/}/health"
ingestion_url="${STAGING_API_BASE_URL%/}/health/ingestion"
egress_url="${STAGING_API_BASE_URL%/}/health/egress"
expected_sha="${STAGING_EXPECTED_SHA:-$(git rev-parse HEAD)}"
health_json=""
health_attempts="${STAGING_HEALTH_ATTEMPTS:-60}"
for attempt in $(seq 1 "$health_attempts"); do
  if health_json=$(curl --fail --silent --show-error "$health_url"); then
    if printf '%s\n' "$health_json" | jq -e --arg expected_sha "$expected_sha" \
      '(.status == "ok") and (.build_sha == $expected_sha)' >/dev/null; then
      break
    fi
  fi
  [[ "$attempt" -lt "$health_attempts" ]] || fail "staging health did not serve expected revision ${expected_sha}"
  sleep 10
done
printf '%s\n' "$health_json" | ./scripts/assert-staging-health.sh root
VERIFY_STAGING_HEALTH_ASSERTIONS+=("/health")
ingestion_json=$(curl --fail --silent --show-error "$ingestion_url")
egress_json=$(curl --fail --silent --show-error "$egress_url")
printf '%s\n' "$ingestion_json"
printf '%s\n' "$egress_json"

if [[ "${STAGING_REQUIRE_WORKERS:-0}" == "1" ]]; then
  printf '%s\n' "$ingestion_json" | ./scripts/assert-staging-health.sh ingestion
  VERIFY_STAGING_HEALTH_ASSERTIONS+=("/health/ingestion")
  printf '%s\n' "$egress_json" | ./scripts/assert-staging-health.sh egress
  VERIFY_STAGING_HEALTH_ASSERTIONS+=("/health/egress")
fi

ENVIRONMENT=staging uv run pytest backend/tests/integration/ -m staging -v --tb=short -n auto
RUN_ACCEPTANCE_DRILL=1 uv run pytest backend/tests/drills/test_acceptance_drill.py -m "staging and drill" -v --tb=short
VERIFY_STAGING_DRILLS+=("state-ownership-acceptance-drill")
