#!/usr/bin/env bash
# INTERNAL HELPER — called by capture-all-screenshots.sh. Do not run directly.
# Captures 6 iOS screenshots via XCUITest on iPhone 17 Pro simulator.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

SIMULATOR_NAME="iPhone 17 Pro"
RESULT_BUNDLE="$PROJECT_ROOT/ios/ScreenshotResults.xcresult"

# --- Idempotent simulator boot ---

SIM_STATE=$(xcrun simctl list devices | grep "$SIMULATOR_NAME" | head -1 | sed 's/.*(\(.*\))/\1/' | awk '{print $NF}' | tr -d ')')
if [ "$SIM_STATE" = "Booted" ]; then
    echo "==> Simulator '$SIMULATOR_NAME' already booted"
else
    echo "==> Booting simulator '$SIMULATOR_NAME'..."
    xcrun simctl boot "$SIMULATOR_NAME" 2>/dev/null || true
    # Wait for simulator to be ready
    sleep 3
fi

# --- Force light appearance (idempotent) ---

xcrun simctl ui "$SIMULATOR_NAME" appearance light

# --- Disable password autofill (idempotent, prevents "Save Password?" modal) ---

xcrun simctl spawn "$SIMULATOR_NAME" defaults write -g AutoFillPasswords -bool false 2>/dev/null || true

# --- Uninstall app to ensure clean state (no stale login session) ---

echo "==> Uninstalling app to ensure clean state..."
xcrun simctl uninstall "$SIMULATOR_NAME" net.melisma.Selko 2>/dev/null || true

# Clean previous result bundle
rm -rf "$RESULT_BUNDLE"

# --- Build and test (always full build since we uninstalled above) ---

echo "==> Building and running screenshot tests..."
xcodebuild test \
    -project "$PROJECT_ROOT/ios/iOS.xcodeproj" \
    -scheme iOS \
    -destination "platform=iOS Simulator,name=$SIMULATOR_NAME" \
    -only-testing:iOSUITests/ScreenshotCaptureTests \
    -resultBundlePath "$RESULT_BUNDLE" \
    | tail -20

# Clean up result bundle (screenshots are already saved to docs/screenshots/ by the test)
rm -rf "$RESULT_BUNDLE"

# Resize to ≤1920px height (iPhone 17 Pro captures at 2622px)
echo "==> Resizing iOS screenshots..."
sips --resampleHeight 1920 "$PROJECT_ROOT"/docs/screenshots/ios-*.png

echo "==> iOS screenshots saved to docs/screenshots/"
