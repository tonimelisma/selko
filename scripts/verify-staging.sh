#!/usr/bin/env bash
# Tier 2 staging verification. This script is intentionally incapable of
# targeting production: it requires both the staging environment and ref.
set -euo pipefail

STAGING_REF="lxmysergoeaegxlyfzwk"
PRODUCTION_REF="khahcozfbnpykspvatrg"
LINKED_REF_FILE="supabase/.temp/project-ref"

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
[[ "${STAGING_APPLY_MIGRATIONS:-}" == "1" ]] || fail "set STAGING_APPLY_MIGRATIONS=1 after reviewing the migration dry-run"

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
for attempt in $(seq 1 30); do
  if curl --fail --silent --show-error --output /dev/null "$health_url"; then
    break
  fi
  [[ "$attempt" -lt 30 ]] || fail "staging health did not become ready"
  sleep 10
done
curl --fail --silent --show-error "$ingestion_url"
curl --fail --silent --show-error "$egress_url"

ENVIRONMENT=staging uv run pytest backend/tests/integration/ -m staging -v --tb=short -n auto
