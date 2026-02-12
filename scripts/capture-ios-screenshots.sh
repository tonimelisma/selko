#!/usr/bin/env bash
# Capture all 6 iOS screenshots via XCUITest.
# Prerequisites: local Supabase running, seed data loaded, iPhone 17 Pro simulator available.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"

RESULT_BUNDLE="$PROJECT_ROOT/ios/ScreenshotResults.xcresult"

# Clean previous result bundle
rm -rf "$RESULT_BUNDLE"

echo "==> Building and running iOS screenshot tests..."
xcodebuild test \
  -project "$PROJECT_ROOT/ios/iOS.xcodeproj" \
  -scheme iOS \
  -destination 'platform=iOS Simulator,name=iPhone 17 Pro' \
  -only-testing:iOSUITests/ScreenshotCaptureTests \
  -resultBundlePath "$RESULT_BUNDLE" \
  | tail -20

# Clean up result bundle (screenshots are already saved to docs/screenshots/ by the test)
rm -rf "$RESULT_BUNDLE"

# Resize to ≤1920px height (iPhone 17 Pro captures at 2622px)
echo "==> Resizing iOS screenshots..."
sips --resampleHeight 1920 "$PROJECT_ROOT"/docs/screenshots/ios-*.png

echo "==> iOS screenshots saved to docs/screenshots/"
