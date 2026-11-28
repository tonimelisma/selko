# Requirements: Accounts, ownership and integrations

Selko's own sign-in (passwords, access tokens, rotating refresh cookie), per-user data ownership,
connecting and disconnecting Google and Microsoft accounts, account deletion and demo seeding, and
API rate limits.

## Sign-up and passwords

- **SEL-400** When `POST /auth/signup` receives a valid email and password, Selko shall create an
  `accounts` row with the email trimmed and lowercased and a `users` profile row whose
  `display_name` is the email's local part, and answer 201. [verified]
- **SEL-401** If the email is already registered, then Selko shall refuse the sign-up with 409
  `USER_ALREADY_EXISTS`. [verified]
- **SEL-402** If a sign-up password is shorter than 6 characters or longer than 72 UTF-8 bytes, then
  Selko shall refuse it with `WEAK_PASSWORD`, and if the email is not a valid address, then with
  `INVALID_REQUEST`. [verified]
- **SEL-403** Selko shall hash passwords with bcrypt at cost 10 and shall accept an imported
  `$2a$10$` bcrypt hash unchanged at sign-in. [verified]
- **SEL-404** If a password sign-in names an unknown email, a wrong password or a disabled account,
  then Selko shall answer 400 `INVALID_CREDENTIALS` "Invalid login credentials", the same for each
  case, and set no cookie. [verified]

## Access tokens

- **SEL-410** When a password sign-in succeeds, Selko shall start an `auth_sessions` row, set the
  account's `last_sign_in_at`, and return an HS256 access token signed with `SELKO_JWT_SECRET`
  carrying the account id and session id, valid for 3600 seconds. [verified]
- **SEL-411** While `SELKO_JWT_SECRET_PREVIOUS` is set, Selko shall also accept access tokens signed
  with it (key id `0`), so the secret can rotate without signing users out. [verified]
- **SEL-412** If an access token is expired, has an audience other than `selko`, is not of type
  `access`, lacks a session id, or is signed with an unknown secret, then Selko shall answer 401.
  [verified]
- **SEL-413** If `SELKO_JWT_SECRET` is shorter than 32 bytes, then Selko shall refuse to build its
  token keys. unverified: no test constructs `TokenKeys` with a short secret; checked by code
  review of `selko.services.accounts.TokenKeys`.
- **SEL-414** When `GET /auth/user` is called with a valid access token, Selko shall return the
  account's id, email, `created_at` and `last_sign_in_at`, and answer 401 without one. [verified]

## Refresh sessions

- **SEL-420** When a password sign-in succeeds, Selko shall set a random refresh token in the
  `selko_refresh` cookie (HttpOnly, SameSite=Strict, Path=/auth, Secure outside development) and
  store only its SHA-256 hash in `auth_refresh_tokens`. [verified]
- **SEL-421** When `POST /auth/token` asks for `grant_type` `refresh_token`, Selko shall read the
  refresh token only from the `selko_refresh` cookie, mark it rotated, store a successor and set
  the successor in the cookie. [verified]
- **SEL-422** If an already rotated refresh token is presented again within 10 seconds of its
  rotation, then Selko shall issue an access token and leave the cookie unchanged. [verified]
- **SEL-423** If an already rotated refresh token is presented more than 10 seconds after its
  rotation, then Selko shall revoke the whole session with reason `reuse_detected`, so its
  successor stops working too. [verified]
- **SEL-424** If a session has not been refreshed for 30 days, then Selko shall revoke it with
  reason `expired` and refuse the refresh. [verified]
- **SEL-425** If a refresh carries no refresh token or an unknown one, then Selko shall answer 401.
  [verified]
- **SEL-426** When `POST /auth/logout` is called with a bearer token or only the refresh cookie,
  Selko shall revoke the caller's current session (`local`) or every session of the account
  (`global`, the default), never another account's session, and clear the cookie. [verified]
- **SEL-427** If a request to `/auth/signup`, `/auth/token` or `/auth/logout` carries an `Origin`
  not in `ALLOWED_ORIGINS`, then Selko shall answer 403, and if its body is not
  `application/json`, then Selko shall refuse it without setting a cookie. [verified]
- **SEL-428** Selko shall send CORS allow-origin headers only to origins listed in
  `ALLOWED_ORIGINS`. [verified]

## Rate limits

- **SEL-430** If a client address makes more than 10 password sign-in attempts in a minute
  (`SELKO_SIGNIN_ATTEMPTS_PER_MINUTE`), then Selko shall answer 429 `RATE_LIMITED`. [verified]
- **SEL-431** Selko shall not count refreshes against the password sign-in budget, while capping
  `/auth/token` as a whole at 30 requests per client address per minute
  (`SELKO_TOKEN_REQUESTS_PER_MINUTE`). [verified]
- **SEL-432** If a client address makes more than 5 sign-ups in an hour, then Selko shall answer
  429. unverified: no test sends six sign-ups; checked by code review of the `/auth/signup`
  limiter decorator.
- **SEL-433** Selko shall key its default limit of 60 requests per minute by the verified user id of
  a valid bearer token and otherwise by client address, so a forged token cannot spend another
  user's budget. unverified: no test exercises `get_user_id_or_ip`; checked by code review of
  `selko.api.limits`.
- **SEL-434** If one client address calls an OAuth callback more than 10 times in 60 seconds, then
  Selko shall answer 429, counting each address separately. [verified]

## Data ownership

- **SEL-440** Selko shall give every public `selko.db` function that touches a user-owned table a
  `user_id`, `user_ids` or `account_id` parameter, except functions on the named service-wide
  allowlist (worker claims and lease-fenced transitions, health counts, token-keyed lookups).
  [verified]
- **SEL-441** If a request names another user's event, email, attachment, integration or sender
  rule by id, then Selko shall answer 404, never 403, and change nothing, and lists without an id
  shall contain only the caller's rows. [verified]
- **SEL-442** If a data or OAuth-start route is called without a valid bearer token, then Selko
  shall answer 401. [verified]

## OAuth integrations

- **SEL-450** When a signed-in user starts an OAuth connect, Selko shall store an `oauth_states` row
  with the user, provider, redirect URI and a PKCE code verifier, expiring 10 minutes later, and
  shall delete expired states. [verified]
- **SEL-451** Selko shall accept each OAuth state once, and if the callback's state is unknown,
  already used or expired, then Selko shall delete it and redirect with `oauth=error`. [verified]
- **SEL-452** If an OAuth state has no stored code verifier or names a provider the callback does
  not allow, then Selko shall refuse before exchanging the code. [verified]
- **SEL-453** When `GET /integrations/google/auth` is called, Selko shall start one combined
  consent (pseudo-provider `google`) for both the Gmail and the Google Calendar scope sets, and
  shall accept a partial grant only while the code is exchanged. [verified]
- **SEL-454** When a Google consent completes, Selko shall create an `integrations` row for each
  product whose full scope set was granted, all sharing the same token and provider email, and if
  no product's scopes were granted, then Selko shall connect nothing and redirect with
  `oauth=error`. [verified]
- **SEL-455** When a Microsoft consent is started, Selko shall request `Calendars.ReadWrite` along
  with its mail scopes, and when it completes, Selko shall store the `outlook` row's tokens and
  provider email. [verified]
- **SEL-456** When an integration is reconnected without a new refresh token, Selko shall keep the
  stored refresh token. [verified]
- **SEL-457** If an OAuth start names a redirect URI whose host is not `localhost`, `127.0.0.1`,
  `api.selkoapp.com` or the `API_PUBLIC_URL` host, then Selko shall answer 400. [verified]
- **SEL-458** If Google refuses to refresh a stored token, then Selko shall mark that integration
  `expired`. [verified]
- **SEL-459** When an integration is disconnected, Selko shall delete only the caller's
  `integrations` row and, by cascade, its `email_sync_state`, and if
  `POST /integrations/disconnect` names no integration the caller owns, then Selko shall answer
  404. [verified]
- **SEL-460** Selko shall never return `access_token`, `refresh_token` or `code_verifier` in an
  integration response. [verified]
- **SEL-461** Selko shall define the Gmail scope set as `gmail.readonly` and the Google Calendar
  scope set as `calendar` plus `calendar.events`, a Calendar grant counting only when both are
  granted. unverified: tests import the scope constants rather than pin their values (only the
  both-scopes rule is tested); checked by code review of `selko.services.integrations`.

## Account deletion and demo data

- **SEL-470** When an operator runs `python -m selko.admin delete-account <uuid>`, Selko shall
  delete the account and, by cascade, its profile, sessions, refresh tokens and every owned row,
  remove its attachments folder and exit 0, exiting 1 for an unknown account and 2 for a non-UUID.
  [verified]
- **SEL-471** If `seed-demo` is run without `SELKO_ALLOW_DEMO_SEED=1`, then Selko shall refuse with
  exit 2, and it shall refuse to seed an account that already has events. [verified]
