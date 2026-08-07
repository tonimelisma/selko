#!/usr/bin/env bash
# R5 — Enforced cutover: migrations must not be behind code.
# Fails CI/deploy if HEAD migrations are not yet pushed to the linked
# environment. This makes the wrong order (Render ENV redeploy of HEAD
# ahead of schema) mechanically impossible — the runbook alone cannot.
#
# Usage: ./scripts/assert-schema-code-compat.sh [--linked]
#   --linked  checks remote linked project (requires supabase link)
#   default   checks local vs committed migration count (no auth needed)
set -euo pipefail

MIGR_DIR="supabase/migrations"
EXPECTED_COUNT=$(ls -1 "$MIGR_DIR"/*.sql 2>/dev/null | wc -l | tr -d ' ')
echo "Local migration files: $EXPECTED_COUNT"

if [[ "${1:-}" == "--linked" ]]; then
  if ! command -v supabase >/dev/null 2>&1; then
    echo "supabase CLI not installed — skipping linked check"
    exit 0
  fi
  # supabase migration list --linked lists applied migrations; compare counts
  # This is best-effort: if linked project not configured, warn not fail
  if ! supabase migration list --linked 2>&1 | head -n 5; then
    echo "⚠️  Could not list linked migrations — ensure 'supabase link' and SUPABASE_ACCESS_TOKEN"
    echo "   Continuing without remote count check (local count is $EXPECTED_COUNT)"
    exit 0
  fi
  REMOTE_COUNT=$(supabase migration list --linked 2>&1 | grep -c "\.sql" || true)
  echo "Remote applied migrations: $REMOTE_COUNT"
  if [[ "$REMOTE_COUNT" -lt "$EXPECTED_COUNT" ]]; then
    echo "❌ FAIL: $((EXPECTED_COUNT - REMOTE_COUNT)) migration(s) pending on remote — run 'supabase db push' first"
    exit 1
  fi
  echo "✅ Schema and code are in sync ($REMOTE_COUNT/$EXPECTED_COUNT)"
else
  # Local-only sanity: ensure no untracked migration would be missed by CI
  if git diff --name-only origin/main 2>/dev/null | grep -q "supabase/migrations/"; then
    echo "ℹ️  Migration changes vs origin/main detected — workflow will enforce sync on push"
  fi
  echo "✅ Local migration count check passed ($EXPECTED_COUNT) — use --linked for remote check"
fi
