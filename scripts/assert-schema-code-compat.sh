#!/usr/bin/env bash
# R5 — migrations must not be behind code.
#
# Compares migration VERSIONS between the repository and the linked Supabase
# project, using the CLI's own local/remote correlation per row (not a
# separate filesystem scan) so there is no ambiguity about which column a
# version came from.
#
# Usage: ./scripts/assert-schema-code-compat.sh --linked
#
# There is no mode that passes without checking. If the check cannot run,
# it fails. A gate that exits 0 when it cannot verify is not a gate.
set -euo pipefail

# find_missing_versions — reads `supabase migration list --linked
# --output-format json` from stdin, prints one missing (local-only) 14-digit
# version per line.
#
# F1.2 (D2): the old implementation grepped 14-digit numbers out of the
# whole CLI output, which contains BOTH the local and remote columns per
# row — so a migration missing only on the remote still had its version
# grepped out of the local column, and the gate could never fail. This
# parses the JSON structurally and looks at .remote specifically.
#
# Exit status distinguishes "parsed cleanly, nothing missing" (0, empty
# stdout) from "could not parse the input at all" (2, no stdout) — a
# malformed or empty response must never be read as "nothing missing."
find_missing_versions() {
  if ! command -v jq >/dev/null 2>&1; then
    echo "jq is required to parse migration list output — not installed" >&2
    return 2
  fi
  local input
  input=$(cat)
  # jq treats empty stdin as "zero JSON values, exit 0" — not a parse error —
  # so an empty response would otherwise read as "nothing missing."
  if [[ -z "${input//[[:space:]]/}" ]]; then
    echo "empty migration list output — cannot verify" >&2
    return 2
  fi
  echo "$input" | jq -r '
    if (.migrations | type) != "array" then
      error("malformed migration list output: no .migrations array")
    else
      .migrations[]
      | select((.remote // "") == "")
      | .local
      | select(test("^[0-9]{14}$"))
    end
  '
}

main() {
  if [[ "${1:-}" != "--linked" ]]; then
    echo "❌ FAIL: --linked is required. A local-only check proves nothing."
    exit 1
  fi

  if ! command -v supabase >/dev/null 2>&1; then
    echo "❌ FAIL: supabase CLI not installed — cannot verify remote schema."
    exit 1
  fi

  local migration_list_args=(migration list --linked --output-format json)
  # Supabase's legacy linked-project path attempts to initialize a temporary
  # login role before reading migrations. Staging currently rejects that role
  # mutation, while a direct password-authenticated migration query works.
  # Keep token-based linking as the fallback for environments that do not
  # provide a database password.
  if [[ -n "${SUPABASE_DB_PASSWORD:-}" ]]; then
    migration_list_args+=(--password "${SUPABASE_DB_PASSWORD}")
  fi

  if ! REMOTE_RAW=$(supabase "${migration_list_args[@]}" 2>&1); then
    echo "❌ FAIL: could not list linked migrations."
    echo "   Run 'supabase link' and export SUPABASE_ACCESS_TOKEN."
    echo "$REMOTE_RAW"
    exit 1
  fi

  # The password-authenticated Supabase CLI path writes connection progress
  # before the JSON payload. Strip only leading non-JSON lines, then validate
  # the complete payload with jq so noisy output cannot become a false pass.
  local remote_json
  if ! remote_json=$(printf '%s\n' "$REMOTE_RAW" | sed -n '/^[[:space:]]*{/,$p' | jq -c .); then
    echo "❌ FAIL: could not parse migration list output as JSON — cannot verify."
    echo "$REMOTE_RAW"
    exit 1
  fi

  if ! MISSING=$(printf '%s\n' "$remote_json" | find_missing_versions); then
    echo "❌ FAIL: could not parse migration list output as JSON — cannot verify."
    echo "$REMOTE_RAW"
    exit 1
  fi

  if [[ -n "$MISSING" ]]; then
    echo "❌ FAIL: these migrations exist in the repo but not on the remote:"
    echo "$MISSING" | sed 's/^/   /'
    echo "   Run 'supabase db push' before deploying this code."
    exit 1
  fi

  TOTAL=$(printf '%s\n' "$remote_json" | jq '.migrations | length')
  echo "✅ Every local migration is applied remotely ($TOTAL total)"
}

# Allow sourcing this file (e.g. from tests) without running main.
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
  main "$@"
fi
