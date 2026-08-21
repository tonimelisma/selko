#!/usr/bin/env bash
# Tier 1 local execution gate.
#
# A backend verification is not complete until the local Supabase database has
# applied every migration and the unit plus non-staging integration suites
# have run against it. This script fails closed when Docker/Supabase is not
# available; a skipped database setup is never reported as a green gate.
set -euo pipefail

usage() {
  echo "Usage: ./scripts/verify.sh backend [--accept-stale-gmail-token]"
  echo "       ./scripts/verify.sh [staging|frontend|all]"
}

VERIFY_SHA="$(git rev-parse HEAD)"
VERIFY_DIR=".verify"
VERIFY_MANIFEST="${VERIFY_DIR}/backend-${VERIFY_SHA}.json"
VERIFY_UNIT_XML="${TMPDIR:-/tmp}/selko-unit-${VERIFY_SHA}.xml"
VERIFY_INTEGRATION_XML="${TMPDIR:-/tmp}/selko-integration-${VERIFY_SHA}.xml"
VERIFY_SCHEMA_HASH=""
VERIFY_SEED="${PYTEST_RANDOMLY_SEED:-$RANDOM}"
VERIFY_ACCEPTED_DEGRADATIONS=""

write_manifest_on_exit() {
  local status="$1"
  local dirty_tree
  dirty_tree="$(git status --porcelain)"
  local manifest_status=0
  set +e
  local command=(
    python3 scripts/write-verification-manifest.py
    --manifest "$VERIFY_MANIFEST"
    --skip-budget backend/tests/skip_budget.toml
    --status "$status"
    --git-sha "$VERIFY_SHA"
    --seed "$VERIFY_SEED"
  )
  [[ -z "$dirty_tree" ]] || command+=(--dirty-tree)
  [[ -n "$VERIFY_SCHEMA_HASH" ]] && command+=(--schema-hash "$VERIFY_SCHEMA_HASH")
  if [[ -n "$VERIFY_ACCEPTED_DEGRADATIONS" ]]; then
    command+=(--accepted-degradation "$VERIFY_ACCEPTED_DEGRADATIONS")
  fi
  command+=("$VERIFY_UNIT_XML" "$VERIFY_INTEGRATION_XML")
  "${command[@]}"
  manifest_status=$?
  set -e
  if [[ "$status" -eq 0 && "$manifest_status" -ne 0 ]]; then
    status="$manifest_status"
  fi
  rm -f "$VERIFY_UNIT_XML" "$VERIFY_INTEGRATION_XML"
  trap - EXIT
  exit "$status"
}

require_local_supabase() {
  # Supabase CLI status output is TTY-sensitive and returns non-zero in
  # redirected/non-TTY mode when optional services are stopped. Inspect the
  # health state of the required database and gateway containers instead of
  # treating that exit status as proof that local Postgres is unavailable.
  local db_health gateway_health
  if db_health="$(docker inspect -f '{{.State.Health.Status}}' supabase_db_selko 2>/dev/null)"; then
    :
  else
    db_health=""
  fi
  if gateway_health="$(docker inspect -f '{{.State.Health.Status}}' supabase_kong_selko 2>/dev/null)"; then
    :
  else
    gateway_health=""
  fi
  if [[ "$db_health" != "healthy" || "$gateway_health" != "healthy" ]]; then
    echo "ERROR: Local Supabase is not running. Start it with: supabase start" >&2
    exit 1
  fi
}

prepare_local_integration_fixtures() {
  echo "Preparing local integration fixtures..."
  uv run python -c '
from selko.config import load_config
from selko.services.users import create_user

config = load_config(env_override="development")
if not config.test_user_email or not config.test_user_password:
    raise SystemExit("ERROR: .env must define TEST_USER_EMAIL and TEST_USER_PASSWORD")
create_user(
    config,
    email=config.test_user_email,
    password=config.test_user_password,
    auto_confirm=True,
)
'
  # Local real-Gmail integration tests are development-only. After the reset,
  # development is always the missing side, so use the documented explicit
  # staging -> development copy rather than the bidirectional sync command,
  # which intentionally refuses when the source access token is near expiry.
  # The CLI and imported implementation both refuse production.
  if ! uv run python -m cli.cli_seed_tokens --from staging --to development --provider gmail; then
    if [[ "${ACCEPT_STALE_GMAIL_TOKEN:-0}" != "1" ]]; then
      echo "ERROR: no live Gmail token; rerun with --accept-stale-gmail-token only after recording the degradation." >&2
      return 1
    fi
    echo "WARN: accepting stale/missing Gmail token; real-Gmail tests are explicitly degraded." >&2
    VERIFY_ACCEPTED_DEGRADATIONS="real-gmail-token-unavailable"
    export SELKO_SKIP_REAL_GMAIL=1
  fi
}

run_pytest_with_evidence() {
  local junit_path="$1"
  shift
  set +e
  uv run pytest "$@" --junitxml="$junit_path"
  local status=$?
  set -e
  return "$status"
}

verify_backend() {
  trap 'write_manifest_on_exit "$?"' EXIT
  ./scripts/check-migration-order.sh main
  require_local_supabase
  supabase db reset
  prepare_local_integration_fixtures
  local migration_output
  migration_output="$(supabase migration list --local)"
  VERIFY_SCHEMA_HASH="$(printf '%s\n' "$migration_output" | shasum -a 256 | awk '{print $1}')"
  echo "Running backend unit tests with random seed ${VERIFY_SEED}"
  run_pytest_with_evidence "$VERIFY_UNIT_XML" backend/tests/ -m "not integration" \
    --randomly-seed="${VERIFY_SEED}"
  echo "Running backend integration tests with random seed ${VERIFY_SEED}"
  run_pytest_with_evidence "$VERIFY_INTEGRATION_XML" backend/tests/integration/ -m "not staging" -v --tb=short \
    --randomly-seed="${VERIFY_SEED}"
}

verify_frontend() {
  npm --prefix frontend run test:unit
  npm --prefix frontend run check
}

main() {
  local mode="${1:-}"
  if [[ "$#" -gt 0 ]]; then
    shift
  fi
  if [[ "$mode" == "backend" ]]; then
    if [[ "${1:-}" == "--accept-stale-gmail-token" ]]; then
      ACCEPT_STALE_GMAIL=1
      shift
    fi
    [[ "$#" -eq 0 ]] || { usage >&2; exit 1; }
    verify_backend
    return
  fi
  case "$mode" in
    staging)
      ./scripts/verify-staging.sh
      ;;
    frontend)
      verify_frontend
      ;;
    all)
      verify_backend
      verify_frontend
      ;;
    *)
      usage >&2
      exit 1
      ;;
  esac
}

main "$@"
