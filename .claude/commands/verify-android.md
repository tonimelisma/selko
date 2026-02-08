# Visual Verification: Android App

Verify the Selko Android app visually using mobile-mcp tools and Bash for building.

## Prerequisites

- Android SDK installed
- Android Emulator running (Pixel device recommended)
- `ANDROID_HOME` environment variable set

## Steps

### 1. Build and install the app

Use Bash to build and install:
```bash
cd android && ./gradlew installDebug
```

### 2. Launch the app

Use `mobile_launch_app` from mobile-mcp:
- Package: `net.melisma.selko`

### 3. Screenshot each screen

Use `mobile_take_screenshot` to capture each screen.

### 4. Screens to verify

1. **Login screen** — initial screen
2. **Register screen** — tap "Create Account" or equivalent
3. **Review Queue** — after login (may show integration setup if not connected)
4. **Integration Setup** — shown when Google account not connected
5. **Event Detail** — tap "Edit" on an event card
6. **Activity History** — tap History tab in bottom navigation
7. **Settings** — tap Settings tab in bottom navigation

### 5. Navigation

Use `mobile_tap` to navigate between screens:
- Tap bottom navigation items for Review, History, Settings
- Tap event cards or "Edit" buttons for Event Detail
- Tap back arrow to return to previous screen

### 6. What to check

For each screenshot, analyze:
- **Material3 theming:** Dynamic color or proper Material3 color scheme
- **Compose layout:** Proper spacing, alignment, no clipping or overflow
- **Navigation:** Bottom navigation bar with correct icons and labels
- **Typography:** Material3 type scale (headlineSmall, bodyMedium, etc.)
- **Edge-to-edge:** Content handles system bars correctly
- **Component usage:** Material3 components (Cards, TopAppBar, FloatingActionButton, etc.)

### 7. Accessibility audit

Use `mobile_list_elements_on_screen` to enumerate UI elements. Check:
- All interactive elements have content descriptions
- Proper semantics on headings and buttons
- Touch targets meet minimum 48dp

### 8. Report

For each screen, report:
- **PASS** — looks correct
- **ISSUE** — describe the problem with a suggestion

Format:
```
## [Screen Name]
Status: PASS / ISSUE
Notes: [description]
Accessibility: [any missing content descriptions or issues]
```
