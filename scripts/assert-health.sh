#!/usr/bin/env bash
# Assert the health invariants of a running deployment.
#
# Usage:
#   ./scripts/assert-health.sh root       < health.json
#   ./scripts/assert-health.sh work-state < ingestion.json
#   ./scripts/assert-health.sh ingestion  < ingestion.json
#   ./scripts/assert-health.sh egress     < egress.json
#
# These invariants were staging-only for their whole life, called by
# verify-staging.sh and CI and by nothing else. Nothing ever pointed them at
# production -- so `unclaimable_emails: 27`, a condition this very file calls
# never acceptable, sat true in production unnoticed until it was checked by
# hand. The file is environment-agnostic now; check-production-health.sh runs
# it against production.
#
# The endpoint responses are safe, content-free health payloads. Do not pass
# deployment hooks, connection strings, or other secret-bearing values here.
set -euo pipefail

surface="${1:-}"
case "$surface" in
  root)
    # `.status == "ok"` cannot hold on staging and never could.
    #
    # health_work_state degrades on stale polling, and D4 runs staging with
    # background processing OFF, so nothing ever polls and the roll-up is
    # permanently degraded. Requiring "ok" here made Tier 2's own root
    # assertion unsatisfiable by construction -- the same shape as D2's
    # "staging runs workers permanently", which was also asserted against an
    # environment that could not hold it.
    #
    # What this assertion is actually for is V4's release identity: proving
    # which build answered. That is asserted strictly. The roll-up bit is
    # replaced by `work-state` below, which names the counters that must be
    # zero whatever the worker posture -- a narrower claim than "ok", not a
    # weaker one.
    filter='(.build_sha | type == "string" and length == 40) and ((.status == "ok") or (.status == "degraded"))'
    failure="API health does not publish a 40-character build SHA, or reports an unknown status"
    ;;
  work-state)
    # Degradations that are NEVER acceptable, regardless of worker posture.
    # Stale polling and due integrations are expected with workers off; lost
    # or unclaimable work is not.
    filter='
      (.items_dead_letter == 0) and
      (.attachments_dead_letter == 0) and
      (.stale_processing_emails == 0) and
      (.unclaimable_emails == 0)
    '
    failure="deployment holds dead-lettered, stale, or unclaimable work"
    ;;
  ingestion)
    filter='
      (.status == "ok") and
      (.background_processing_enabled == true) and
      (.tasks | type == "array" and length > 0 and all(.[]; .alive == true)) and
      (.listener | type == "object" and .connected == true)
    '
    failure="ingestion health does not prove the worker/listener is running"
    ;;
  egress)
    filter='(.transport == "asyncpg")'
    failure="egress health does not prove the asyncpg worker transport is active"
    ;;
  *)
    echo "ERROR: expected health surface 'root', 'work-state', 'ingestion', or 'egress'" >&2
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

echo "OK: $surface health invariants verified"
