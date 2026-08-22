#!/usr/bin/env bash
# Run a command with Selko's backend API guaranteed available, and leave the
# machine exactly as it was found.
#
# Written because a rule was not enough. "Stop what you start" was documented
# and then broken within the hour: a uvicorn was left running for 1h47m, and a
# second one outlived the test run it was started for. Process lifetime is not
# something to remember; it is something to own. This script starts the API only
# if it is not already up, and stops only the instance it started -- an API the
# operator was already running is never touched.
set -euo pipefail

if [ "$#" -eq 0 ]; then
    echo "Usage: ./scripts/with-api.sh <command> [args...]" >&2
    exit 2
fi

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
API_LOG="${TMPDIR:-/tmp}/selko-with-api.log"
STARTED_PID=""
STARTED_LISTENER_PID=""

# Identify *Selko's* API, not merely something answering on the port. An
# unrelated dev server once answered 200 on /health and the app then decoded its
# HTML as JSON. `resolution` is unique to HealthResponse.
api_is_up() {
    curl -fsS --max-time 5 http://127.0.0.1:8000/health 2>/dev/null | grep -q '"resolution"'
}

cleanup() {
    [ -n "$STARTED_PID" ] || return 0
    # Kill the listener, not just the shell that launched it. `uv run uvicorn`
    # spawns the server as a child, so killing $! reaps the subshell and leaves
    # the server holding port 8000 -- which is exactly how the first version of
    # this script leaked a process it claimed to clean up.
    if [ -n "$STARTED_LISTENER_PID" ]; then
        kill "$STARTED_LISTENER_PID" 2>/dev/null || true
    fi
    kill "$STARTED_PID" 2>/dev/null || true
    wait "$STARTED_PID" 2>/dev/null || true
    for _ in $(seq 1 10); do
        api_is_up || break
        sleep 1
    done
    if api_is_up; then
        echo "with-api: WARNING -- the API we started is still running on :8000" >&2
    fi
}
trap cleanup EXIT INT TERM

if api_is_up; then
    echo "with-api: reusing the API already running on :8000 (will not stop it)"
else
    if curl -fsS -o /dev/null --max-time 5 http://127.0.0.1:8000/health 2>/dev/null; then
        echo "with-api: port 8000 is serving something that is not the Selko API." >&2
        echo "          Stop it (lsof -nP -iTCP:8000 -sTCP:LISTEN) and retry." >&2
        exit 1
    fi
    echo "with-api: starting the API (will stop it when the command finishes)"
    (cd "$PROJECT_ROOT" && uv run uvicorn selko.api.app:app --host 127.0.0.1 --port 8000 >"$API_LOG" 2>&1) &
    STARTED_PID=$!
    for _ in $(seq 1 60); do
        api_is_up && break
        sleep 1
    done
    if ! api_is_up; then
        echo "with-api: API did not start. See $API_LOG" >&2
        exit 1
    fi
    # Record the process actually holding the port, so cleanup targets it.
    STARTED_LISTENER_PID="$(lsof -nP -iTCP:8000 -sTCP:LISTEN -t 2>/dev/null | head -1)"
fi

"$@"
