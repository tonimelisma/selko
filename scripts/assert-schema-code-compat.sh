#!/usr/bin/env bash
# R5 — migrations must not be behind code.
#
# Compares migration VERSIONS (not counts) between the repository and the
# linked Supabase project. Any local version missing remotely is a failure.
#
# Usage: ./scripts/assert-schema-code-compat.sh --linked
#
# There is no mode that passes without checking. If the check cannot run,
# it fails. A gate that exits 0 when it cannot verify is not a gate.
set -euo pipefail

MIGR_DIR="supabase/migrations"

if [[ "${1:-}" != "--linked" ]]; then
  echo "❌ FAIL: --linked is required. A local-only check proves nothing."
  exit 1
fi

if ! command -v supabase >/dev/null 2>&1; then
  echo "❌ FAIL: supabase CLI not installed — cannot verify remote schema."
  exit 1
fi

LOCAL_VERSIONS=$(ls -1 "$MIGR_DIR"/*.sql | xargs -n1 basename | cut -d_ -f1 | sort -u)
LOCAL_COUNT=$(echo "$LOCAL_VERSIONS" | grep -c . || true)
echo "Local migration versions: $LOCAL_COUNT"

if ! REMOTE_RAW=$(supabase migration list --linked 2>&1); then
  echo "❌ FAIL: could not list linked migrations."
  echo "   Run 'supabase link' and export SUPABASE_ACCESS_TOKEN."
  echo "$REMOTE_RAW"
  exit 1
fi

REMOTE_VERSIONS=$(echo "$REMOTE_RAW" | grep -oE '[0-9]{14}' | sort -u)
REMOTE_COUNT=$(echo "$REMOTE_VERSIONS" | grep -c . || true)
echo "Remote applied versions: $REMOTE_COUNT"

MISSING=$(comm -23 <(echo "$LOCAL_VERSIONS") <(echo "$REMOTE_VERSIONS"))
if [[ -n "$MISSING" ]]; then
  echo "❌ FAIL: these migrations exist in the repo but not on the remote:"
  echo "$MISSING" | sed 's/^/   /'
  echo "   Run 'supabase db push' before deploying this code."
  exit 1
fi

echo "✅ Every local migration is applied remotely ($LOCAL_COUNT local, $REMOTE_COUNT remote)"
