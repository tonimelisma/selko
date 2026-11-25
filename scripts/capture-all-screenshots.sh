#!/usr/bin/env bash
# Capture the standard light/dark screenshot matrix of the web app (the only
# client; the native apps are unmaintained, legacy/README.md).
#
# Usage:
#   ./scripts/capture-all-screenshots.sh          # the web app
#   ./scripts/capture-all-screenshots.sh web      # the same
#
# Runs Selko the way the image does: the web app built once and served by the
# API on one origin, over a throwaway SQLite data directory seeded by
# scripts/seed_screenshot_data.py. Stops the API it starts, pass or fail.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
PLATFORM="${1:-all}"
case "$PLATFORM" in
    web | all) ;;
    *) echo "Usage: $0 [web]" >&2; exit 1 ;;
esac

PORT="${SELKO_SCREENSHOT_PORT:-8000}"
BASE="http://127.0.0.1:${PORT}"
DATA_DIR="$PROJECT_ROOT/.verify/screenshot-data"
LOG="$PROJECT_ROOT/.verify/screenshot-api.log"

# Something already on the port would answer for us (it has before: an
# unrelated dev server's HTML decoded as JSON on the Settings screen).
if curl -fsS -o /dev/null --max-time 3 "$BASE/health" 2>/dev/null; then
    echo "ERROR: port $PORT is already serving something; stop it (lsof -nP -iTCP:$PORT -sTCP:LISTEN) or set SELKO_SCREENSHOT_PORT." >&2
    exit 1
fi

echo "==> Building the web app (same origin, as in the image)..."
(cd "$PROJECT_ROOT/frontend" && VITE_API_URL="" npm run build >/dev/null)

echo "==> Seeding a fresh SQLite data directory..."
rm -rf "$DATA_DIR"
mkdir -p "$DATA_DIR"
SELKO_DATA_DIR="$DATA_DIR" uv run python "$PROJECT_ROOT/scripts/seed_screenshot_data.py" seed

echo "==> Starting the API on $BASE..."
SELKO_DATA_DIR="$DATA_DIR" \
SELKO_WEB_DIR="$PROJECT_ROOT/frontend/build" \
SELKO_JWT_SECRET="$(python3 -c 'import secrets; print(secrets.token_hex(32))')" \
ALLOWED_ORIGINS="$BASE" \
ENVIRONMENT=development \
ENABLE_BACKGROUND_PROCESSING=false \
SELKO_SIGNIN_ATTEMPTS_PER_MINUTE=200 \
SELKO_TOKEN_REQUESTS_PER_MINUTE=500 \
    uv run uvicorn selko.api.app:app --host 127.0.0.1 --port "$PORT" >"$LOG" 2>&1 &
API_PID=$!
trap 'kill "$API_PID" 2>/dev/null || true; wait "$API_PID" 2>/dev/null || true' EXIT
for _ in $(seq 1 30); do
    curl -fsS --max-time 3 "$BASE/health" 2>/dev/null | grep -q '"resolution"' && break
    kill -0 "$API_PID" 2>/dev/null || { echo "ERROR: the API exited; see $LOG" >&2; exit 1; }
    sleep 1
done
curl -fsS --max-time 3 "$BASE/health" | grep -q '"resolution"' || { echo "ERROR: the API did not start; see $LOG" >&2; exit 1; }

echo ""
echo "=============================="
echo "  Web Screenshots (24)"
echo "=============================="
SELKO_E2E_BASE_URL="$BASE" "$SCRIPT_DIR/capture-web-screenshots.sh"
