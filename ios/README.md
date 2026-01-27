# Selko iOS App

Native iOS companion app for Selko.

## Architecture

**Direct Supabase Access** - The app queries Supabase directly for all data operations using the Swift Supabase SDK. The Python API is only used for server-side operations.

```
iOS App
    │
    ├─── Data queries ──→ Supabase (direct)
    │    - List emails, events, integrations
    │    - Update event status
    │    - Download attachments
    │
    └─── Server-side ops ──→ Python API
         - OAuth callback handling
         - Email sync triggers
         - LLM processing triggers
         - Calendar sync triggers
```

## Tech Stack

- **Language**: Swift
- **UI**: SwiftUI
- **Supabase**: `supabase-swift` (auth, postgrest, storage)
- **Minimum iOS**: 17.0

## Data Access

All data queries use the Supabase Swift SDK directly. See `docs/supabase-frontend-queries.md` for canonical query patterns.

```swift
// Example: List emails
let emails: [Email] = try await supabase
    .from("emails")
    .select()
    .eq("is_spam", false)
    .eq("is_trash", false)
    .order("date_sent", ascending: false)
    .limit(20)
    .execute()
    .value
```

## Project Structure

```
Selko/
├── SelkoApp.swift           # App entry point
├── ContentView.swift        # Root view
├── Core/
│   ├── Config/             # Configuration
│   └── Supabase/           # Supabase client setup
├── Features/
│   ├── Auth/               # Authentication views
│   ├── Emails/             # Email list & detail views
│   └── Events/             # Event review views
└── Models/                  # Data models
```

## Building

Open `iOS.xcodeproj` in Xcode 16+ and build.

```bash
# Run tests
xcodebuild test -project iOS.xcodeproj -scheme iOS \
  -destination 'platform=iOS Simulator,name=iPhone 16' \
  -resultBundlePath TestResults.xcresult
```

## Configuration

Set Supabase URL and publishable key in `Selko/Core/Config/AppConfig.swift`:

```swift
enum AppConfig {
    static let supabaseURL = URL(string: "https://your-project.supabase.co")!
    static let supabasePublishableKey = "your-publishable-key"
    static let backendURL = URL(string: "https://your-backend.onrender.com")!
}
```
