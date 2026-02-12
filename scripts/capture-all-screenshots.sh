#!/usr/bin/env bash
# Capture all 24 screenshots (12 web + 6 iOS + 6 Android).
# Prerequisites: local Supabase running, seed data loaded, Android emulator running.
#
# Usage:
#   ./scripts/capture-all-screenshots.sh          # Run all three platforms
#   ./scripts/capture-all-screenshots.sh web       # Web only
#   ./scripts/capture-all-screenshots.sh ios       # iOS only
#   ./scripts/capture-all-screenshots.sh android   # Android only
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

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
        run_web
        run_ios
        run_android
        echo ""
        echo "==> All 24 screenshots captured in docs/screenshots/"
        ;;
    *)
        echo "Usage: $0 [web|ios|android|all]" >&2
        exit 1
        ;;
esac
