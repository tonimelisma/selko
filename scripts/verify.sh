#!/usr/bin/env bash
# Tier 1 local execution gate.
#
# A backend verification is not complete until the local Supabase database has
# applied every migration and the unit plus non-staging integration suites
# have run against it. This script fails closed when Docker/Supabase is not
# available; a skipped database setup is never reported as a green gate.
set -euo pipefail

usage() {
  echo "Usage: ./scripts/verify.sh [backend|frontend|all]"
}

require_local_supabase() {
  if ! supabase status >/dev/null 2>&1; then
    echo "ERROR: Local Supabase is not running. Start it with: supabase start" >&2
    exit 1
  fi
}

verify_backend() {
  ./scripts/check-migration-order.sh main
  require_local_supabase
  supabase db reset
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
