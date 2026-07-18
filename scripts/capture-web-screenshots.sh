#!/usr/bin/env bash
# INTERNAL HELPER — called by capture-all-screenshots.sh. Do not run directly.
# Captures 24 web screenshots (six screens, desktop/mobile, light/dark).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT/frontend"

echo "==> Capturing web screenshots with Playwright..."
npx playwright test screenshots --project=screenshots
echo "==> Web screenshots saved to docs/screenshots/"
