# Client API

The web app reads and writes only through Selko's API; there is no database
client in the browser. The API serves the web app itself, so in production
everything is one origin. Design: `docs/specs/sqlite-single-process/03-api-auth-web.md`.
The live list of routes and models is the app's OpenAPI schema
(`create_app().openapi()`); this page is the map.

## Calling it

- **Auth:** `Authorization: Bearer <access token>` on every route except
  `/auth/signup`, `/auth/token`, `/health*`, and the OAuth callbacks.
- **Client:** `frontend/src/lib/api/client.js` (`apiFetch`) adds the token,
  times out after 30 s, and on a 401 does one shared refresh and one retry. It
  never throws: it returns `{data, error, status}`. `frontend/src/lib/auth.js`
  keeps the access token in memory and renews it before expiry.
- **Ownership:** every route is scoped to the signed-in user; another user's id
  answers **404**, never 403.
- **Errors:** auth routes answer `{"detail": {"code", "message"}}`; data routes
  answer `{"detail": "<message>"}`; validation errors are FastAPI's 422 list.
  `parseApiError` in `frontend/src/lib/api/http.js` reads all three.
- **Rate limits:** 60/minute per user by default; `/auth/token` 30/minute per
  address, of which password sign-ins 10/minute (`SELKO_TOKEN_REQUESTS_PER_MINUTE`,
  `SELKO_SIGNIN_ATTEMPTS_PER_MINUTE`).

## Sign-in (`backend/selko/api/routes/auth.py`)

| Route | Purpose |
|---|---|
| `POST /auth/signup` | Create an account (`email`, `password`) → 201 `{user, confirmation_required}` |
| `POST /auth/token` | `grant_type=password` (`email`, `password`) or `grant_type=refresh_token` (the `selko_refresh` cookie) → `{access_token, expires_at, user}`; sets or rotates the cookie |
| `POST /auth/logout` | Revoke the session (or every session) and clear the cookie |
| `GET /auth/user` | The signed-in user |

Cookie endpoints check `Origin` against `ALLOWED_ORIGINS`. The refresh cookie is
HttpOnly, SameSite=Strict, `Path=/auth`.

## Live updates (`routes/live.py`)

`GET /live` is a Server-Sent Events stream (fetched with the Bearer header, not
`EventSource`). Frames: `ready`, `invalidate` (`{"resource": …}` — refetch that
resource), heartbeats every 25 s, `reauth` before the token expires, `revoked`
after sign-out. At most 5 streams per user.

## Data (`routes/client.py` and the feature routers)

| Route | Purpose |
|---|---|
| `GET /events/review` | New lane and Changes lane, with sources and proposals |
| `GET /events/activity` | History of events (`limit`, `offset`; `{items, total}`) |
| `GET /events/{id}` · `PATCH /events/{id}` | One event; edit fields (returns the full event) |
| `POST /events/{id}/accept` · `/reject` | Decide a New-lane event |
| `POST /events/{id}/apply-change` · `/reject-change` | Decide a pending proposal |
| `POST /events/{id}/sync` · `/unsync` · `/undo` | Calendar delivery and undo (worker-owned) |
| `GET /emails/history` | Processed emails, paginated |
| `GET /emails/{id}` · `/processing-state` · `/attachments` | One email, its pipeline state, its attachments |
| `POST /emails/{id}/process` · `/reprocess` · `POST /emails/batch-process` · `POST /emails/sync` | Run or re-run extraction; ask for a prompt poll. An exhausted LLM quota answers 429 |
| `GET /attachments/{id}/content` | Download a stored attachment (owner only) |
| `GET /integrations` · `POST /integrations/disconnect` · `GET /integrations/recovery` | Connected accounts; disconnect; reconnect catch-up progress |
| `GET /integrations/{google,outlook}/auth` and the callbacks | OAuth sign-in to providers |
| `GET /integrations/{provider}/folders` · `PATCH …/folders/{id}` | Mail folders and their Included/Excluded preference |
| `GET /calendars` | The user's writable calendars |
| `GET /settings/calendar` · `PATCH /settings/calendar` | Target calendar, invitees, all-day display, timezone |
| `GET /sender-rules` · `POST` · `DELETE /sender-rules/{id}` · `POST /sender-rules/ignore-sender` | Sender rules; ignore a sender and reject what it sent |

## Health (no auth)

`GET /health`, `/health/db`, `/health/ingestion`, `/health/egress` — the
invariants `scripts/assert-health.sh` asserts are listed in `CLAUDE.md`.

## Tests

Every route above is exercised over a real database: `backend/tests/db/test_client_routes.py`
(with an ownership matrix), `test_auth_routes.py`, `test_live_route.py`,
`backend/tests/test_event_routes.py`, `test_api_routes.py`.
