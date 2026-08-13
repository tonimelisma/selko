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
  # JSON status reports the core services' health without treating disabled
  # optional services (pooler/imgproxy) as a failed local database.
  if ! supabase status -o json >/dev/null 2>&1; then
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
  uv run python -m cli.cli_seed_tokens --from staging --to development --provider gmail
}

verify_backend() {
  ./scripts/check-migration-order.sh main
  require_local_supabase
  supabase db reset
  prepare_local_integration_fixtures
  uv run pytest backend/tests/ -m "not integration"
  uv run pytest backend/tests/integration/ -m "not staging" -v --tb=short
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
