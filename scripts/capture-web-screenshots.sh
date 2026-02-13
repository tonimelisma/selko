#!/usr/bin/env bash
# INTERNAL HELPER — called by capture-all-screenshots.sh. Do not run directly.
# Captures 12 web screenshots (6 desktop + 6 mobile) using Playwright.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

cd "$PROJECT_ROOT/frontend"

echo "==> Capturing web screenshots with Playwright..."
npx playwright test screenshots --project=screenshots
echo "==> Web screenshots saved to docs/screenshots/"
