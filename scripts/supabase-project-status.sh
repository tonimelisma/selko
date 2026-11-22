#!/usr/bin/env bash
# Report a hosted Supabase project's status through the Management API (HTTPS).
#
# Usage: ./scripts/supabase-project-status.sh <project-ref>
#
# Exit codes -- distinct on purpose, so a caller can tell "paused" (an owner
# decision: staging is paused today) from "could not ask" (a missing token or
# an unreachable API), which must stay red:
#   0  ACTIVE_HEALTHY
#   3  paused or pausing (INACTIVE, PAUSING, PAUSED)
#   1  anything else, including any failure to get an answer
#
# Authentication: SUPABASE_ACCESS_TOKEN when set (GitHub Actions secret).
# In a cloud session the token is a network secret the proxy adds to requests
# for api.supabase.com, so the request carries no header of its own there.
# Prints the status word only -- never the response body, which names the
# project's organization and owner.
set -uo pipefail

ref="${1:-}"
[[ "$ref" =~ ^[a-z0-9]{20}$ ]] || { echo "usage: $0 <20-character project ref>" >&2; exit 1; }

headers=()
[[ -n "${SUPABASE_ACCESS_TOKEN:-}" ]] && headers=(-H "Authorization: Bearer ${SUPABASE_ACCESS_TOKEN}")

if ! body="$(curl -fsS --max-time 30 "${headers[@]}" "https://api.supabase.com/v1/projects/${ref}")"; then
  echo "could not read project ${ref} from the Supabase Management API" >&2
  exit 1
fi
status="$(printf '%s' "$body" | jq -r '.status // empty')"
echo "${status:-unknown}"
case "$status" in
  ACTIVE_HEALTHY) exit 0 ;;
  INACTIVE | PAUSING | PAUSED) exit 3 ;;
  *) exit 1 ;;
esac
