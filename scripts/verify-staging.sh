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
  [[ -n "${SUPABASE_DB_URL:-}" ]] || fail "SUPABASE_DB_URL (session pooler, port 5432) is required to run the worker drill"
fi

echo "Tier 2: staging ref verified"

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
      '((.status == "ok") or (.status == "degraded")) and (.build_sha == $expected_sha)' >/dev/null; then
      break
    fi
  fi
  [[ "$attempt" -lt "$health_attempts" ]] || fail "staging health did not serve expected revision ${expected_sha}"
  sleep 10
done
printf '%s\n' "$health_json" | ./scripts/assert-health.sh root
VERIFY_STAGING_HEALTH_ASSERTIONS+=("/health")
ingestion_json=$(curl --fail --silent --show-error "$ingestion_url")
# Degradations that are never acceptable whatever the worker posture. Stale
# polling and due integrations are expected with background processing off;
# dead-lettered, stale or unclaimable work is not.
printf '%s\n' "$ingestion_json" | ./scripts/assert-health.sh work-state
VERIFY_STAGING_HEALTH_ASSERTIONS+=("/health/ingestion")
egress_json=$(curl --fail --silent --show-error "$egress_url")
printf '%s\n' "$ingestion_json"
printf '%s\n' "$egress_json"

# D4: the deployed staging service runs on Render's FREE plan and spins down
# after ~15 minutes idle, so it cannot hold workers on. Asserting that posture
# against the deployed service would be asserting something staging does not
# have. Worker properties are proven instead by drill-staging-workers.sh, which
# runs selko.worker_app from this machine against staging Supabase over the real
# Supavisor session pooler.
#
# What that covers: real Postgres, real LISTEN/NOTIFY, real leases, real
# generation fencing, real expiry reclaim.
# What it does NOT cover: Render's memory ceiling, and the deployed service's
# own worker posture. Nothing below may claim otherwise.
echo "NOTE: staging runs with background processing off by design (Render free plan)."
echo "      Worker behaviour is proven by ./scripts/drill-staging-workers.sh, not by"
echo "      the deployed service's /health/ingestion."

if [[ "${STAGING_REQUIRE_WORKERS:-1}" == "1" ]]; then
  # Runs the entire drill suite with a live worker attached to staging, so it
  # is what proves the acceptance drill too.
  ./scripts/drill-staging-workers.sh
  VERIFY_STAGING_DRILLS+=("staging-worker-drill" "state-ownership-acceptance-drill")
fi

# The Gmail token is a precondition for the real-Gmail staging tests only. It
# was previously synced as the very first thing this script did, so an expired
# test token failed the whole run before a single migration was pushed or a
# single health assertion made -- and the reported cause was OAuth, not
# whatever the change under test actually did. It is still a hard failure, just
# attributed to the thing that needs it.
uv run python -m cli.cli_seed_tokens --sync --provider gmail

# Serial, deliberately. These tests share one cloud database, and -n auto
# had them competing for the same rows -- the same failure mode that made
# the worker drill red. (It also never ran: pytest-xdist was declared in
# backend's test extra but `uv sync --extra test` resolves the ROOT
# project's extra, which does not list it, so CI died on `unrecognized
# arguments: -n`.)
ENVIRONMENT=staging uv run pytest backend/tests/integration/ -m staging -v --tb=short
