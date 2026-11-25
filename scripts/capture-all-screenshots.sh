#!/usr/bin/env bash
# Capture the standard light/dark screenshot matrix of the web app (the only
# client; the native apps are unmaintained, legacy/README.md).
#
# Usage:
#   ./scripts/capture-all-screenshots.sh          # the web app
#   ./scripts/capture-all-screenshots.sh web      # the same
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

# --- Prerequisite checks ---

echo "==> Checking prerequisites..."

# Check Supabase is running
if ! curl -fsS -o /dev/null http://127.0.0.1:54321/auth/v1/health 2>/dev/null; then
    echo "ERROR: Local Supabase is not running. Start it with: supabase start" >&2
    exit 1
fi
echo "  Supabase: running"

# The app's folder-preference screens use the authenticated backend API. Reuse an
# existing local server or start one for this capture run and stop only that PID.
#
# The probe must identify *Selko's* API, not merely something answering on the
# port. An unrelated dev server occupying 8000 answered 200 on /health, this
# script concluded "Backend API: running", and the app then decoded that
# server's HTML as JSON -- surfacing as "The data couldn't be read because it
# isn't in the correct format" on the Settings screen, with no hint that the
# wrong service was being talked to. `resolution` is unique to HealthResponse.
selko_api_is_up() {
    curl -fsS --max-time 5 http://127.0.0.1:8000/health 2>/dev/null \
        | grep -q '"resolution"'
}

SCREENSHOT_API_PID=""
if selko_api_is_up; then
    echo "  Backend API: running"
elif curl -fsS -o /dev/null --max-time 5 http://127.0.0.1:8000/health 2>/dev/null; then
    echo "ERROR: Port 8000 is serving something that is not the Selko API." >&2
    echo "       Stop that process (lsof -nP -iTCP:8000 -sTCP:LISTEN) and retry." >&2
    exit 1
else
    echo "==> Starting local backend API..."
    uv run uvicorn selko.api.app:app --host 127.0.0.1 --port 8000 \
        >/tmp/selko-screenshot-api.log 2>&1 &
    SCREENSHOT_API_PID=$!
    trap 'if [ -n "$SCREENSHOT_API_PID" ]; then kill "$SCREENSHOT_API_PID" 2>/dev/null || true; fi' EXIT
    for _ in {1..30}; do
        if selko_api_is_up; then
            break
        fi
        sleep 1
    done
    if ! selko_api_is_up; then
        echo "ERROR: Local backend API did not start. See /tmp/selko-screenshot-api.log" >&2
        exit 1
    fi
    echo "  Backend API: running"
fi

# Seed screenshot data (idempotent with --cleanup-first)
echo "==> Seeding screenshot data..."
uv run python "$PROJECT_ROOT/scripts/seed_screenshot_data.py" seed --cleanup-first

# --- Platform runners ---

run_web() {
    echo ""
    echo "=============================="
    echo "  Web Screenshots (24)"
    echo "=============================="
    "$SCRIPT_DIR/capture-web-screenshots.sh"
}

PLATFORM="${1:-all}"

case "$PLATFORM" in
    web | all) run_web ;;
    *)
        echo "Usage: $0 [web]" >&2
        exit 1
        ;;
esac
