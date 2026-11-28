# 0006. Selko's own sign-in

- Status: accepted
- Date: 2026-11-28

## Context and problem

Sign-in used to go through a hosted identity service. With one process and one file, an external
auth service would be the only remaining network dependency for every request. Requirements:
[SEL-400..434](../requirements/accounts.md).

## Decision drivers

- No external service in the request path.
- Imported password hashes keep working.
- A stolen access token is short-lived; a refresh token is never readable by script.

## Considered options

### bcrypt passwords, HS256 access tokens, rotating refresh cookie (chosen)

- Good: no third party; rotation detects token theft.
- Bad: password reset and change are not built yet (#451).
- Failure modes: a leaked `SELKO_JWT_SECRET` forges tokens until it is rotated.

### A hosted identity provider

- Good: social login, reset flows for free.
- Bad: a network dependency and a second user store.
- Failure modes: provider outages lock everyone out.

## Decision

`selko.services.accounts`: bcrypt passwords (imported `$2a$10$` hashes verify unchanged), HS256
access tokens signed with `SELKO_JWT_SECRET` (`SELKO_JWT_SECRET_PREVIOUS` verifies during a
rotation), and a rotating refresh token in the `selko_refresh` cookie (HttpOnly, SameSite=Strict,
Path=/auth; only its SHA-256 is stored; reusing a rotated token revokes the session). Cookie
endpoints check `Origin`. Password sign-ins are rate-limited per address separately from
refreshes. The access token lives only in browser memory.

## Consequences

Data endpoints are Bearer-only, so they need no CSRF defence; cookie endpoints need Origin,
JSON and SameSite. Design detail: `docs/design/auth.md`.

## Confirmation

`backend/tests/db/test_accounts.py`, `backend/tests/db/test_auth_routes.py`,
`backend/tests/integration/test_rate_limiting.py` (SEL-400..434).

## Retirement proof

A requirement Selko's own sign-in cannot meet (for example enterprise single sign-on).

## Reversal plan

Accounts are one table; a provider could be added beside passwords without migrating users.
