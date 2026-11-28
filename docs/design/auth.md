GOVERNS: backend/selko/services/accounts.py backend/selko/db/accounts.py backend/selko/api/routes/auth.py backend/selko/api/deps.py backend/selko/api/limits.py frontend/src/lib/auth.js

# Auth and sessions

Selko's own sign-in ([ADR 0006](../adr/0006-own-sign-in.md)). Requirements:
[accounts](../requirements/accounts.md).

## Tokens

- Passwords: bcrypt (imported `$2a$10$` hashes verify unchanged); 6 characters minimum, 72 UTF-8
  bytes maximum. Emails are trimmed, lowercased, at most 254 characters.
- Access token: HS256 JWT, one hour, stateless; claims `iss`/`aud` `selko`, `typ` `access`, `sid`;
  a `kid` lets `SELKO_JWT_SECRET_PREVIOUS` verify old tokens during a rotation. Lives only in
  browser memory.
- Refresh token: random, only its SHA-256 stored, rotated on every use, in the host-only
  `selko_refresh` cookie (`HttpOnly; Secure; SameSite=Strict; Path=/auth`). A reuse within 10 s of
  rotation gets a new access token without touching the cookie; a reuse after that revokes the
  session. Sessions expire after 30 idle days.

## Abuse resistance

- An unknown email still runs a dummy bcrypt compare and gets the same "Invalid login
  credentials"; a disabled account gets the same 400 (no account-state oracle).
- Data endpoints are Bearer-only, so they need no CSRF defence. Cookie-reading and cookie-setting
  endpoints require `Origin` in `ALLOWED_ORIGINS` and a JSON content type, with `SameSite=Strict` as
  the third layer.
- Password sign-ins are rate-limited per address separately from refreshes; rate-limit keys use the
  verified token subject, otherwise the address.

## Open

Password reset and change, tokens encrypted at rest, and a Content-Security-Policy are tracked in
#451.
