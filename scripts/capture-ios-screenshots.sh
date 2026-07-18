#!/usr/bin/env bash
# INTERNAL HELPER — called by capture-all-screenshots.sh. Do not run directly.
# Captures 12 iOS screenshots (six screens in light and dark appearances)
# via XCUITest on iPhone 17 Pro simulator.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

SIMULATOR_NAME="iPhone 17 Pro"
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

# --- Disable password autofill (idempotent, prevents "Save Password?" modal) ---

xcrun simctl spawn "$SIMULATOR_NAME" defaults write -g AutoFillPasswords -bool false 2>/dev/null || true

# --- Build and test once per appearance ---
# Omit -resultBundlePath: post-success diagnostic collection often hangs ~600s and
# then fails saving the bundle even when tests passed.

export SCREENSHOT_DIR="$PROJECT_ROOT/docs/screenshots"

capture_appearance() {
    local appearance="$1"
    local log_file="/tmp/ios-screenshot-capture-$appearance.log"

    echo "==> Capturing iOS $appearance appearance..."
    xcrun simctl ui "$SIMULATOR_NAME" appearance "$appearance"
    xcrun simctl uninstall "$SIMULATOR_NAME" net.melisma.Selko 2>/dev/null || true
    local test_method="testCaptureLightScreenshots"
    if [ "$appearance" = "dark" ]; then
        test_method="testCaptureDarkScreenshots"
    fi

    set +e
    xcodebuild test \
        -project "$PROJECT_ROOT/ios/iOS.xcodeproj" \
        -scheme iOS \
        -destination "platform=iOS Simulator,name=$SIMULATOR_NAME" \
        -only-testing:iOSUITests/ScreenshotCaptureTests/$test_method \
        2>&1 | tee "$log_file" | tail -40
    local xcode_status=${PIPESTATUS[0]}
    set -e

    if ! grep -q "TEST SUCCEEDED" "$log_file"; then
        echo "ERROR: iOS $appearance screenshot tests did not succeed (xcodebuild exit $xcode_status)"
        exit "${xcode_status:-1}"
    fi
}

capture_appearance light
capture_appearance dark

# Resize to ≤1920px height (iPhone 17 Pro captures at 2622px)
echo "==> Resizing iOS screenshots..."
sips --resampleHeight 1920 "$PROJECT_ROOT"/docs/screenshots/ios-*.png

echo "==> 12 iOS screenshots saved to docs/screenshots/"
