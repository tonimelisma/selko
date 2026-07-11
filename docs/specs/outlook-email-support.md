# Spec: Outlook.com email support (Microsoft Graph)

**Status:** Planned — not yet implemented
**Author:** Design plan (see git history)
**Related reference docs:** [`docs/gmail-integration.md`](../gmail-integration.md), [`docs/database-schema.md`](../database-schema.md), [`docs/job-queue.md`](../job-queue.md)

---

## 1. Goal

Let a user connect an **Outlook.com / Microsoft personal account** (also works for
Microsoft 365 work/school accounts) so their inbox is ingested into Selko exactly
like Gmail is today: emails land in the `emails` table with `processing_status =
'pending'`, and the existing worker pool runs LLM event extraction on them. No
change to the downstream LLM/event pipeline — only a second **ingestion source**.

### Non-goals (v1)

- Webhooks / push notifications (Graph `/subscriptions`). We poll, like Gmail does today.
- Syncing folders other than the Inbox.
- Sending mail, modifying mail, or writing back read state to Outlook.
- Calendar/contacts via Graph (email only).

---

## 2. Background: how email ingestion works today (Gmail)

Read this before implementing. The pipeline:

```
OAuth (google-auth)                       [services/gmail.py, services/integrations.py]
  → scheduled task "email_fetch" every 15 min  [workers/email_fetch.py, api/app.py lifespan]
  → fetch_messages() list + full get       [services/gmail.py]
  → parse_gmail_message() → DB dict         [services/emails.py]
  → save_emails() upsert (status pending)   [services/emails.py]
  → worker pool claims pending emails       [workers/email_process.py, services/emails.py]
  → LLM extraction → events                 [services/event_processing.py]
```

Key facts:

- **The pipeline is provider-agnostic downstream of a saved `emails` row.**
  `event_processing.py` only reads `subject`, `from_email`, `from_name`, `date_sent`,
  and `body_text` (falls back to `snippet`) — plus it uses the email's `gmail_id`
  purely as an opaque `email_message_id`. See
  [`event_processing.py:295`](../../backend/selko/services/event_processing.py).
- **Gmail already uses polling, not push**, despite what `docs/gmail-integration.md`
  describes. `schedule_email_fetches()` enqueues one `email_fetch` task per active
  Gmail integration every 15 minutes; `process_email_fetch_task()` fetches the latest
  N messages. There is no history-API / Pub/Sub code in the repo.
- **Label → flag computation happens in a Postgres trigger**, not in Python. The
  `parse_gmail_labels()` trigger reads `gmail_label_ids text[]` and sets
  `is_spam`, `is_unread`, `is_promotions`, etc. See
  [`20260121000003_create_emails.sql`](../../supabase/migrations/20260121000003_create_emails.sql).

---

## 3. Locked design decisions

1. **Full provider-agnostic schema rename** (not a reuse-the-`gmail_*`-columns hack).
   `gmail_id → provider_message_id`, `gmail_label_ids → provider_labels`,
   `gmail_attachment_id → provider_attachment_id`, add `emails.email_provider`.
2. **Delta-query sync.** Store the Inbox `@odata.deltaLink` per integration and use
   Graph's `messages/delta` for incremental sync. Reuse the (renamed) integrations
   cursor column.
3. **Reuse the existing flag trigger** by feeding it *synthesized* Gmail-style label
   tokens for Outlook (`UNREAD`, `IMPORTANT`, `STARRED`). This keeps the flag columns
   and the trigger essentially unchanged (only column/function renames), so web/iOS/
   Android — which read `is_spam`/`is_unread`/etc. — need no query changes. This is a
   deliberate simplification: Outlook rows carry a few Gmail-flavored pseudo-tokens in
   `provider_labels`. Accepted.

---

## 4. Prerequisite: Azure app registration (done by a human, once)

Selko needs a Microsoft Entra (Azure AD) **app registration** with a client secret.
This cannot be automated by the implementer — an account owner runs it. Delegated,
personal-account access needs **no admin consent**; the user consents at runtime.

```bash
# 1. Create the app. AzureADandPersonalMicrosoftAccount = work + personal (outlook.com).
az ad app create \
  --display-name "Selko" \
  --sign-in-audience AzureADandPersonalMicrosoftAccount \
  --web-redirect-uris \
      "http://localhost:8000/integrations/microsoft/callback" \
      "https://api.selko.app/integrations/microsoft/callback"
# note the returned "appId"

# 2. (Optional but recommended) declare delegated Graph permissions in the manifest.
#    Microsoft Graph resource appId = 00000003-0000-0000-c000-000000000000
#    Verify the scope GUIDs for your tenant:
#      az ad sp show --id 00000003-0000-0000-c000-000000000000 \
#        --query "oauth2PermissionScopes[?value=='Mail.Read' || value=='offline_access' || value=='User.Read']"
#    Then (GUIDs below are the well-known values, confirm before use):
az ad app permission add --id <appId> \
  --api 00000003-0000-0000-c000-000000000000 \
  --api-permissions \
    570282fd-fa5c-430d-a7fd-fc8dc98a9dca=Scope \  # Mail.Read
    7427e0e9-2fba-42fe-b0c0-848c9e6a8182=Scope \  # offline_access
    e1fe6dd8-ba31-4d61-89e7-88639da4683d=Scope    # User.Read

# 3. Create a client secret (copy the returned password immediately — shown once).
az ad app credential reset --id <appId> --append --display-name "selko-backend"
```

> **Note on scopes:** with the v2.0 endpoint (MSAL), consent is *dynamic* — the app
> requests scopes at runtime and the user consents then. Pre-registering permissions
> (step 2) is good hygiene but the runtime scope list in code is what drives consent.

Then add to `.env`, `.env.test`, `.env.production` (and `.env.example` with blanks):

```
MICROSOFT_CLIENT_ID=<appId>
MICROSOFT_CLIENT_SECRET=<secret from step 3>
```

---

## 5. Microsoft Graph reference (what the code will call)

- **Auth authority:** `https://login.microsoftonline.com/common`
  (handles both personal + work accounts). Token endpoint is under
  `.../common/oauth2/v2.0/token`.
- **Scopes (runtime):** `["Mail.Read", "User.Read"]` — MSAL adds `offline_access`,
  `openid`, `profile` implicitly and always returns a refresh token when the app is
  configured for it. If requesting refresh explicitly, include `offline_access`.
- **Profile (for `provider_email`):** `GET https://graph.microsoft.com/v1.0/me`
  → `{ "mail": "...", "userPrincipalName": "..." }` (use `mail`, fall back to `userPrincipalName`).
- **Delta (incremental Inbox sync):**
  `GET https://graph.microsoft.com/v1.0/me/mailFolders/inbox/messages/delta`
  with `Prefer: odata.maxpagesize=50`. Follow `@odata.nextLink` (skipToken) until you
  get `@odata.deltaLink`; persist the deltaLink. Next run, GET the deltaLink to receive
  only created/updated/deleted since last time. `@removed` entries mean deleted/moved.
  Invalid/expired deltaToken → **410 Gone** → discard cursor and full-resync.
- **Full message (per changed id):**
  `GET https://graph.microsoft.com/v1.0/me/messages/{id}` with header
  `Prefer: outlook.body-content-type="text"` so `body.content` is plain text
  (populates `body_text`, which the LLM uses).
- **Attachments:**
  `GET https://graph.microsoft.com/v1.0/me/messages/{id}/attachments`
  → collection. `fileAttachment` entries carry `contentBytes` (base64, **standard**
  base64 not urlsafe), `name`, `contentType`, `size`, `isInline`, `contentId`.
  Inline images are `fileAttachment` with `isInline = true` — so the attachments
  collection covers both regular files and inline images (no MIME-tree walk needed,
  unlike Gmail).

### Message field → DB column mapping

| DB column (after rename) | Graph field | Notes |
|---|---|---|
| `provider_message_id` | `id` | Opaque. Changes if message moves folders unless `Prefer: IdType="ImmutableId"` — not needed for Inbox-only v1. |
| `thread_id` | `conversationId` | |
| `subject` | `subject` | |
| `from_email` / `from_name` | `from.emailAddress.address` / `.name` | |
| `to_emails` | `toRecipients[].emailAddress.address` | array |
| `date_sent` | `receivedDateTime` | already ISO-8601 UTC; no strptime needed |
| `snippet` | `bodyPreview` | first 255 chars, plain text |
| `body_text` | `body.content` (with text Prefer header) | LLM input |
| `body_html` | `body.content` (html) | v1: leave null (see §7.3). Optional follow-up. |
| `has_attachments` | `hasAttachments` | excludes inline (same caveat as Gmail) |
| `provider_labels` | *synthesized* | see below |
| `email_provider` | constant `'outlook'` | |

### Synthesized `provider_labels` for Outlook

Build a `list[str]` of Gmail-style tokens so the existing flag trigger works unchanged:

| Condition | Token added | Trigger sets |
|---|---|---|
| `isRead == false` | `"UNREAD"` | `is_unread` |
| `importance == "high"` | `"IMPORTANT"` | `is_important` |
| `flag.flagStatus == "flagged"` | `"STARRED"` | `is_starred` |

We sync **only the Inbox**, so `is_spam`/`is_trash` are always false for Outlook v1
(Junk/Deleted are separate folders); a message moved out of Inbox arrives as
`@removed`. The Gmail-only category flags (`is_promotions`, `is_social`, `is_forums`,
`is_updates`, `is_primary`) stay false — Outlook has no equivalent.

---

## 6. Database migration

Two migration files (the enum `ADD VALUE` must be isolated — see note).

### `supabase/migrations/20260710000001_generalize_email_provider_columns.sql`

```sql
-- Rename Gmail-specific columns to provider-agnostic names
alter table public.emails       rename column gmail_id            to provider_message_id;
alter table public.emails       rename column gmail_label_ids     to provider_labels;
alter table public.attachments  rename column gmail_attachment_id to provider_attachment_id;
alter table public.integrations rename column last_history_id     to sync_cursor;

-- Provider discriminator on emails
alter table public.emails add column email_provider text not null default 'gmail';

-- Swap the unique key to include provider.
-- NOTE: verify the existing constraint name with `\d emails` first — Postgres
-- auto-named `unique(user_id, gmail_id)`; it is typically `emails_user_id_gmail_id_key`.
alter table public.emails drop constraint emails_user_id_gmail_id_key;
alter table public.emails add constraint emails_user_provider_message_key
    unique (user_id, email_provider, provider_message_id);

-- Rename the index for clarity (optional but keeps naming consistent)
alter index idx_emails_gmail_id rename to idx_emails_provider_message_id;

-- Retarget the flag trigger to the renamed column
drop trigger parse_gmail_labels_trigger on public.emails;
drop function public.parse_gmail_labels();

create or replace function public.parse_provider_labels()
returns trigger as $$
begin
    new.is_spam       := 'SPAM'                = any(new.provider_labels);
    new.is_trash      := 'TRASH'               = any(new.provider_labels);
    new.is_promotions := 'CATEGORY_PROMOTIONS' = any(new.provider_labels);
    new.is_social     := 'CATEGORY_SOCIAL'     = any(new.provider_labels);
    new.is_updates    := 'CATEGORY_UPDATES'    = any(new.provider_labels);
    new.is_forums     := 'CATEGORY_FORUMS'     = any(new.provider_labels);
    new.is_primary    := 'CATEGORY_PERSONAL'   = any(new.provider_labels);
    new.is_important  := 'IMPORTANT'           = any(new.provider_labels);
    new.is_starred    := 'STARRED'             = any(new.provider_labels);
    new.is_unread     := 'UNREAD'              = any(new.provider_labels);
    return new;
end;
$$ language plpgsql;

create trigger parse_provider_labels_trigger
    before insert or update of provider_labels on public.emails
    for each row execute function public.parse_provider_labels();
```

### `supabase/migrations/20260710000002_add_outlook_provider.sql`

```sql
-- Must be its own migration: a new enum value cannot be used in the same
-- transaction that adds it, and Supabase wraps each migration in a transaction.
alter type integration_provider add value if not exists 'outlook';
```

Apply locally with `supabase db reset`; push to staging/prod with `supabase db push --linked`.
Update [`docs/database-schema.md`](../database-schema.md) to reflect the renamed columns
and new `email_provider` column.

---

## 7. Backend implementation

### 7.1 Config — `backend/selko/config.py`

Add two fields to `Config` and load them in `load_config()`:

```python
microsoft_client_id: Optional[str] = None
microsoft_client_secret: Optional[str] = None
# ...
microsoft_client_id=os.getenv("MICROSOFT_CLIENT_ID"),
microsoft_client_secret=os.getenv("MICROSOFT_CLIENT_SECRET"),
```

Add `msal` and `requests` to `pyproject.toml` dependencies (run `uv add msal requests`).
(`requests` is already present transitively via google libs, but declare it explicitly.)

### 7.2 New service — `backend/selko/services/outlook.py`

Mirror the public surface of `services/gmail.py`. Suggested functions:

```python
GRAPH = "https://graph.microsoft.com/v1.0"
AUTHORITY = "https://login.microsoftonline.com/common"
SCOPES = ["Mail.Read", "User.Read"]          # offline_access added by MSAL

class OutlookError(Exception): ...

def _msal_app(config) -> msal.ConfidentialClientApplication:
    return msal.ConfidentialClientApplication(
        client_id=config.microsoft_client_id,
        client_credential=config.microsoft_client_secret,
        authority=AUTHORITY,
    )

# --- OAuth (used by API route + CLI) ---
def build_auth_url(config, state, redirect_uri) -> str
def exchange_code(config, code, redirect_uri) -> dict   # returns token result
def get_access_token(client, config, user_id) -> str    # load DB tokens, refresh if expired

# --- Graph REST helpers ---
def _graph_get(access_token, url, *, params=None, prefer=None) -> dict
def get_user_profile(access_token) -> dict              # GET /me → {mail|userPrincipalName}

# --- Delta sync ---
def fetch_message_changes(access_token, delta_link: str | None) -> tuple[list[dict], str]:
    """Return (changes, new_delta_link).
    changes: list of {"id", "removed": bool} for created/updated/deleted.
    Handles paging (@odata.nextLink) and 410 (return sentinel to trigger resync)."""

def get_full_message(access_token, message_id) -> dict  # GET /me/messages/{id}, Prefer text body
def list_attachments(access_token, message_id) -> list[dict]

# --- Parsing (pure functions, easy to unit test) ---
def synthesize_labels(msg: dict) -> list[str]
def parse_outlook_message(msg: dict) -> dict            # → DB dict, mirrors parse_gmail_message
```

**Token handling.** Microsoft tokens are **not** `google.oauth2.credentials.Credentials`,
so do not route them through the google-auth path. `get_access_token`:

1. Read the integrations row for `(user_id, provider='outlook')` (reuse a helper — see 7.4).
2. If `token_expiry` is in the future, return the stored `access_token`.
3. Else call `_msal_app(config).acquire_token_by_refresh_token(refresh_token, scopes=SCOPES)`.
   - On success, persist the new `access_token`, `refresh_token` (MSAL may rotate it),
     and expiry (`now + expires_in`) via the generic updater in 7.4; return the token.
   - On failure (`error == "invalid_grant"`), set integration status `expired` and raise.

**`parse_outlook_message`** returns a dict with the same shape `save_emails` expects,
plus the new provider fields:

```python
{
  "email_provider": "outlook",
  "provider_message_id": msg["id"],
  "thread_id": msg.get("conversationId"),
  "subject": msg.get("subject"),
  "from_email": (msg.get("from") or {}).get("emailAddress", {}).get("address"),
  "from_name":  (msg.get("from") or {}).get("emailAddress", {}).get("name") or None,
  "to_emails": [r["emailAddress"]["address"] for r in msg.get("toRecipients", [])
                if r.get("emailAddress", {}).get("address")] or None,
  "date_sent": msg.get("receivedDateTime"),          # already ISO-8601
  "snippet": msg.get("bodyPreview"),
  "provider_labels": synthesize_labels(msg),
  "has_attachments": bool(msg.get("hasAttachments")),
  # body_text set when body.contentType == "text"
}
```

### 7.3 Body handling

Fetch the full message with `Prefer: outlook.body-content-type="text"` so
`body.content` is plain text → `body_text`. Set `body_html = None` for v1.

- **Why:** the LLM extractor uses `body_text or snippet` — plain text is exactly what
  it needs, and one GET per message keeps quota low.
- **Consequence:** the HTML-based image extractors (`extract_linked_images`,
  `extract_data_uri_images` in `services/email_images.py`) won't run for Outlook. That's
  fine — inline images arrive as `fileAttachment isInline=true` and are captured by the
  attachment path (7.5). If HTML body is wanted later, do a second GET with the html
  Prefer header; deferred.

### 7.4 Generalize `backend/selko/services/integrations.py`

The google-specific pieces to branch by provider:

- **Scope map** in `initiate_oauth_flow` / `complete_oauth_flow`: add an `outlook` branch.
  For `outlook`, don't use `google_auth_oauthlib.flow.Flow`; call the MSAL helpers in
  `outlook.py` (`build_auth_url`, `exchange_code`). The `oauth_states` table + CSRF
  state logic is reused as-is (it's provider-independent).
- **`get_oauth_credentials`** hardcodes Google's `token_uri` and returns google
  `Credentials`. Leave it for Google providers; Outlook uses `outlook.get_access_token`
  instead (do not reconstruct google Credentials for Outlook).
- Add a small generic updater used by Outlook refresh:

```python
def update_provider_tokens(client, provider, *, access_token, refresh_token,
                           token_expiry, user_id):
    client.table("integrations").update({
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_expiry": token_expiry,   # ISO string, UTC
        "status": "active",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("user_id", user_id).eq("provider", provider).execute()
```

`save_oauth_credentials` is google-`Credentials`-typed. Add an Outlook-friendly path
(either overload or a sibling `save_provider_tokens(...)`) that writes `access_token`,
`refresh_token`, `token_expiry`, `scopes`, `provider_email` directly from an MSAL result.

### 7.5 Attachments — `backend/selko/services/attachments.py`

Outlook returns attachment bytes inline (`contentBytes`, standard base64), so there is
no per-attachment download call like Gmail's. Add a provider-agnostic storage path:

- Add `store_attachment_bytes(client, email_id, *, data, filename, mime_type, config,
  provider_attachment_id="")` that does the existing hash-dedup → upload → metadata
  flow (factor it out of `process_attachment` / `store_image_content`, which already
  share that logic).
- `save_attachment_metadata` param `gmail_attachment_id` → `provider_attachment_id`
  (column renamed in migration). Update all callers.

Outlook ingestion loop, per changed message:

```
for att in list_attachments(token, msg_id):
    if att["@odata.type"] == "#microsoft.graph.fileAttachment":
        data = base64.b64decode(att["contentBytes"])   # NB: standard b64, not urlsafe
        store_attachment_bytes(client, email_id, data=data,
                               filename=att["name"], mime_type=att["contentType"],
                               config=config, provider_attachment_id=att["id"])
    # itemAttachment / referenceAttachment: skip in v1 (log + continue)
```

Respect `config.max_attachment_size` (same as Gmail path).

### 7.6 Worker + scheduler — `backend/selko/workers/email_fetch.py`

- **`schedule_email_fetches()`**: currently filters `provider == 'gmail'`. Change to
  fetch active integrations for **both** `gmail` and `outlook`, and include the
  provider in the task payload: `{"user_id", "provider", "max_emails"}`. Keep the
  "skip if a pending/processing email_fetch task already exists for this user"
  dedup — but key it on `(user_id, provider)` so Gmail and Outlook don't block each
  other (store provider in payload and check accordingly, or add provider to the
  skip query).
- **`process_email_fetch_task()`**: branch on `payload["provider"]`:
  - `gmail` → existing path (`gmail.get_credentials` → `fetch_messages` →
    `parse_gmail_message` → `save_emails`).
  - `outlook` → new path:
    1. `token = outlook.get_access_token(client, config, user_id)`; return if none.
    2. Read `sync_cursor` (deltaLink) from the integration row.
    3. `changes, new_cursor = outlook.fetch_message_changes(token, cursor)`.
    4. For each non-removed change: `msg = get_full_message(...)`,
       `parsed = parse_outlook_message(msg)`, `save_emails(client, [parsed], user_id)`,
       then attachments (7.5).
    5. For each removed change: mark the matching email `is_trash`/deleted (best-effort;
       find by `email_provider='outlook'` + `provider_message_id`).
    6. Persist `new_cursor` to `integrations.sync_cursor`.
  - On a 410/resync sentinel from `fetch_message_changes`, clear the cursor and re-run
    a full sync (cursor `None`).

- **`services/emails.py`**: `save_emails` `on_conflict` changes from `"user_id,gmail_id"`
  to `"user_id,email_provider,provider_message_id"`. Rename internal `gmail_id` dict keys
  and mapping vars. `parse_gmail_message` keeps its name but emits the renamed keys
  (`provider_message_id`, `provider_labels`, `email_provider="gmail"`).

### 7.7 Circuit breaker — `backend/selko/workers/pool.py`

`pool.py` keys the breaker `"gmail"` and maps `task_type "email_fetch" → "gmail"`. Make
the breaker key provider-aware (e.g. `f"email:{provider}"`, or `"outlook"` vs `"gmail"`)
so a Graph outage doesn't trip the Gmail breaker and vice-versa.

### 7.8 API routes — `backend/selko/api/routes/integrations.py`

- Add `GET /integrations/outlook/auth` mirroring `gmail_oauth_initiate` (provider
  `"outlook"`). It reuses `_oauth_initiate_response`, which calls `initiate_oauth_flow`
  (now provider-aware).
- Add `GET /integrations/microsoft/callback` (separate from Google's callback because
  the IdP and token exchange differ). It validates state via the existing
  `complete_oauth_flow` (outlook branch), fetches the profile via
  `outlook.get_user_profile` for `provider_email`, saves tokens, and redirects to the
  SPA with `_frontend_oauth_redirect(...)`.
- Extend the redirect allowlist: add `/integrations/microsoft/callback` to
  `ALLOWED_REDIRECT_PATHS`. Hosts already covered by `_allowed_redirect_hosts()`.

### 7.9 API schemas — `backend/selko/api/schemas/`

- `emails.py`: `gmail_id → provider_message_id`, `gmail_label_ids → provider_labels`,
  add `email_provider: str`. Fix the `EmailSyncResponse` docstring ("fetched from Gmail").
- `attachments.py`: `gmail_attachment_id → provider_attachment_id`.

### 7.10 Other backend reads of the renamed columns

Update these to the new names (they treat the id as opaque):

- `services/event_processing.py` (`email_metadata["gmail_id"]`, `email.get("gmail_id")`)
- `services/ics_parser.py` (`email_metadata["gmail_id"]`)
- `cli/cli_extract_events.py` (`input_data["gmail_id"]`)

Keep the internal metadata key name if you like (it's just a dict key), but the DB
column it reads from is now `provider_message_id`.

---

## 8. CLI

- **New `cli/cli_auth_outlook.py`** mirroring `cli_auth_gmail.py`: sign in as the test
  user, run the MSAL auth-code flow (open browser to `build_auth_url`, run a tiny local
  server on the redirect port to capture `code`, call `exchange_code`), fetch profile,
  `save_provider_tokens(client, user_id, "outlook", token_result, provider_email)`.
- **`cli/cli_seed_tokens.py`**: add `"outlook"` to the `--provider` choices and copy the
  renamed `sync_cursor` field instead of `last_history_id`.
- **`cli/cli_fetch_emails.py`**: it imports `parse_gmail_message` — either add a
  `--provider outlook` branch or leave Gmail-only for now (note in help text).

---

## 9. Frontend & mobile

The flag columns are unchanged, and `emails.js` / `integrations.js` use `select('*')`,
so **no Supabase query strings change**. Changes are limited to types, provider enums,
and the connect UI.

### Web (`frontend/`)

- `src/lib/types.js`: add `'outlook'` to `IntegrationProvider`; rename `Email.gmail_id →
  provider_message_id`, `Email.gmail_label_ids → provider_labels`, add `email_provider`.
- `src/lib/api/backend.js`: add `initiateOutlookAuth()` (hits `/integrations/outlook/auth`),
  parallel to `initiateGmailAuth()`.
- `src/routes/app/settings/+page.svelte`: add an `outlook` case in `handleAuthorize`,
  a provider display name, and a connect button via `IntegrationStatus`.
- `src/lib/components/IntegrationStatus.svelte`: render the Outlook row/button.
- `src/lib/i18n/en.json`: add `integrations.outlook` label.
- Follow web platform rules in `CLAUDE.md` (DaisyUI semantic colors, svelte-check).

### iOS (`ios/`) and Android (`android/`)

- Add `outlook` to the integration provider enum/model
  (`ios/Selko/Features/Integrations/Models/Integration.swift`, Android equivalent).
- Rename `gmail_id`/`gmail_label_ids` in the `Email` models to the new columns.
- Add an Outlook "Connect" affordance in Settings (mirror Gmail; iOS pure SwiftUI,
  Android Compose Material3 — per `CLAUDE.md`).

---

## 10. Testing

- **`backend/tests/test_outlook.py`** (pure-function unit tests, no network):
  - `parse_outlook_message` maps every field correctly (from/to/date/subject/snippet).
  - `synthesize_labels`: unread → `UNREAD`; high importance → `IMPORTANT`; flagged →
    `STARRED`; read/normal/unflagged → empty. Then assert the flag trigger result via
    an integration test (or test the Python mapping directly).
  - Attachment parsing: `contentBytes` decoded with **standard** base64; `isInline`
    handled; non-file attachment types skipped.
  - `fetch_message_changes`: paging via `@odata.nextLink`; returns deltaLink; `@removed`
    entries flagged; 410 → resync sentinel. Mock `requests` with `unittest.mock`.
  - Token refresh: expired token triggers `acquire_token_by_refresh_token`; `invalid_grant`
    sets status `expired`. Mock the MSAL app.
- **Worker dispatch** (`test_email_fetch` / `test_workers`): `process_email_fetch_task`
  routes to the Outlook path when `payload["provider"] == "outlook"`;
  `schedule_email_fetches` enqueues for both providers.
- **Migration/regression:** existing Gmail tests must pass after the rename (update any
  fixtures using `gmail_id`/`gmail_label_ids`).
- Run: `uv run pytest backend/tests/ -v` and `npm run test:unit` (frontend). Android
  unit tests run in CI.
- **Screenshots** (DoD, UI changed): `./scripts/capture-all-screenshots.sh web` (and
  `ios`/`android` if their settings UI changed). Review the Settings screen shows the
  Outlook connect button.

### Manual end-to-end (staging)

1. `ENVIRONMENT=staging uv run python -m cli.cli_auth_outlook` (consent with a real
   outlook.com account).
2. Trigger a fetch (scheduler or a manual task) and confirm rows land in `emails` with
   `email_provider='outlook'`, correct flags, and attachments in storage.
3. Confirm the worker pool extracts events as it does for Gmail.

---

## 11. Suggested PR sequencing

Each is a worktree + branch + PR (see `CLAUDE.md` / `docs/parallel-agents.md`). The
migration renames columns, so **backend + clients that read those columns must ship
together** — do the rename and all reference updates in one PR to avoid a broken window.

1. **PR 1 — schema rename + reference updates** (migration, trigger, all backend/API/
   client column renames; no Outlook yet). Pure refactor; Gmail keeps working. Ship and
   verify green before layering Outlook on top.
2. **PR 2 — Outlook backend** (config, `services/outlook.py`, integrations branching,
   attachments path, worker dispatch, API routes, CLI auth). Behind the need for
   `MICROSOFT_CLIENT_ID/SECRET`; safe to merge without clients.
3. **PR 3 — clients** (web + iOS + Android connect UI, provider enums, i18n, screenshots).

---

## 12. Risks & open questions

- **Enum `ADD VALUE` in a transaction.** Keep it in its own migration (§6); don't
  reference `'outlook'` in the same file.
- **Exact unique-constraint name.** Verify with `\d emails` before `DROP CONSTRAINT`
  (auto-generated names can differ).
- **Personal-account Graph quirks.** Delta and delegated Mail.Read are supported for
  personal accounts, but validate against a real outlook.com account early (some Graph
  features differ between consumer and work tenants).
- **base64 flavor.** Outlook `contentBytes` is **standard** base64 (`base64.b64decode`),
  unlike Gmail's urlsafe — a common bug source.
- **Deferred `body_html`.** v1 stores text only; if a future feature needs HTML image
  extraction for Outlook, add a second GET with the html Prefer header.
- **Token security.** Tokens are stored plaintext in `integrations` today (same as
  Gmail). This spec matches existing behavior; encryption-at-rest is a separate concern.
```
