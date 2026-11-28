# Requirements: Privacy

What Selko keeps out of logs, metrics and the browser, what it stores about LLM calls, who can
read stored content, what the public privacy policy says, and how API keys reach the process.

## Logs and metrics

- **SEL-700** Selko shall never pass an email content field (subject, title, sender_email,
  from_email, snippet, body, body_text, description, location) to a `logger` call anywhere in
  the backend package; log lines name ids instead. [verified]
- **SEL-701** Selko shall write its own INFO-level log lines to stderr, so they reach the
  container log, without any extra configuration. [verified]
- **SEL-702** When Selko counts server errors by route for `/health`, it shall record the route
  template (for example `/events/{event_id}/apply-change`), never a concrete path with an id.
  [verified]
- **SEL-703** When Selko meters outbound traffic, it shall name each operation by a bounded
  template (for an LLM call, `<provider>:<operation type>`), never by prompt or attachment
  content, and fold operations beyond the tracked maximum into one `other` bucket. [verified]
- **SEL-704** Selko's `/health` queue gauges shall report only the count of pending emails and
  the age in seconds of the oldest one. [verified]

## LLM call records

- **SEL-710** When Selko makes an LLM call, it shall store one `llm_call_log` row holding the
  full prompt text and response text together with the user, operation type, model, provider,
  token counts, latency, success, error and estimated cost; this table is content-bearing.
  [verified]
- **SEL-711** Selko shall read `llm_call_log` rows only by their owner's user_id, and no API
  route shall read the table. [verified]
- **SEL-712** If writing an `llm_call_log` row fails, then Selko shall continue the LLM
  operation and record nothing. [verified]
- **SEL-713** When a user is deleted, Selko shall delete that user's `llm_call_log` rows, and
  when an email is deleted, clear the rows' email_id.
  unverified: the foreign keys (`ON DELETE CASCADE`, `ON DELETE SET NULL`) are in the initial
  migration, but no test deletes a user or email and inspects `llm_call_log`; checked by schema
  review.

## Stored content and tokens

- **SEL-720** If a user asks for another user's attachment, email or event by id, then Selko
  shall answer 404 and change nothing. [verified]
- **SEL-721** If an attachment's stored path or a filename would resolve outside the attachments
  folder, then Selko shall refuse to read, write or serve it. [verified]
- **SEL-722** When Selko serves attachment content, it shall send `Cache-Control: private,
  max-age=0, no-store` and `X-Content-Type-Options: nosniff`.
  unverified: no test asserts these headers; checked by reading
  `backend/selko/api/routes/client.py`.
- **SEL-723** When Selko lists an email's attachments to the web app, it shall omit the storage
  path. [verified]
- **SEL-724** When Selko lists a user's integrations, it shall never include the OAuth access or
  refresh token. [verified]
- **SEL-725** When a user signs in or refreshes, Selko shall put the refresh token only in the
  `selko_refresh` cookie (HttpOnly, Secure, SameSite=Strict, Path=/auth), so no script in the
  browser can read it, and the web app's refresh request shall carry no token in its body.
  [verified]
- **SEL-726** Selko's web app shall send tokens only in the `Authorization` header, never in a
  URL, including for the `/live` stream. [verified]

## OAuth scopes

- **SEL-730** When a user connects Google, Selko shall request only the read-only Gmail scope
  (`gmail.readonly`) and the Google Calendar scopes (`calendar`, `calendar.events`).
  unverified: tests compare the requested scopes against the same constants the code uses, not
  against literal values; checked by reading `backend/selko/services/integrations.py`.
- **SEL-731** When a user connects Outlook, Selko shall request only `Mail.Read` and `User.Read`,
  plus `Calendars.ReadWrite` when the calendar is connected.
  unverified: no test pins the requested scope list; checked by reading
  `backend/selko/services/outlook.py`.

## Privacy policy

- **SEL-735** Selko shall serve a privacy policy at `/privacy` that renders without a signed-in
  user. [verified]
- **SEL-736** Selko's privacy policy shall name Google Cloud, Anthropic, Google and Microsoft as
  the service providers that handle user data, and name no provider Selko no longer uses
  (Supabase, Render). [verified]
- **SEL-737** Selko's privacy policy shall name no AI provider other than Anthropic. [verified]
- **SEL-738** Selko's privacy policy shall carry the Google API Services User Data Policy
  disclosure, including the Limited Use requirements, with a link to that policy. [verified]
- **SEL-739** Selko's privacy policy shall give a mailto link for deletion requests. [verified]
- **SEL-740** Where an LLM provider can receive email content (as primary or fallback), Selko's
  privacy policy shall name that provider.
  unverified: the policy's provider list is hard-coded and no test ties it to the model
  registry or the configured providers; the code's default pairing (no LLM_* variables set) is
  a Gemini primary with a Qwen fallback, so production depends on its deployment config naming
  Anthropic only; checked by reviewing the production environment at deploy.
- **SEL-741** Where the fallback provider is configured as `none`, Selko shall build no fallback
  route, even when a fallback model and its API key are present. [verified]

## API keys

- **SEL-745** When the process starts, Selko shall itself read each external API key that its
  environment does not set from Azure Key Vault, and the values read shall reach its
  configuration. [verified]
- **SEL-746** If an environment variable (or one of its accepted aliases) already sets a key,
  then Selko shall use it and not fetch that key from the vault. [verified]
- **SEL-747** If a key cannot be read from the vault, or no vault credential is available, then
  Selko shall leave that key absent and continue with the others. [verified]
- **SEL-748** Selko shall fetch each key from the vault at most once per process. [verified]
- **SEL-749** Where `SELKO_KEYVAULT_AUTH` is `off`, Selko shall fetch nothing from the vault,
  and where it has an unrecognised value, it shall fetch nothing; the test suite runs with
  `off`. [verified]
- **SEL-750** When Selko fetches keys from the vault, it shall log only key names and counts,
  never a value.
  unverified: no test captures the key fetch's log output; checked by reading
  `backend/selko/keyvault.py`.
- **SEL-751** Where `SELKO_KEYVAULT_AUTH` is `gce`, Selko shall authenticate to the vault as
  the app `AZURE_TENANT_ID`/`AZURE_CLIENT_ID` with the host's workload identity (a GCE metadata ID
  token as the client assertion). [verified]
- **SEL-752** Selko shall read the vaults' URLs (`SELKO_KEYVAULT_URL`, `SELKO_KEYVAULT_HOSTS_URL`)
  and the app's tenant and client from configuration, shall sign in with `AZURE_CLIENT_SECRET`
  (or `MELISMA_SECRETS_CLIENT_SECRET`) when one is set, and if the tenant or client is missing,
  or a key's vault has no URL, then it shall not fetch those keys. [verified]

## Process rules

- **SEL-755** Selko's operators shall never copy production credentials or production user data
  into a development environment.
  unverified: a process rule with no automated check; enforced by review of setup scripts and
  deploy changes.
