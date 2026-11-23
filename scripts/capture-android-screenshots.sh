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

# A system ANR dialog ("Pixel Launcher isn't responding") once covered the
# login form mid-run on a slow emulator; a capture run never wants one.
adb shell settings put global hide_error_dialogs 1 2>/dev/null || true

cd "$PROJECT_ROOT/android"


echo "==> Installing debug APK and test APK..."
with_timeout 900 ./gradlew installDebug installDebugAndroidTest

PICTURES=/sdcard/Android/data/net.melisma.selko/files/Pictures
mkdir -p "$TMP_DIR"

# Run one ScreenshotCaptureTest method. `am instrument` exits 0 even when the
# app process crashes or a test fails; the verdict is only in its output. Read
# it, or a crash surfaces later as a misleading "no screenshots to pull".
run_capture() {
    local method="$1" output
    adb logcat -c 2>/dev/null || true
    output="$(with_timeout 600 adb shell am instrument -w \
        -e class "net.melisma.selko.ScreenshotCaptureTest#${method}" \
        net.melisma.selko.test/androidx.test.runner.AndroidJUnitRunner)"
    printf '%s\n' "$output"
    grep -q '^OK (' <<<"$output" && return 0
    echo "==> ${method} did not pass; crash buffer and test log:" >&2
    adb logcat -d -b crash 2>/dev/null | tail -60 >&2 || true
    adb logcat -d -s TestRunner:* AndroidRuntime:E 2>/dev/null | tail -60 >&2 || true
    # What the screen showed when it gave up -- seeded demo data only. Kept
    # under build/reports so ops.yml's android-test-reports artifact has it.
    local failure_dir="$PROJECT_ROOT/android/app/build/reports/screenshot-failure"
    mkdir -p "$failure_dir"
    adb exec-out screencap -p >"$failure_dir/screen.png" 2>/dev/null || true
    adb shell uiautomator dump /sdcard/window.xml >/dev/null 2>&1 &&
        adb pull /sdcard/window.xml "$failure_dir/window.xml" >/dev/null 2>&1 || true
    echo "==> Screen at failure saved to android/app/build/reports/screenshot-failure/" >&2
    fail "ScreenshotCaptureTest#${method} did not report OK"
}

# `pm clear` both signs the app out and deletes its Pictures folder, so pull
# after each signed-in pass. It must run from here: from inside the test it
# kills the process the instrumentation itself runs in.
echo "==> Clearing app data (removes stale Supabase sessions)..."
adb shell pm clear net.melisma.selko 2>/dev/null || true

echo "==> Capturing the signed-in screens (light and dark) and the light signed-out ones..."
run_capture captureAllScreenshots
adb pull "$PICTURES/" "$TMP_DIR/"

echo "==> Signing out (pm clear), then capturing the dark signed-out screens..."
adb shell pm clear net.melisma.selko >/dev/null
run_capture captureSignedOutDarkScreens
adb pull "$PICTURES/" "$TMP_DIR/"

SCREENSHOT_COUNT=$(find "$TMP_DIR/Pictures" -name 'android-*.png' | wc -l | tr -d ' ')
if [ "$SCREENSHOT_COUNT" -ne 12 ]; then
    echo "ERROR: Expected 12 Android screenshots, found $SCREENSHOT_COUNT" >&2
    exit 1
fi

echo "==> Copying and resizing screenshots..."
cp "$TMP_DIR"/Pictures/*.png "$SCREENSHOT_DIR/"
# sips on the Mac; ImageMagick on Linux (ops.yml's android-emulator job).
if command -v sips >/dev/null; then
    sips --resampleHeight 1920 "$SCREENSHOT_DIR"/android-*.png
else
    command -v mogrify >/dev/null || fail "neither sips nor ImageMagick's mogrify is installed"
    mogrify -resize x1920 "$SCREENSHOT_DIR"/android-*.png
fi

rm -rf "$TMP_DIR"
echo "==> Android screenshots saved to docs/screenshots/"
