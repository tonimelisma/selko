#!/usr/bin/env bash
# Durability drill 9a: kill-mid-pass lease-recovery
#
# Proves the core v2 promise: a worker dying mid-pass loses nothing and
# duplicates nothing. Uses local Supabase (supabase start) with a faked
# slow provider, SIGKILLs the runtime while a lease is held, starts a
# second instance, and asserts the lease is reclaimed after expiry and
# every discovered identity is acquired exactly once.
#
# Prerequisites:
#   - supabase start && supabase db reset (local)
#   - .env with local Supabase URL/keys (npm run dev uses same)
#   - No staging/prod credentials are used or printed.
#
# Usage: ENVIRONMENT=staging ./scripts/drill-lease-recovery.sh
# Exit 0 only when the staging drill suite passes.

set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

if [[ "${ENVIRONMENT:-}" != "staging" ]]; then
  echo "ERROR: ENVIRONMENT=staging is required" >&2
  exit 1
fi

echo "==> Drill 9a: kill-mid-pass lease recovery"
echo "    Local Supabase must be running (supabase status)"

# 1. Seed a fake integration and provider messages via a Python harness that
#    inserts directly through the service role client. The harness fakes a slow
#    provider by sleeping inside discover (patched time.sleep).
if ! command -v supabase >/dev/null 2>&1; then
  echo "ERROR: supabase CLI not found" >&2
  exit 1
fi

# Check local Supabase is reachable. CLI status is TTY-sensitive and can
# return non-zero when optional services are stopped, so inspect the required
# database and gateway container health instead.
db_health="$(docker inspect -f '{{.State.Health.Status}}' supabase_db_selko 2>/dev/null || true)"
gateway_health="$(docker inspect -f '{{.State.Health.Status}}' supabase_kong_selko 2>/dev/null || true)"
if [[ "$db_health" != "healthy" || "$gateway_health" != "healthy" ]]; then
  echo "ERROR: supabase status failed — is local Supabase running?" >&2
  exit 1
fi

echo "==> Running the ten-step staging acceptance drill"
uv run pytest backend/tests/drills/test_acceptance_drill.py -m "staging and drill" -v --tb=short
