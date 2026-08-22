#!/usr/bin/env bash
# W5 / D4: prove worker behaviour against staging, from this machine.
#
# `selko-app-staging` is a Render FREE web service: 512 MB, 0.15 CPU, and it
# spins down after ~15 minutes idle. Measured 2026-08-21 -- the first /health
# request timed out at 30s and the retry reported uptime_seconds: 8, a cold
# start caused by the request itself. A sleeping instance holds no lease, sends
# no heartbeat and reclaims nothing, so `background_processing_enabled` on the
# deployed service can never be a durable truth there.
#
# D4 records the operator decision: staging stays on free, and worker
# verification runs `selko.worker_app` HERE, against staging Supabase, over the
# real Supavisor session pooler. That covers real Postgres, real LISTEN/NOTIFY,
# real leases, real generation fencing and real expiry reclaim -- everything
# Tier 1 structurally cannot reach.
#
# It does NOT cover Render's memory ceiling or the deployed service's posture.
# Nothing in this script may claim otherwise.
set -euo pipefail

STAGING_REF="lxmysergoeaegxlyfzwk"
PRODUCTION_REF="khahcozfbnpykspvatrg"
LINKED_REF_FILE="supabase/.temp/project-ref"
WORKER_LOG="${TMPDIR:-/tmp}/selko-staging-worker-$$.log"
WORKER_PID=""
READY_TIMEOUT_SECONDS="${DRILL_READY_TIMEOUT_SECONDS:-90}"

fail() { echo "ERROR: $*" >&2; exit 1; }

cleanup() {
  local status=$?
  if [[ -n "$WORKER_PID" ]] && kill -0 "$WORKER_PID" 2>/dev/null; then
    echo "Stopping staging worker (pid ${WORKER_PID})"
    kill -TERM "$WORKER_PID" 2>/dev/null || :
    local waited=0
    while kill -0 "$WORKER_PID" 2>/dev/null && [[ "$waited" -lt 20 ]]; do
      sleep 1
      waited=$((waited + 1))
    done
    kill -9 "$WORKER_PID" 2>/dev/null || :
  fi
  if [[ "$status" -ne 0 ]]; then
    echo "--- last 40 lines of worker log ---" >&2
    tail -40 "$WORKER_LOG" >&2 || :
  fi
  rm -f "$WORKER_LOG"
  exit "$status"
}
trap cleanup EXIT

# A drill that can point at production is a drill that will, eventually.
[[ "${ENVIRONMENT:-}" == "staging" ]] || fail "ENVIRONMENT=staging is required"
[[ -f "$LINKED_REF_FILE" ]] || fail "linked project ref is unknown; run supabase link --project-ref $STAGING_REF"
linked_ref=$(tr -d '[:space:]' < "$LINKED_REF_FILE")
[[ "$linked_ref" != "$PRODUCTION_REF" ]] || fail "production project ref detected; refusing to continue"
[[ "$linked_ref" == "$STAGING_REF" ]] || fail "linked project is not the staging project"
[[ -n "${SUPABASE_DB_URL:-}" ]] || fail "SUPABASE_DB_URL (Supavisor session pooler, port 5432) is required"

echo "Starting selko.worker_app against staging Supabase"
ENVIRONMENT=staging uv run python -m selko.worker_app >"$WORKER_LOG" 2>&1 &
WORKER_PID=$!

# Ready means the runtime reported its tasks started, not that the process
# exists. A worker that died during pool creation still has a pid for a moment.
waited=0
until grep -q "Email ingestion v2 runtime started" "$WORKER_LOG" 2>/dev/null; do
  kill -0 "$WORKER_PID" 2>/dev/null || fail "worker exited before becoming ready"
  [[ "$waited" -lt "$READY_TIMEOUT_SECONDS" ]] || fail "worker did not report ready within ${READY_TIMEOUT_SECONDS}s"
  sleep 2
  waited=$((waited + 2))
done
grep -q "Supavisor session pooler connected" "$WORKER_LOG" \
  || fail "worker started without the session pooler; the drill would prove nothing"
echo "Worker ready against staging (pid ${WORKER_PID})"

# That is the whole of what a LIVE worker proves here: selko.worker_app boots
# against staging over the Supavisor session pooler, with LISTEN/NOTIFY, and
# reaches a healthy runtime. Stop it before the drills run.
#
# The drill suite drives the claim/heartbeat/complete RPCs itself, and a live
# worker is a competing claimer for exactly the same rows. Left running, it
# steals the work the drills are about to claim: test_05 claimed a different
# event than the one it created, and test_07 claimed nothing at all because the
# worker got there first. Both looked like fencing failures and were races
# against my own worker.
# Drain before stopping. SIGTERM mid-run leaves the sync run `running` and the
# lease held. On a machine with a live worker that self-heals -- the next
# claim_due_email_sync abandons the stale run (test_08 proves it). Staging has
# no worker by design (D4), so nothing ever claims, the run stays `running`
# forever, and health_work_state degrades permanently:
#
#   stale_sync_runs: 1, open_incidents: 1  ->  /health "degraded"
#
# which then fails Tier 2's own root assertion. A drill that breaks the
# environment it verifies is worse than no drill.
instance_id="$(sed -n 's/.*instance=\([A-Za-z0-9-]*\).*/\1/p' "$WORKER_LOG" | head -1)"
[[ -n "$instance_id" ]] || fail "could not determine the worker instance id from its log"
echo "Draining worker ${instance_id} before stopping it"
drained=0
for _ in $(seq 1 "${DRILL_DRAIN_ATTEMPTS:-60}"); do
  held="$(uv run python scripts/_drill_lease_probe.py "$instance_id" 2>/dev/null | sed -n 's/^held=//p')"
  if [[ "$held" == "0" ]]; then
    drained=1
    break
  fi
  sleep 3
done
[[ "$drained" == "1" ]] || fail "worker still holds leases after draining; refusing to strand them on staging"
echo "Worker holds no leases"

echo "Stopping the worker before the drills (it competes for the same claims)"
kill -TERM "$WORKER_PID" 2>/dev/null || :
waited=0
while kill -0 "$WORKER_PID" 2>/dev/null && [[ "$waited" -lt 30 ]]; do
  sleep 1
  waited=$((waited + 1))
done
kill -0 "$WORKER_PID" 2>/dev/null && fail "worker did not stop; refusing to race the drills"
grep -q "unfinished leases remain reclaimable" "$WORKER_LOG" \
  || fail "worker did not shut down cleanly; leases may still be held"
WORKER_PID=""
echo "Worker stopped cleanly; leases released"

# Assert the environment is no worse than we found it. A drill that degrades
# staging has to say so rather than hand the next run a red root assertion.
held_after="$(uv run python scripts/_drill_lease_probe.py "$instance_id" 2>/dev/null | sed -n 's/^held=//p')"
[[ "$held_after" == "0" ]] || fail "worker left ${held_after} lease/run rows behind on staging"

echo "Running the drill suite against staging"
RUN_ACCEPTANCE_DRILL=1 ENVIRONMENT=staging \
  uv run pytest backend/tests/drills/ -m "staging and drill" -v --tb=short

# The staging integration suite (including the grant posture assertions) is run
# by verify-staging.sh, not here. Running it twice would mean two owners for
# one operation and two places to keep in step.

# No PASSED banner. The exit code is the result -- printing a verdict is
# exactly how drill-lease-recovery.sh claimed success on a path it never ran.
echo "staging-worker-drill: drill suite completed against staging"
