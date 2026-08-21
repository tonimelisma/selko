#!/usr/bin/env bash
# Assert the health invariants required by the staging worker-on gate.
#
# Usage:
#   ./scripts/assert-staging-health.sh ingestion < ingestion.json
#   ./scripts/assert-staging-health.sh egress < egress.json
#
# The endpoint responses are safe, content-free health payloads. Do not pass
# deployment hooks, connection strings, or other secret-bearing values here.
set -euo pipefail

surface="${1:-}"
case "$surface" in
  root)
    filter='(.status == "ok") and (.build_sha | type == "string" and length > 0)'
    failure="staging API health is not ok or does not publish a build SHA"
    ;;
  ingestion)
    filter='
      (.status == "ok") and
      (.background_processing_enabled == true) and
      (.tasks | type == "array" and length > 0 and all(.[]; .alive == true)) and
      (.listener | type == "object" and .connected == true)
    '
    failure="staging ingestion health does not prove the worker/listener is running"
    ;;
  egress)
    filter='(.transport == "asyncpg")'
    failure="staging egress health does not prove the asyncpg worker transport is active"
    ;;
  *)
    echo "ERROR: expected health surface 'root', 'ingestion', or 'egress'" >&2
    exit 2
    ;;
esac

command -v jq >/dev/null 2>&1 || {
  echo "ERROR: jq is required to validate staging health JSON" >&2
  exit 2
}

if ! jq -e "$filter" >/dev/null; then
  echo "ERROR: $failure" >&2
  exit 1
fi

echo "OK: staging $surface health invariants verified"
