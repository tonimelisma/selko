#!/usr/bin/env bash
# Capture all 24 screenshots (12 web + 6 iOS + 6 Android).
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
if ! curl -fsS -o /dev/null http://localhost:54321/rest/v1/ 2>/dev/null; then
    echo "ERROR: Local Supabase is not running. Start it with: supabase start" >&2
    exit 1
fi
echo "  Supabase: running"

# Seed screenshot data (idempotent with --cleanup-first)
echo "==> Seeding screenshot data..."
uv run python "$PROJECT_ROOT/scripts/seed_screenshot_data.py" seed --cleanup-first

# --- Platform runners ---

run_web() {
    echo ""
    echo "=============================="
    echo "  Web Screenshots (12)"
    echo "=============================="
    "$SCRIPT_DIR/capture-web-screenshots.sh"
}

run_ios() {
    echo ""
    echo "=============================="
    echo "  iOS Screenshots (6)"
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
            echo "==> All 24 screenshots captured in docs/screenshots/"
        fi
        ;;
    *)
        echo "Usage: $0 [web|ios|android|all]" >&2
        exit 1
        ;;
esac
