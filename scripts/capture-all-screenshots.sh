#!/usr/bin/env bash
# Capture the standard light/dark screenshot matrix for every platform.
# Runs platforms in parallel when capturing all.
#
# Usage:
#   ./scripts/capture-all-screenshots.sh          # Run all three platforms in parallel
#   ./scripts/capture-all-screenshots.sh web       # Web only
#   ./scripts/capture-all-screenshots.sh ios       # iOS only
#   ./scripts/capture-all-screenshots.sh android   # Android only
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

# Native folder-preference screens use the authenticated backend API. Reuse an
# existing local server or start one for this capture run and stop only that PID.
SCREENSHOT_API_PID=""
if curl -fsS -o /dev/null http://127.0.0.1:8000/health 2>/dev/null; then
    echo "  Backend API: running"
else
    echo "==> Starting local backend API..."
    uv run uvicorn selko.api.app:app --host 127.0.0.1 --port 8000 \
        >/tmp/selko-screenshot-api.log 2>&1 &
    SCREENSHOT_API_PID=$!
    trap 'if [ -n "$SCREENSHOT_API_PID" ]; then kill "$SCREENSHOT_API_PID" 2>/dev/null || true; fi' EXIT
    for _ in {1..30}; do
        if curl -fsS -o /dev/null http://127.0.0.1:8000/health 2>/dev/null; then
            break
        fi
        sleep 1
    done
    if ! curl -fsS -o /dev/null http://127.0.0.1:8000/health 2>/dev/null; then
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

run_ios() {
    echo ""
    echo "=============================="
    echo "  iOS Screenshots (12)"
    echo "=============================="
    "$SCRIPT_DIR/capture-ios-screenshots.sh"
}

run_android() {
    echo ""
    echo "=============================="
    echo "  Android Screenshots (6)"
    echo "=============================="
    "$SCRIPT_DIR/capture-android-screenshots.sh"
}

PLATFORM="${1:-all}"

case "$PLATFORM" in
    web)     run_web ;;
    ios)     run_ios ;;
    android) run_android ;;
    all)
        # Run all three platforms in parallel
        FAILED=""

        run_web &
        WEB_PID=$!

        run_ios &
        IOS_PID=$!

        run_android &
        ANDROID_PID=$!

        # Wait for each and track failures
        if ! wait $WEB_PID; then
            FAILED="${FAILED} web"
        fi
        if ! wait $IOS_PID; then
            FAILED="${FAILED} ios"
        fi
        if ! wait $ANDROID_PID; then
            FAILED="${FAILED} android"
        fi

        echo ""
        if [ -n "$FAILED" ]; then
            echo "==> FAILED platforms:${FAILED}" >&2
            echo "==> Succeeded platforms may have screenshots in docs/screenshots/"
            exit 1
        else
            echo "==> All 42 screenshots captured in docs/screenshots/"
        fi
        ;;
    *)
        echo "Usage: $0 [web|ios|android|all]" >&2
        exit 1
        ;;
esac
