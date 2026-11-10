# Selko for Claude (MCP)

Selko exposes its review queue and calendar to Claude through a remote MCP
server at **`https://api.selkoapp.com/mcp`**. Claude can tell you what Selko
found in your email, accept or reject events and changes for you, and run that
on a schedule, for example a morning digest.

- [Connect Claude](#connect-claude): claude.ai, Claude Desktop, mobile, Claude Code
- [Run it on a schedule](#run-it-on-a-schedule)
- [What Claude can do](#tools)
- [How it works](#how-it-works) and [operating it](#operating-it)
- [Design notes](#design-notes): the research behind the choices

## Connect Claude

All you need is the URL, **`https://api.selkoapp.com/mcp`**. Claude registers
itself with Selko automatically, then opens Selko's own login page, where you
sign in and choose **Allow**. Nothing to paste.

### claude.ai, Claude Desktop and Claude mobile

These share one connector list, so add it once on the web or in Desktop.

1. Open **Settings → Connectors** (claude.ai/customize/connectors) and choose
   **Add custom connector**.
2. Name: `Selko`. Remote MCP server URL: `https://api.selkoapp.com/mcp`.
   Leave **Advanced settings** empty and choose **Add**.
3. Choose **Connect**. A Selko page opens: sign in if asked, check that it says
   *Connect Claude to Selko* with your account, and choose **Allow**.
4. In a chat, enable Selko from the tools menu and ask *"What's waiting in
   Selko?"*. In Desktop and on the web, the queue appears as cards with
   Accept / Reject buttons.

Claude asks before running tools that change your calendar (accept, reject),
and runs the read-only ones without asking. You can change that per tool in
the connector's settings.

### Claude Code (CLI)

```bash
claude mcp add --transport http --scope user selko https://api.selkoapp.com/mcp
```

Then run `/mcp` inside `claude`, pick **selko → Authenticate**, and approve in
the browser. Claude Code stores the token in the keychain and refreshes it, so
later `claude -p` runs use it without a browser.

### Disconnecting

Selko → **Settings → Connected apps → Disconnect** revokes Claude's grant. Its
token stops working within a minute. Removing the connector in Claude only
forgets the token on Claude's side.

## Run it on a schedule

Pick one. All three use the same connector; the difference is where the run
happens and whether your computer must be on.

**Keep scheduled runs read-only** unless you have decided otherwise. A run
nobody watches should report, not decide: Selko's own rules (auto-approve
senders, automatic updates to events Selko created) already handle the
decisions that need no human. The examples below allow only read tools.

### A. Claude Code routine (cloud, runs with your computer off)

1. Connect Selko on claude.ai first (above). Routines use your claude.ai
   connectors.
2. In Claude Code run `/schedule`, or open claude.ai/code → **Routines** →
   **New routine**.
3. Schedule: e.g. weekdays at 07:00 in your timezone.
4. Connectors: enable **Selko** (and Gmail or Slack if you want the digest
   delivered there).
5. Prompt:

   ```text
   Use the Selko tools to write my morning calendar digest.
   1. list_review_queue: everything waiting for my decision. For each item give
      the title, when, where, who it came from, and for changes what changed
      (old → new). Put cancellations first.
   2. list_recent_activity with since_hours=24: what Selko already put on my
      calendar or updated since yesterday.
   3. get_account_status: if all_good is false, lead with what needs me and include each reconnect_url.
   Keep it under 15 lines. Do not accept or reject anything.
   ```

6. Optionally add *"Then email the digest to me with the Gmail connector"*.

### B. Claude Desktop scheduled task (runs while the app is open)

In Claude Desktop, open **Scheduled** (Code tab sidebar, or ask Claude to
*"schedule a task"*), create a task with the prompt above and a cron schedule
such as `0 7 * * 1-5`, and make sure the Selko connector is enabled for it. A
run that was due while the computer slept starts when it wakes.

### C. Headless `claude -p` from launchd or cron (any machine with Claude Code)

After connecting Claude Code (above), this runs the digest with only the read
tools allowed, so it cannot change anything even if asked to:

```bash
claude -p "Use the Selko tools to write my morning calendar digest: what is waiting in list_review_queue, what changed in list_recent_activity over the last 24 hours, and any account in get_account_status that needs reconnecting. Under 15 lines. Do not accept or reject anything." --allowedTools "mcp__selko__list_review_queue,mcp__selko__list_recent_activity,mcp__selko__get_account_status,mcp__selko__get_event,mcp__selko__list_calendar_events"
```

macOS, weekdays at 07:00, written to a file:
`~/Library/LaunchAgents/com.selko.digest.plist`

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>com.selko.digest</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string><string>-lc</string>
    <string>claude -p "$(cat ~/.selko-digest-prompt.txt)" --allowedTools "mcp__selko__list_review_queue,mcp__selko__list_recent_activity,mcp__selko__get_account_status" &gt; ~/selko-digest.md</string>
  </array>
  <key>StartCalendarInterval</key>
  <array>
    <dict><key>Weekday</key><integer>1</integer><key>Hour</key><integer>7</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Weekday</key><integer>2</integer><key>Hour</key><integer>7</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Weekday</key><integer>3</integer><key>Hour</key><integer>7</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Weekday</key><integer>4</integer><key>Hour</key><integer>7</integer><key>Minute</key><integer>0</integer></dict>
    <dict><key>Weekday</key><integer>5</integer><key>Hour</key><integer>7</integer><key>Minute</key><integer>0</integer></dict>
  </array>
</dict>
</plist>
```

```bash
launchctl load ~/Library/LaunchAgents/com.selko.digest.plist
```

If a headless run reports that Selko needs authentication, the refresh token
has expired or the grant was revoked: run `/mcp` interactively once.

### Letting a schedule decide

If you do want an unattended run to act, give it a narrow, explicit rule and
only the tools it needs, for example *"accept New-lane events whose source is
from `office@school.example`; list everything else"* with
`mcp__selko__accept_event` added to `--allowedTools`. `reject_event` is
deliberately terminal (later emails never revive a rejected event), so keep it
out of unattended runs. For a sender you always trust, Selko's own
**Auto-approve sender** rule is the better tool: it runs on every email, not once
a day.

## Tools

| Tool | Kind | What it does |
|---|---|---|
| `list_review_queue` | read, **widget** | New and Changes lanes, upcoming only, with counts, source email subject/sender, and field-level diffs for changes |
| `get_event` | read | One event: description (≤1,500 chars), status, pending change, every source email (subject, sender, time) |
| `list_calendar_events` | read | Accepted events in a date range with calendar delivery status |
| `list_recent_activity` | read | Events found or changed in the last N hours, incl. automatic updates |
| `get_account_status` | read | Every Google/Outlook sign-in: is mail being read (last check, failing polls), can events reach a calendar, accepted events parked on a lapsed sign-in, catch-up progress; `all_good` plus `needs_attention` (problem, action, `reconnect_url`); lane counts |
| `reconnect_account` | write | Direct Google or Microsoft sign-in link for this user (`initiate_oauth_flow`, 10-minute state), plus the non-expiring Settings link |
| `accept_event` | write | New lane → calendar (`set_event_review_status` → `active`) |
| `reject_event` | write, destructive | New lane → rejected (terminal) |
| `accept_change` | write, destructive | Apply a pending update or cancellation to the calendar entry |
| `reject_change` | write | Discard a pending change; calendar unchanged |
| `check_email_now` | write, idempotent | `request_email_sync_now` for each active mailbox |

Prompt: `daily_digest` (the read-only digest above, as a slash command).

### Connection health on every answer

Every tool except `get_account_status` and `reconnect_account` attaches
`connection_alert` when a sign-in needs the user — a lapsed Google or Microsoft
sign-in, Google consent without Calendar, an Outlook mail-only grant with no
other writable calendar, polls failing on auth, or accepted events parked
`blocked` with `oauth_required`/`oauth_scope_required`. Self-healing problems
(transient poll failures, a mailbox not checked for six hours) appear only in
`get_account_status` as `action: "wait"`, so the alert is never noise Claude
learns to ignore. Each problem clears without bookkeeping: signing in again
flips the integration to `active` and recovery requeues parked work. The
verdict lives in `selko/api/mcp/connections.py` and mirrors the web banner's
`recoveryPlan`; it reads `email_sync_health` (the safe `security_invoker`
view), never `email_sync_state`. The check is best effort: if it fails, the
tool still answers and the failure is logged as `mcp_connection_check_failed`.
The review widget shows the alert above the cards with a sign-in button, so an
empty queue caused by a lapsed sign-in is not presented as "nothing to review".

**Reauth.** Selko cannot complete a provider consent inside Claude; the user
must open a browser. Two links: `reconnect_url`
(`/app/settings?reconnect=google|outlook`) never expires — Settings starts the
sign-in on open, and a signed-out user returns to it after login via `next` —
which is what a scheduled digest read hours later needs; `reconnect_account`
returns the provider's own consent URL for a live chat, bound to the caller's
user id through the same `oauth_states` row the apps create, valid 10 minutes.

Times are returned in the user's timezone (`user_calendar_settings.timezone`).
Email bodies and attachments never leave Selko through MCP.

## How it works

```
Claude ──(1) POST /mcp, no token──────────────▶ Selko API (FastAPI, Render)
       ◀─ 401 WWW-Authenticate: resource_metadata=…/.well-known/oauth-protected-resource/mcp
       ──(2) GET protected-resource metadata ──▶ authorization_servers: [<supabase>/auth/v1]
       ──(3) OAuth 2.1 + PKCE ─────────────────▶ Supabase Auth OAuth server
                                                   └─▶ selkoapp.com/oauth/consent (sign in, Allow)
       ◀─ access + refresh token (JWT, client_id claim)
       ──(4) POST /mcp, Bearer token ──────────▶ verify with Supabase, check client_id allowlist
                                                   └─▶ PostgREST as the user (RLS) / review RPCs
```

- **Code:** `backend/selko/api/mcp/` (`server.py` tools, `operations.py` data
  path, `auth.py` verifier, `review_queue.html` widget, `static/` vendored
  `@modelcontextprotocol/ext-apps@2.0.4` runtime). Mounted into the existing
  API process by `create_app()`; no new service.
- **Transport:** streamable HTTP, stateless, JSON responses. Nothing is held in
  process memory between calls.
- **Authorization server:** Supabase Auth's OAuth 2.1 server (beta). Selko runs
  no OAuth code of its own beyond the consent page and the token check.
- **Audience:** Supabase sets `aud=authenticated` on every token and ignores the
  RFC 8707 `resource` parameter, so the audience cannot distinguish an MCP token
  from a browser session. The `client_id` claim can (only the OAuth server mints
  it), so the verifier requires it. A browser session token is refused at
  `/mcp`.
- **Registration:** dynamic client registration is on, as every MCP client
  expects: Claude registers itself when the connector is added. No client
  allowlist exists; the gate is the consent page, which names the app and
  shares nothing until the user chooses Allow.
- **Data access:** reads use the caller's token through PostgREST, so RLS
  applies exactly as in the apps. Writes reuse the apps' paths:
  `set_event_review_status`, `apply_change_proposal` / `reject_change_proposal`
  after an ownership check with the caller's token (as the REST route does), and
  `request_email_sync_now`.
- **Revocation:** validated tokens are cached for 60 s, so a revoked grant stops
  working within a minute.
- **Widget:** `list_review_queue` declares `_meta.ui.resourceUri =
  ui://selko/review-queue.html`. Hosts with MCP Apps support render cards that
  call `accept_*` / `reject_*` through `callServerTool` and tell Claude what
  was decided with `updateModelContext`. Other hosts and scheduled runs get the
  same data as JSON.

## Operating it

| Environment | Authorization server | Consent page | Client |
|---|---|---|---|
| Local | `http://127.0.0.1:54321/auth/v1` (`supabase/config.toml` `[auth.oauth_server]`; restart supabase after changing it) | `http://127.0.0.1:3000/oauth/consent` | self-registered per test, removed after |
| Production | `https://khahcozfbnpykspvatrg.supabase.co/auth/v1` | `https://selkoapp.com/oauth/consent` | self-registered by each Claude surface |

Production settings (deploy logs `docs/deploy-log/2026-11-06-*`):

- Supabase auth config: `oauth_server_enabled=true`,
  `oauth_server_authorization_path=/oauth/consent`,
  `oauth_server_allow_dynamic_registration=true`, `site_url=https://selkoapp.com`
  (the consent path is resolved against `site_url`, **and** GoTrue refuses
  consent API calls whose `Origin` is not `site_url` — "unauthorized request
  origin". The consent page only works on the exact `site_url` origin, which
  is why `www.selkoapp.com` must keep redirecting to the apex).
Check the endpoint from outside:

```bash
curl -s https://api.selkoapp.com/.well-known/oauth-protected-resource/mcp
```

```bash
npx @modelcontextprotocol/inspector --cli https://api.selkoapp.com/mcp --transport http --method tools/list
```

The second one answers 401 without a token, which is correct.

**Tests:** `backend/tests/test_mcp_server.py` (verifier, tool contract and
annotations, widget, HTTP wiring, `create_app` mount) and
`backend/tests/integration/test_integration_mcp.py` (a real Supabase OAuth
grant from a self-registered client → MCP over HTTP → RLS and RPCs; session
tokens refused; revocation).

## Design notes

What the research said, and what Selko does with it.

**Deployment model.** Anthropic's connector guidance ranks a remote
streamable-HTTP server first for anything wrapping a cloud service: users add a
URL, one deployment serves every Claude surface (web, Desktop, mobile, Claude
Code, routines), and OAuth works because there is a real host to redirect to.
Local stdio servers are for prototypes. Selko already has an HTTPS API with the
right data access, so `/mcp` mounts into it.

**Auth.** Claude supports OAuth with DCR or CIMD, Anthropic-held credentials,
or no auth. User-pasted bearer tokens are not supported for claude.ai
connectors. The callback is `https://claude.ai/api/mcp/auth_callback` for every
hosted surface, plus a localhost loopback for Claude Code. Token endpoints must
accept form-encoded bodies, PKCE S256 is required, and discovery and token
calls have about a 10 s budget. Supabase's OAuth 2.1 server covers all of that.
Its tokens are ordinary Supabase JWTs, so RLS keeps working unchanged.
Supabase offers DCR (it does not support CIMD yet). DCR is how every other
MCP server works: the user adds a URL and lands on the service's login page.
The first version kept DCR off and pre-registered Claude, which made users
paste a client ID into Advanced settings. Nobody else's MCP asks for that, so
it was reverted the same day.

**Tool design** (the connector review criteria):

- Every tool has `title`, `readOnlyHint` and `destructiveHint`, which drive
  Claude's auto-approval.
- Reads and writes are separate tools, never one tool with a mode parameter.
- Names are ≤64 characters.
- Descriptions say what the tool does and does not do and point to the sibling
  tool, and never instruct the model (that counts as prompt injection in
  review).
- Errors are actionable ("Only events in the New lane … can be accepted").
- Results are compact. Claude.ai caps a tool result at about 150k characters
  and Claude Code at about 25k tokens.

Eleven tools is well inside the "one tool per action" range (<15). Tool names use
the apps' own words (Accept / Reject, New / Changes) so a user moving between
Selko and Claude sees one vocabulary.

**UI in Claude.** MCP Apps render a `ui://` HTML resource in a sandboxed iframe
when a tool declares `_meta.ui.resourceUri`. Desktop, web and mobile show it,
and other hosts fall back to text. Claude's design guidelines for inline
widgets:

- Fit the content height, with no nested scrolling.
- Show 4–5 data points per card and at most two actions.
- Leave out menus.
- Use the host's color and font tokens so the widget works in light and dark.
- Show a skeleton rather than a spinner, and keep tap targets at least 44 pt.
- Handle the toggle or confirm in the widget, and send free text back to chat.

The iframe CSP blocks CDN imports, so the runtime is inlined. Outbound links
must go through `app.openLink`.

A review queue fits this well: it is a list the user decides on, item by item,
which Claude cannot rank for them. The widget shows up to five cards, each with:

- title, a New / Changed / Cancelled tag, the time, place and sender;
- for changes, up to three `old → new` lines;
- two peer buttons in Selko's colors (green Accept, berry outline Reject).

A decided card collapses to a one-line confirmation, and the widget tells Claude
what was decided so it does not ask again. Beyond five cards it says "N more
waiting" and links to the app. Elicitation, the spec's native form, cannot show
a list with per-item actions, so a widget is the right tool here. Every other
tool stays plain JSON: account status, history and event detail read well as
Claude's prose.

**Scheduled runs.** The connector docs say nothing specific about unattended
use, so these choices follow from the auth model:

- Unattended runs keep working while the refresh token is valid.
- Revoking the grant stops them within a minute.
- Recommended prompts are read-only, and the headless example enforces that
  with `--allowedTools`.
- Rejection is terminal in Selko, so it stays out of unattended runs.
