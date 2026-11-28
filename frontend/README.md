# Selko Web Frontend

SvelteKit web application for Selko.

## Architecture

The web app talks only to Selko's API. In production the API serves the built
app from the same origin; in development the dev server on `:5173` calls the
API on `:8000` (`VITE_API_URL`). There is no database client in the browser.

```
Web app
    │
    └── Selko API (Bearer token)
         - sign-in: /auth/*          (refresh token in an HttpOnly cookie)
         - data: /events, /emails, /integrations, /settings, /sender-rules
         - attachments: /attachments/{id}/content
         - live updates: GET /live   (Server-Sent Events)
```

The full route map is [`docs/design/client-api.md`](../docs/design/client-api.md).

## Tech Stack

- **Framework**: SvelteKit 2, Svelte 5 (runes)
- **CSS**: Tailwind CSS v4 + DaisyUI (themes in `src/app.css`)
- **Testing**: Vitest (unit), Playwright (screenshots, e2e)

## Project Structure

```
src/
├── routes/               # SvelteKit routes (/login, /register, /app/…, /privacy)
└── lib/
    ├── api/
    │   ├── client.js     # apiFetch: Bearer token, 30 s timeout, one shared refresh on 401
    │   ├── http.js       # base URL, parseApiError
    │   └── backend.js    # action calls (sync, process, calendars, …)
    ├── auth.js           # sign-in, sign-up, sign-out, token renewal, cross-tab sync
    ├── live-updates.js   # the /live stream: invalidate, reconnect with backoff
    ├── services/         # data modules returning {data, error, count}
    ├── stores.js
    ├── errors.js
    └── components/
```

The access token lives in memory only; the refresh token only in the
`selko_refresh` cookie. `src/lib/__tests__/no-supabase.test.js` fails if a
database client comes back.

## Development

```bash
npm install
npm run dev                # http://localhost:5173, API at VITE_API_URL
npm run test:unit -- --reporter=json --outputFile=test-results.json
npm run check              # svelte-check (strict)
npm run build              # VITE_API_URL="" for same-origin (what the image does)
```

## Configuration

`frontend/.env`:

```bash
VITE_API_URL=http://localhost:8000
```

The API must list the dev origin in `ALLOWED_ORIGINS` (sign-in checks
`Origin`).
