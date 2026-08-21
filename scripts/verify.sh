#!/usr/bin/env bash
# Tier 1 local execution gate.
#
# A backend verification is not complete until the local Supabase database has
# applied every migration and the unit plus non-staging integration suites
# have run against it. This script fails closed when Docker/Supabase is not
# available; a skipped database setup is never reported as a green gate.
set -euo pipefail

usage() {
  echo "Usage: ./scripts/verify.sh [backend|staging|frontend|all]"
}

require_local_supabase() {
  # Supabase CLI status output is TTY-sensitive and returns non-zero in
  # redirected/non-TTY mode when optional services are stopped. Inspect the
  # health state of the required database and gateway containers instead of
  # treating that exit status as proof that local Postgres is unavailable.
  local db_health gateway_health
  db_health="$(docker inspect -f '{{.State.Health.Status}}' supabase_db_selko 2>/dev/null || true)"
  gateway_health="$(docker inspect -f '{{.State.Health.Status}}' supabase_kong_selko 2>/dev/null || true)"
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
    echo "WARN: no live Gmail token; real-Gmail tests will skip. Gate continues." >&2
    export SELKO_SKIP_REAL_GMAIL=1
  fi
}

verify_backend() {
  ./scripts/check-migration-order.sh main
  require_local_supabase
  supabase db reset
  prepare_local_integration_fixtures
  uv run pytest backend/tests/ -m "not integration"
  local integration_seed="${PYTEST_RANDOMLY_SEED:-$RANDOM}"
  local integration_log
  integration_log="$(mktemp)"
  trap 'rm -f "$integration_log"' RETURN
  echo "Running backend integration tests with random seed ${integration_seed}"
  uv run pytest backend/tests/integration/ -m "not staging" -v --tb=short \
    --randomly-seed="${integration_seed}" 2>&1 | tee "$integration_log"
  local skip_count
  skip_count="$(grep -oE '[0-9]+ skipped' "$integration_log" | tail -1 | awk '{print $1}')"
  skip_count="${skip_count:-0}"
  echo "Backend integration summary: seed=${integration_seed} skipped=${skip_count}"
  trap - RETURN
  rm -f "$integration_log"
}

verify_frontend() {
  npm --prefix frontend run test:unit
  npm --prefix frontend run check
}

main() {
  case "${1:-}" in
    backend)
      verify_backend
      ;;
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
