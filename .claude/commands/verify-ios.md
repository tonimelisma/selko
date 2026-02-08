# Visual Verification: iOS App

Verify the Selko iOS app visually using XcodeBuildMCP and mobile-mcp tools.

## Prerequisites

- Xcode installed with iOS Simulator
- iPhone 16 simulator available

## Steps

### 1. Build the app

Use XcodeBuildMCP tools to build:
- Project: `ios/iOS.xcodeproj`
- Scheme: `iOS`
- Destination: `iPhone 16` simulator

### 2. Launch the simulator

Use `mobile_launch_app` from mobile-mcp to launch the app on the simulator.

### 3. Screenshot each screen

Use `mobile_take_screenshot` to capture each screen.

### 4. Screens to verify

1. **Login screen** — initial screen
2. **Register screen** — tap "Create Account" or equivalent
3. **Review Queue** — after login (may show integration setup if not connected)
4. **Integration Setup** — shown when Google account not connected
5. **Event Detail** — tap "Edit" on an event card
6. **Activity History** — tap History tab
7. **Settings** — tap Settings tab

### 5. Navigation

Use `mobile_tap` to navigate between screens:
- Tap tab bar items for Review, History, Settings
- Tap "Edit" on event cards for Event Detail
- Tap "Back" to return to previous screen

### 6. What to check

For each screenshot, analyze:
- **Safe area compliance:** Content doesn't overlap status bar or home indicator
- **Navigation bars:** Standard iOS navigation bar appearance
- **SwiftUI layout:** Proper spacing, alignment, no clipping
- **Tab bar:** Correct icons and labels, active state highlighted
- **Typography:** SF system font, proper size hierarchy
- **Colors:** Consistent theme, proper contrast

### 7. Accessibility audit

Use `mobile_list_elements_on_screen` to enumerate UI elements. Check:
- All buttons and interactive elements have accessibility labels
- Images have accessibility descriptions
- Navigation elements are properly identified

### 8. Report

For each screen, report:
- **PASS** — looks correct
- **ISSUE** — describe the problem with a suggestion

Format:
```
## [Screen Name]
Status: PASS / ISSUE
Notes: [description]
Accessibility: [any missing labels or issues]
```
