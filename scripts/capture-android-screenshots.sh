#!/usr/bin/env bash
# INTERNAL HELPER — called by capture-all-screenshots.sh. Do not run directly.
# Captures 12 Android screenshots via UiAutomator instrumented test.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SCREENSHOT_DIR="$PROJECT_ROOT/docs/screenshots"
TMP_DIR="/tmp/android-screenshots"

AVD_NAME="Pixel_8"
CONNECT_TIMEOUT=120

fail() {
    echo "ERROR: $*" >&2
    exit 1
}

# Run a command, killing it after N seconds. macOS ships no `timeout`; perl's
# alarm survives exec, so SIGALRM terminates the command itself.
with_timeout() {
    local secs=$1
    shift
    perl -e 'alarm shift; exec @ARGV or die "exec: $!"' "$secs" "$@" \
        || fail "'$*' failed or exceeded ${secs}s"
}

# --- Preflight: fail fast instead of waiting on a device that cannot appear ---
# `adb wait-for-device` has no timeout. If the emulator cannot start (no AVD,
# no system image), it waits forever, which is how a screenshot run hung.

command -v adb >/dev/null || fail "adb not found. Install Android SDK platform-tools and put them on PATH."

if ! adb devices 2>/dev/null | grep -q emulator; then
    command -v emulator >/dev/null || fail "emulator not found and no emulator running. Install the Android Emulator via Android Studio > SDK Manager."
    emulator -list-avds 2>/dev/null | grep -qx "$AVD_NAME" || fail "AVD '$AVD_NAME' does not exist (found: $(emulator -list-avds 2>/dev/null | tr '\n' ' ')). Create it in Android Studio > Device Manager (Pixel 8, with a system image), or start any emulator first."
fi

# Only now discard the old screenshots, so a failed preflight leaves them intact.
mkdir -p "$SCREENSHOT_DIR"
rm -f "$SCREENSHOT_DIR"/android-*.png
rm -rf "$TMP_DIR"

# --- Idempotent emulator start ---

if adb devices 2>/dev/null | grep -q emulator; then
    echo "==> Android emulator already running"
else
    echo "==> No emulator detected. Starting $AVD_NAME..."
    emulator -avd "$AVD_NAME" -no-audio -no-window &
    EMULATOR_PID=$!

    # Wait for the device to appear, bounded, and stop if the emulator died.
    echo "==> Waiting for emulator to connect..."
    ELAPSED=0
    until adb devices 2>/dev/null | grep -q "emulator.*device$"; do
        kill -0 "$EMULATOR_PID" 2>/dev/null || fail "emulator exited before a device connected. Run 'emulator -avd $AVD_NAME' by hand to see why."
        if [ $ELAPSED -ge $CONNECT_TIMEOUT ]; then
            kill "$EMULATOR_PID" 2>/dev/null || true
            fail "emulator did not connect within ${CONNECT_TIMEOUT}s"
        fi
        sleep 2
        ELAPSED=$((ELAPSED + 2))
    done

    # Wait for boot to complete
    echo "==> Waiting for emulator to finish booting..."
    BOOT_TIMEOUT=120
    ELAPSED=0
    while [ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" != "1" ]; do
        if [ $ELAPSED -ge $BOOT_TIMEOUT ]; then
            kill "$EMULATOR_PID" 2>/dev/null || true
            fail "Emulator boot timed out after ${BOOT_TIMEOUT}s"
        fi
        sleep 2
        ELAPSED=$((ELAPSED + 2))
    done
    echo "==> Emulator booted (${ELAPSED}s)"

    # Dismiss any "System UI isn't responding" dialogs after cold boot
    echo "==> Waiting for system to settle after cold boot..."
    sleep 15
    for _ in 1 2 3; do
        adb shell input keyevent KEYCODE_ENTER 2>/dev/null || true
        sleep 2
    done
fi

cd "$PROJECT_ROOT/android"

echo "==> Clearing old screenshots from device..."
adb shell rm -f /sdcard/Android/data/net.melisma.selko/files/Pictures/*.png 2>/dev/null || true

echo "==> Installing debug APK and test APK..."
with_timeout 900 ./gradlew installDebug installDebugAndroidTest

echo "==> Clearing app data (removes stale Supabase sessions)..."
adb shell pm clear net.melisma.selko 2>/dev/null || true

echo "==> Running screenshot capture test..."
with_timeout 600 adb shell am instrument -w \
  -e class net.melisma.selko.ScreenshotCaptureTest \
  net.melisma.selko.test/androidx.test.runner.AndroidJUnitRunner

echo "==> Pulling screenshots from device..."
mkdir -p "$TMP_DIR"
adb pull /sdcard/Android/data/net.melisma.selko/files/Pictures/ "$TMP_DIR/"

SCREENSHOT_COUNT=$(find "$TMP_DIR/Pictures" -name 'android-*.png' | wc -l | tr -d ' ')
if [ "$SCREENSHOT_COUNT" -ne 12 ]; then
    echo "ERROR: Expected 12 Android screenshots, found $SCREENSHOT_COUNT" >&2
    exit 1
fi

echo "==> Copying and resizing screenshots..."
cp "$TMP_DIR"/Pictures/*.png "$SCREENSHOT_DIR/"
sips --resampleHeight 1920 "$SCREENSHOT_DIR"/android-*.png

rm -rf "$TMP_DIR"
echo "==> Android screenshots saved to docs/screenshots/"
