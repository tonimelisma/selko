# Legacy: iOS and Android apps (unmaintained)

`legacy/ios/` (SwiftUI) and `legacy/android/` (Jetpack Compose) are the native
Selko apps as they stood on 2026-11-25. **They are no longer maintained**
(owner decision, 2026-11-25). Selko's only client is the web app in
`frontend/`.

What that means:

- **Not built, tested or screenshotted** by any lane, CI job, hook or setup
  script. No change elsewhere in the repository has to keep them compiling or
  working.
- **Not updated** when the backend, the database or the API changes. They
  talk to hosted Supabase directly (PostgREST, Auth, Realtime), so they stop
  working once Selko moves off it (`docs/specs/sqlite-single-process.md`).
- **Don't edit them**, and don't read them as a description of how Selko
  works today.

The backend paths that existed only for these apps (`GET
/integrations/gmail/auth` and `/integrations/calendar/auth`) were removed on
2026-11-25; installed builds can no longer start a Google sign-in.
