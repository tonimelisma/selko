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
# Usage: ./scripts/drill-lease-recovery.sh
# Exit 0 on success, non-zero with diagnostics on failure.

set -euo pipefail

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

echo "==> Drill 9a: kill-mid-pass lease recovery"
echo "    Local Supabase must be running (supabase status)"

# 1. Seed a fake integration and provider messages via a Python harness that
#    inserts directly through the service role client. The harness fakes a slow
#    provider by sleeping inside discover (patched time.sleep).
if ! command -v supabase >/dev/null 2>&1; then
  echo "ERROR: supabase CLI not found" >&2
  exit 1
fi

# Check local Supabase is reachable
if ! supabase status >/dev/null 2>&1; then
  echo "ERROR: supabase status failed — is local Supabase running?" >&2
  exit 1
fi

# Run the Python drill harness. It:
#   - creates a test user + gmail integration (service role)
#   - inserts a sync state with next_poll_at = now()
#   - starts IngestionRuntime with a patched discover that sleeps 5s per folder
#   - SIGKILLs the process mid-pass (lease held)
#   - starts a second runtime with normal discover and waits for lease expiry
#   - asserts: lease reclaimed, items count unchanged, no duplicate (integration_id, provider_message_id)
echo "==> Running Python harness (backend/tests/integration/test_integration_ingestion_drill.py::test_kill_mid_pass)"

uv run pytest backend/tests/integration/test_integration_ingestion_drill.py::test_kill_mid_pass -v --tb=short

echo "==> Drill 9a PASSED: lease reclaimed, no duplicates, no lost identities"
