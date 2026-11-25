# Selko Android App

Native Android companion app for Selko.

## Architecture

**Direct Supabase Access** - The app queries Supabase directly for all data operations using the Kotlin Supabase SDK. The Python API is only used for server-side operations.

```
Android App
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

- **Language**: Kotlin
- **UI**: Jetpack Compose
- **DI**: Koin
- **Network**: Ktor
- **Supabase**: `io.github.jan-tennert.supabase` (auth, postgrest, storage)
- **Navigation**: Compose Navigation

## Data Access

All data queries use the Supabase Kotlin SDK directly. See `docs/supabase-frontend-queries.md` for canonical query patterns.

```kotlin
// Example: List emails
val emails = supabase.from("emails")
    .select {
        filter { eq("is_spam", false); eq("is_trash", false) }
        order("date_sent", Order.DESCENDING)
        limit(20)
    }
    .decodeList<Email>()
```

## Project Structure

```
app/src/main/java/net/melisma/selko/
├── SelkoApplication.kt       # App entry point
├── di/                       # Koin DI modules
├── data/
│   ├── models/              # Data classes
│   └── repository/          # Data access (Supabase queries)
├── network/                  # Backend API client (server-side only)
└── ui/                       # Compose UI screens
```

## Building

```bash
# Debug build
./gradlew assembleDebug

# Run tests
./gradlew test

# Install on device
./gradlew installDebug
```

## Configuration

Set Supabase URL and publishable key in `local.properties`:

```properties
SUPABASE_URL=https://your-project.supabase.co
SUPABASE_PUBLISHABLE_KEY=your-publishable-key
BACKEND_URL=https://your-backend.onrender.com
```
