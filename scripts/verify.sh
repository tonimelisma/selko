#!/usr/bin/env bash
# Tier 1 local execution gate.
#
# The backend runs on one SQLite file. Every test that touches the database gets
# a fresh file with every migration applied (backend/tests/sqlite_fixtures.py),
# so the gate needs no service: it runs the unit and integration suites and
# records an evidence manifest keyed by the migrations' content.
set -euo pipefail

usage() {
  echo "Usage: ./scripts/verify.sh [backend|frontend|all]"
}

VERIFY_SHA="$(git rev-parse HEAD)"
VERIFY_DIR=".verify"
VERIFY_MANIFEST="${VERIFY_DIR}/backend-${VERIFY_SHA}.json"
VERIFY_UNIT_XML="${TMPDIR:-/tmp}/selko-unit-${VERIFY_SHA}.xml"
VERIFY_INTEGRATION_XML="${TMPDIR:-/tmp}/selko-integration-${VERIFY_SHA}.xml"
VERIFY_SCHEMA_HASH=""
VERIFY_SEED="${PYTEST_RANDOMLY_SEED:-$RANDOM}"

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
  VERIFY_SCHEMA_HASH="$(cat backend/selko/db/migrations/*.sql | shasum -a 256 | awk '{print $1}')"
  echo "Running backend unit tests with random seed ${VERIFY_SEED}"
  run_pytest_with_evidence "$VERIFY_UNIT_XML" backend/tests/ -m "not integration" \
    --randomly-seed="${VERIFY_SEED}"
  echo "Running backend integration tests with random seed ${VERIFY_SEED}"
  run_pytest_with_evidence "$VERIFY_INTEGRATION_XML" backend/tests/integration/ -v --tb=short \
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
  [[ "$#" -eq 0 ]] || { usage >&2; exit 1; }
  case "$mode" in
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

# Sourcing this file exposes the helpers without running the gate.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
