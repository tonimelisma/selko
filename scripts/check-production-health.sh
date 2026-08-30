#!/usr/bin/env bash
# Check a running deployment against the invariants in assert-health.sh.
#
# Usage:
#   ./scripts/check-production-health.sh                    # production
#   ./scripts/check-production-health.sh <base-url>
#
# Why this exists: the invariants already existed and were correct, but were
# wired only to staging. Production went unchecked, and a count the assertions
# call "NEVER acceptable" sat true there for an unknown period. A check that is
# never run against the environment that matters is not a check.
#
# That first production run also showed the count itself was wrong: it merged
# terminal failures (permanent, expected) with stuck pending rows (actionable).
# 20260901000001 split them; only the actionable half is asserted.
#
# Production is https://api.selkoapp.com. The .onrender.com host 404s and the
# primary domain appears only in Render's deploy logs, which is how two
# separate checks were accidentally aimed at *staging* and its degraded state
# briefly mistaken for production's.
set -uo pipefail

BASE_URL="${1:-https://api.selkoapp.com}"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CURL=(curl -fsS --max-time 30)
failures=0

fetch() {
    local path="$1"
    "${CURL[@]}" "${BASE_URL}${path}" 2>/dev/null
}

check() {
    local surface="$1" path="$2"
    local body
    if ! body="$(fetch "$path")"; then
        echo "FAIL  ${surface}: could not reach ${BASE_URL}${path}"
        failures=$((failures + 1))
        return
    fi
    if printf '%s\n' "$body" | "$PROJECT_ROOT/scripts/assert-health.sh" "$surface" >/dev/null 2>&1; then
        echo "OK    ${surface}"
    else
        echo "FAIL  ${surface}"
        printf '%s\n' "$body" | "$PROJECT_ROOT/scripts/assert-health.sh" "$surface" 2>&1 | sed 's/^/      /'
        failures=$((failures + 1))
    fi
}

echo "Checking ${BASE_URL}"
check root       /health
check work-state /health/ingestion
check ingestion  /health/ingestion

echo
if [ "$failures" -gt 0 ]; then
    echo "${failures} health invariant(s) failed at ${BASE_URL}"
    exit 1
fi
echo "All health invariants hold at ${BASE_URL}"
