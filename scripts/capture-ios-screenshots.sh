#!/usr/bin/env bash
# INTERNAL HELPER — called by capture-all-screenshots.sh. Do not run directly.
# Captures 12 iOS screenshots (six screens in light and dark appearances)
# via XCUITest on iPhone 17 Pro simulator.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

SIMULATOR_NAME="iPhone 17 Pro"
SIMULATOR_UDID=$(xcrun simctl list devices available | sed -n "s/.*$SIMULATOR_NAME (\([0-9A-F-]*\)).*/\1/p" | head -1)
if [ -z "$SIMULATOR_UDID" ]; then
    echo "ERROR: Could not resolve simulator '$SIMULATOR_NAME'"
    exit 1
fi
# --- Idempotent simulator boot ---

SIM_STATE=$(xcrun simctl list devices | grep "$SIMULATOR_UDID" | sed 's/.*(\(.*\))/\1/' | awk '{print $NF}' | tr -d ')')
if [ "$SIM_STATE" = "Booted" ]; then
    echo "==> Simulator '$SIMULATOR_NAME' already booted"
else
    echo "==> Booting simulator '$SIMULATOR_NAME'..."
    xcrun simctl boot "$SIMULATOR_UDID" 2>/dev/null || true
fi
xcrun simctl bootstatus "$SIMULATOR_UDID" -b

# --- Disable password autofill (idempotent, prevents "Save Password?" modal) ---

xcrun simctl spawn "$SIMULATOR_UDID" defaults write -g AutoFillPasswords -bool false 2>/dev/null || true

# --- Build and test once per appearance ---
# Xcode 27 can hang in post-success diagnostic collection even without a result
# bundle. Run xcodebuild under a watchdog that recognizes the selected XCTest
# suite's success, gives it a short grace period to exit normally, then stops
# only the already-finished build process if necessary.

export SCREENSHOT_DIR="$PROJECT_ROOT/docs/screenshots"

capture_appearance() {
    local appearance="$1"
    local log_file="/tmp/ios-screenshot-capture-$appearance.log"

    echo "==> Capturing iOS $appearance appearance..."
    xcrun simctl ui "$SIMULATOR_UDID" appearance "$appearance"
    local current_appearance
    current_appearance=$(xcrun simctl ui "$SIMULATOR_UDID" appearance)
    if [[ "$current_appearance" != *"$appearance"* ]]; then
        echo "ERROR: Simulator appearance is '$current_appearance', expected '$appearance'"
        exit 1
    fi
    xcrun simctl uninstall "$SIMULATOR_UDID" net.melisma.Selko 2>/dev/null || true
    local test_method="testCaptureLightScreenshots"
    if [ "$appearance" = "dark" ]; then
        test_method="testCaptureDarkScreenshots"
    fi

    : > "$log_file"
    xcodebuild test \
        -project "$PROJECT_ROOT/ios/iOS.xcodeproj" \
        -scheme iOS \
        -destination "platform=iOS Simulator,id=$SIMULATOR_UDID" \
        -only-testing:iOSUITests/ScreenshotCaptureTests/$test_method \
        > "$log_file" 2>&1 &
    local xcode_pid=$!
    local suite_passed=false

    while kill -0 "$xcode_pid" 2>/dev/null; do
        if grep -q "Test Suite 'Selected tests' passed" "$log_file"; then
            suite_passed=true
            break
        fi
        sleep 1
    done

    if [ "$suite_passed" = true ]; then
        for _ in 1 2 3 4 5; do
            kill -0 "$xcode_pid" 2>/dev/null || break
            sleep 1
        done
        if kill -0 "$xcode_pid" 2>/dev/null; then
            echo "  Selected tests passed; stopping hung post-success collection"
            kill "$xcode_pid"
        fi
    fi

    set +e
    wait "$xcode_pid"
    local xcode_status=$?
    set -e
    tail -40 "$log_file"

    if [ "$suite_passed" != true ] && ! grep -q "TEST SUCCEEDED" "$log_file"; then
        echo "ERROR: iOS $appearance screenshot tests did not succeed (xcodebuild exit $xcode_status)"
        exit "${xcode_status:-1}"
    fi
}

capture_appearance light
capture_appearance dark

screens=(login register review-queue event-detail history settings)
for screen in "${screens[@]}"; do
    light_file="$PROJECT_ROOT/docs/screenshots/ios-$screen-light.png"
    dark_file="$PROJECT_ROOT/docs/screenshots/ios-$screen-dark.png"
    if [ ! -f "$light_file" ] || [ ! -f "$dark_file" ]; then
        echo "ERROR: Missing iOS appearance baseline for $screen"
        exit 1
    fi
    if cmp -s "$light_file" "$dark_file"; then
        echo "ERROR: iOS light and dark captures are identical for $screen"
        exit 1
    fi
done

ios_count=$(find "$PROJECT_ROOT/docs/screenshots" -maxdepth 1 -type f -name 'ios-*.png' | wc -l | tr -d ' ')
if [ "$ios_count" -ne 12 ]; then
    echo "ERROR: Expected 12 iOS screenshots, found $ios_count"
    exit 1
fi

# Resize to ≤1920px height (iPhone 17 Pro captures at 2622px)
echo "==> Resizing iOS screenshots..."
sips --resampleHeight 1920 "$PROJECT_ROOT"/docs/screenshots/ios-*.png

echo "==> 12 iOS screenshots saved to docs/screenshots/"
