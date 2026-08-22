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
VERIFY_FIXTURE_XML="${TMPDIR:-/tmp}/selko-screenshot-fixtures-${VERIFY_SHA}.xml"
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
  command+=("$VERIFY_UNIT_XML" "$VERIFY_INTEGRATION_XML" "$VERIFY_FIXTURE_XML")
  "${command[@]}"
  manifest_status=$?
  set -e
  if [[ "$status" -eq 0 && "$manifest_status" -ne 0 ]]; then
    status="$manifest_status"
  fi
  rm -f "$VERIFY_UNIT_XML" "$VERIFY_INTEGRATION_XML" "$VERIFY_FIXTURE_XML"
  trap - EXIT
  exit "$status"
}

DOCKER_PROBE_TIMEOUT_SECONDS="${DOCKER_PROBE_TIMEOUT_SECONDS:-15}"

# Run one docker command under a wall-clock bound.
#
# Docker Desktop can be fully "running" -- app, com.docker.backend and
# com.docker.virtualization all alive -- while its VM disk has taken an I/O
# fault, at which point every daemon call blocks forever rather than failing.
# An unbounded probe turns the gate from "refuses with a reason" into "hangs
# with no output", which is strictly worse: it consumes the whole CI budget and
# is locally indistinguishable from a slow suite.
#
# macOS ships no timeout(1), so the bound is implemented here rather than
# assumed. Echoes the command's stdout on success; returns 124 on timeout.
bounded_docker() {
  local output_file status waited pid
  output_file="$(mktemp)"
  docker "$@" >"$output_file" 2>/dev/null &
  pid=$!
  waited=0
  while kill -0 "$pid" 2>/dev/null; do
    if [[ "$waited" -ge "$DOCKER_PROBE_TIMEOUT_SECONDS" ]]; then
      kill -9 "$pid" 2>/dev/null || :
      wait "$pid" 2>/dev/null || :
      rm -f "$output_file"
      return 124
    fi
    sleep 1
    waited=$((waited + 1))
  done
  status=0
  wait "$pid" || status=$?
  cat "$output_file"
  rm -f "$output_file"
  return "$status"
}

fail_unresponsive_daemon() {
  echo "ERROR: the Docker daemon did not answer within ${DOCKER_PROBE_TIMEOUT_SECONDS}s." >&2
  echo "       Docker Desktop reports itself as running even when its VM disk has" >&2
  echo "       taken an I/O fault. Check the tail of" >&2
  echo "       ~/Library/Containers/com.docker.docker/Data/log/vm/console.log for" >&2
  echo "       'EXT4-fs (vda1)' errors." >&2
  echo "       Repair: quit Docker Desktop and reopen it. If probes still hang," >&2
  echo "       use Docker Desktop -> Troubleshoot -> Clean / Purge data, then" >&2
  echo "       re-run 'supabase start'." >&2
  exit 1
}

require_local_supabase() {
  # Supabase CLI status output is TTY-sensitive and returns non-zero in
  # redirected/non-TTY mode when optional services are stopped. Inspect the
  # health state of the required database and gateway containers instead of
  # treating that exit status as proof that local Postgres is unavailable.
  local db_health gateway_health probe_status
  probe_status=0
  db_health="$(bounded_docker inspect -f '{{.State.Health.Status}}' supabase_db_selko)" || probe_status=$?
  [[ "$probe_status" -ne 124 ]] || fail_unresponsive_daemon
  [[ "$probe_status" -eq 0 ]] || db_health=""
  probe_status=0
  gateway_health="$(bounded_docker inspect -f '{{.State.Health.Status}}' supabase_kong_selko)" || probe_status=$?
  [[ "$probe_status" -ne 124 ]] || fail_unresponsive_daemon
  [[ "$probe_status" -eq 0 ]] || gateway_health=""
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
    -k "not test_screenshot_seed_has_complete_lane_and_work_state" \
    --randomly-seed="${VERIFY_SEED}"
  echo "Seeding screenshot fixtures through the application write paths"
  uv run python scripts/seed_screenshot_data.py seed --cleanup-first
  echo "Verifying the seeded screenshot fixtures"
  run_pytest_with_evidence "$VERIFY_FIXTURE_XML" \
    backend/tests/integration/test_integration_seed_fixtures.py -m integration -q
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

# Sourcing this file exposes the helpers without running the gate, so the gate
# contract test can drive bounded_docker against a stubbed daemon.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
