#!/usr/bin/env bash
# Capture all 6 Android screenshots via UiAutomator instrumented test.
# Prerequisites: local Supabase running, seed data loaded.
# Idempotently starts an emulator if none is running.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SCREENSHOT_DIR="$PROJECT_ROOT/docs/screenshots"
TMP_DIR="/tmp/android-screenshots"

mkdir -p "$SCREENSHOT_DIR"
rm -rf "$TMP_DIR"

# --- Idempotent emulator start ---

if adb devices 2>/dev/null | grep -q emulator; then
    echo "==> Android emulator already running"
else
    echo "==> No emulator detected. Starting Pixel_8..."
    emulator -avd Pixel_8 -no-audio -no-window &
    EMULATOR_PID=$!

    # Wait for device to appear
    echo "==> Waiting for emulator to connect..."
    adb wait-for-device

    # Wait for boot to complete
    echo "==> Waiting for emulator to finish booting..."
    BOOT_TIMEOUT=120
    ELAPSED=0
    while [ "$(adb shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')" != "1" ]; do
        if [ $ELAPSED -ge $BOOT_TIMEOUT ]; then
            echo "ERROR: Emulator boot timed out after ${BOOT_TIMEOUT}s" >&2
            exit 1
        fi
        sleep 2
        ELAPSED=$((ELAPSED + 2))
    done
    echo "==> Emulator booted (${ELAPSED}s)"

    # Dismiss any "System UI isn't responding" dialogs
    sleep 5
    adb shell input keyevent KEYCODE_ENTER 2>/dev/null || true
    adb shell input keyevent KEYCODE_ENTER 2>/dev/null || true
fi

cd "$PROJECT_ROOT/android"

echo "==> Clearing old screenshots from device..."
adb shell rm -f /sdcard/Android/data/net.melisma.selko/files/Pictures/*.png 2>/dev/null || true

echo "==> Installing debug APK and test APK..."
./gradlew installDebug installDebugAndroidTest

echo "==> Running screenshot capture test..."
adb shell am instrument -w \
  -e class net.melisma.selko.ScreenshotCaptureTest \
  net.melisma.selko.test/androidx.test.runner.AndroidJUnitRunner

echo "==> Pulling screenshots from device..."
mkdir -p "$TMP_DIR"
adb pull /sdcard/Android/data/net.melisma.selko/files/Pictures/ "$TMP_DIR/"

echo "==> Copying and resizing screenshots..."
cp "$TMP_DIR"/Pictures/*.png "$SCREENSHOT_DIR/"
sips --resampleHeight 1920 "$SCREENSHOT_DIR"/android-*.png

rm -rf "$TMP_DIR"
echo "==> Android screenshots saved to docs/screenshots/"
