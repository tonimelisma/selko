#!/usr/bin/env bash
# Capture all 6 Android screenshots via UiAutomator instrumented test.
# Prerequisites: local Supabase running, seed data loaded, Android emulator running.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
SCREENSHOT_DIR="$PROJECT_ROOT/docs/screenshots"
TMP_DIR="/tmp/android-screenshots"

mkdir -p "$SCREENSHOT_DIR"
rm -rf "$TMP_DIR"

cd "$PROJECT_ROOT/android"

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
cp "$TMP_DIR"/*.png "$SCREENSHOT_DIR/"
sips --resampleHeight 1920 "$SCREENSHOT_DIR"/android-*.png

rm -rf "$TMP_DIR"
echo "==> Android screenshots saved to docs/screenshots/"
