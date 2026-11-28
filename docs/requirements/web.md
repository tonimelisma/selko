# Requirements: Web app

The SvelteKit web app (the only Selko client), how it talks to the API, its pages and design
contract, and the backend routes and static serving it depends on.

## API client and session

- **SEL-500** Selko's web app shall send every API request through `apiFetch` with the access
  token as an `Authorization: Bearer` header, JSON-encoded bodies, and query parameters whose
  undefined or null values are dropped. [verified]
- **SEL-501** When an API request answers 401, the web app shall refresh the access token once
  and retry the request once with the new token, returning a second 401 (or a failed refresh) as
  the request's error. [verified]
- **SEL-502** When several callers need a refresh at the same time, the web app shall send a
  single `POST /auth/token` refresh request whose result all of them share. [verified]
- **SEL-503** When a page loads, the web app shall restore the session with one
  `POST /auth/token` request carrying only `{"grant_type": "refresh_token"}` with
  `credentials: include`, and shall keep the returned access token in module memory only.
  [verified]
- **SEL-504** While a session is active, the web app shall renew the access token one minute
  before it expires. [verified]
- **SEL-505** If a refresh is refused (400, 401 or 403), then the web app shall clear the tab's
  session and announce SIGNED_OUT; if the server cannot be reached, then it shall keep the
  current session. [verified]
- **SEL-506** If restoring the session fails with a network error or a server error, then the
  web app shall report Selko as unavailable (not signed out), so the app layout shows a retry
  instead of the sign-in page. [verified]
- **SEL-507** When a tab signs in or out, the web app shall announce it on the `selko-auth`
  BroadcastChannel, and other tabs shall drop their access token on SIGNED_OUT and refresh
  from the shared cookie on SIGNED_IN. [verified]
- **SEL-508** When the user signs out, the web app shall `POST /auth/logout` with
  `{"scope": "global"}` and the Bearer token, and shall clear the local session even when that
  request fails. [verified]
- **SEL-509** If an API request has no answer within its timeout (30 s by default) or the
  network fails, then `apiFetch` shall resolve with an error whose code is `TIMEOUT` or
  `NETWORK_ERROR` and status 0, never rejecting. [verified]
- **SEL-510** When the API answers with an error, `apiFetch` shall read the message from a
  string `detail`, a `{code, message}` detail, or the first entry of a validation-error list.
  [verified]
- **SEL-511** Selko's web app source shall contain no database client: no `@supabase` import,
  no `supabase.` call, no PostgREST `.from(` on a client, no `.rpc(` call and no
  `VITE_SUPABASE_` variable. [verified]

## Sign-in, registration and redirect

- **SEL-515** When the user submits the sign-in form, the web app shall sign in with the
  password grant of `POST /auth/token`, and if the server refuses, then it shall show the
  server's message and stay on the sign-in page. [verified]
- **SEL-516** When an unauthenticated user opens a page under `/app`, the web app shall send
  them to `/login?next=<the encoded path and query they opened>`. [verified]
- **SEL-517** When sign-in succeeds, the web app shall go to the `next` path only if it is a
  same-origin path (it starts with a single `/`, not `//` or `/\`), and to `/app` otherwise.
  [verified]
- **SEL-518** When the user registers, the web app shall check that the two passwords match and
  are at least 6 characters before calling `POST /auth/signup`, shall not sign the user in, and
  shall tell them to sign in or, when `confirmation_required` is true, to check their email.
  [verified]
- **SEL-519** Selko's sign-in page shall link to the privacy policy and to the registration
  page. [verified]

## Review queue

- **SEL-520** When the review page loads, the web app shall read `GET /events/review`, which
  returns the user's events awaiting review soonest first, at most `limit` rows (default 200,
  1..500, 422 outside) with the total waiting in the `X-Total-Count` header. [verified]
- **SEL-521** Selko's review queue shall show an event in the New lane when its review_status is
  `pending_review` and in the Changes lane when it is `active` with a `pending`
  event_change_proposal. [verified]
- **SEL-522** Selko's review queue shall group each lane's events by sender, keep the order of
  the first server snapshot (not start time) within and across groups, and append a new card
  after its sender's known cards and a new sender after all known groups. [verified]
- **SEL-523** When an event leaves the queue and a live refetch arrives, the review queue shall
  keep the sender group in place and retain the removed event's rank, so Undo restores it to the
  same position. [verified]
- **SEL-524** When the user accepts or rejects an event, the web app shall remove the card at
  once and call `POST /events/{id}/accept` or `POST /events/{id}/reject`, refusing any other
  transition without calling the API. [verified]
- **SEL-525** When the user rejects events, the review page shall show one Undo toast ("Event
  rejected", or "N events rejected" for consecutive rejects) whose Undo restores every rejected
  event. [verified]
- **SEL-526** While the user has no writable calendar (an active Google Calendar connection or
  an active Outlook connection with the `Calendars.ReadWrite` scope), Selko shall disable Accept
  on review cards and event detail but keep the suggestion readable, editable and rejectable,
  and offer the reconnect. [verified]
- **SEL-527** When the user chooses Ignore sender, the web app shall call
  `POST /sender-rules/ignore-sender` with the sender's address and refetch the queue, and if the
  sender is not an email address, then it shall show that it cannot be ignored without calling
  the API. [verified]
- **SEL-528** When the user chooses Auto-approve sender, the web app shall create an
  `auto_approve` sender rule for that address and approve that sender's events in the queue.
  [verified]
- **SEL-529** When a Changes card has a pending proposal, Selko shall show each changed field's
  old value struck through beside the new value, and if an active event has no proposal, then
  it shall show "Change details are unavailable" and disable Accept and Reject. [verified]
- **SEL-530** If the integrations cannot be loaded, then the review page shall show the error
  instead of the setup screen. [verified]
- **SEL-531** While the user has no connected email account, the review page shall show the
  setup screen with a connect action. [verified]
- **SEL-532** When an event is accepted or rejected, Selko shall move keyboard focus to the
  next card in the queue. [verified]

## Event detail

- **SEL-535** When the event detail page opens, the web app shall show the event's fields and
  its source email, and if the event cannot be found, then it shall show an error. [verified]
- **SEL-536** When the user saves an edit, the web app shall `PATCH /events/{id}` with only the
  changed fields, and the API shall trim the title, refuse an empty body or a `user_id` field
  with 422, and return the whole event. [verified]
- **SEL-537** Selko's event detail page shall offer a download only for attachments whose
  ingestion_status is `stored`, fetching `GET /attachments/{id}/content` with the Bearer client
  and saving it under its filename, and list other attachments by name only. [verified]
- **SEL-538** When the web app reads an email, `GET /emails/{id}` shall return only id,
  email_provider, subject, from_email, from_name, date_sent, snippet and has_attachments.
  [verified]

## History

- **SEL-540** Selko's history page shall page decided events from `GET /events/activity`
  (default 20 per page, clamped to 1..500 by the client, 422 from the API outside that) with a
  Load More control that never repeats a row. [verified]
- **SEL-541** Selko's history page shall offer Undo for `synced` events, Retry for
  `sync_failed` events, and show `cancel_queued` events as "Cancellation queued" without Undo.
  [verified]
- **SEL-542** If an undo answers 409 `CALENDAR_DIVERGED`, then the history page shall show the
  differing fields (Selko's value and the calendar's) with a Force Undo that repeats the undo
  with `force: true`. [verified]
- **SEL-543** When the user retries a failed sync, the history page shall poll the event until
  the worker reports it synced (for up to 120 s), and restore Retry if the retry fails again.
  [verified]
- **SEL-544** When the user reprocesses an email, the history page shall queue it, disable
  Reprocess while it runs, and poll its processing state every 750 ms until it is processed or
  failed, stopping after 40 polls with a "taking longer" message. [verified]
- **SEL-545** Selko's email history (`GET /emails/history`) shall list processed, failed and
  calendar-invite emails with undated ones first, then newest `date_sent` first, ordered from
  the covering index `idx_emails_history_order`. [verified]

## Settings

- **SEL-548** Selko's settings page shall show one Google card for Gmail and Google Calendar,
  and its Disconnect shall remove both rows in one `POST /integrations/disconnect` request.
  [verified]
- **SEL-549** Selko's settings page shall list the calendars of each connected writable
  provider grouped by provider for choosing the target calendar, and prompt to reconnect
  Outlook when its connection lacks the calendar scope. [verified]
- **SEL-550** When the user saves calendar settings, the web app shall `PATCH /settings/calendar`
  with only the changed fields, and the API shall refuse an unknown timezone or a custom all-day
  end not later than its start with 422. [verified]
- **SEL-551** Selko's settings page shall list each mail account's user folders from
  `GET /integrations/{provider}/folders` with any recommendation reason, toggle each with a
  labeled switch, and if saving a folder fails, then roll back only that row. [verified]
- **SEL-552** When the user adds a sender rule, the sender rules panel shall create a
  `sender_email` rule for input containing `@` and a `sender_domain` rule otherwise, and the API
  shall refuse a duplicate rule with 409. [verified]
- **SEL-553** When the user deletes a sender rule, the sender rules panel shall ask for
  confirmation and run deletions one at a time, so an earlier completion cannot clear a later
  error. [verified]

## Connection recovery

- **SEL-556** While every connection works, the ConnectionRecovery card shall show nothing.
  [verified]
- **SEL-557** If a Google connection (Gmail or Google Calendar) lapsed, then the
  ConnectionRecovery card shall ask to reconnect the Google account with one Reconnect Google
  button and say whether mail, calendar or both are affected. [verified]
- **SEL-558** If the Outlook connection lapsed, then the ConnectionRecovery card shall ask to
  reconnect Outlook, and if both Google and Outlook lapsed, then offer both buttons. [verified]
- **SEL-559** While the user reads mail but has no writable calendar, the ConnectionRecovery
  card shall offer to connect a calendar (Google Calendar for a Gmail user, Outlook Calendar for
  a mail-only Outlook user), and shall not prompt for a lapsed Google Calendar while an Outlook
  calendar works. [verified]

## Live updates

- **SEL-562** When a user is signed in, the web app shall open one `GET /live` server-sent-event
  stream per tab with a streaming fetch carrying the Bearer header, never a token in the URL.
  [verified]
- **SEL-563** When the stream sends `ready`, the web app shall refetch every subscribed
  resource, and when it sends `invalidate`, hand it, debounced by 350 ms per resource, to that
  resource's subscribers, ignoring resources outside events, event_sources,
  event_change_proposals, calendar_work_items, emails and integrations. [verified]
- **SEL-564** If the stream ends, fails, answers 429, or is silent for 60 s, then the web app
  shall reconnect after a backoff that starts at 1 s, doubles per attempt, caps at 60 s and
  resets on `ready`. [verified]
- **SEL-565** When the stream sends `revoked`, the web app shall stop for good; when it sends
  `reauth`, reconnect; and when it answers 401, refresh once and reconnect with the new token,
  or stop if the refresh fails. [verified]
- **SEL-566** When events and event_sources invalidations arrive together, the review page
  shall refetch the queue once. [verified]
- **SEL-567** While a `/live` stream is open, Selko shall send it only invalidations for the
  token's own user, answer 401 without a token and 429 beyond 5 streams per user, send
  `revoked` on sign-out and `reauth` when the token expires. [verified]

## Design contract

- **SEL-570** Selko's web CSS shall contain every light and dark color of `design/tokens.json`
  and set `--control-height` to `control.minimumTarget` (48 px), `--input-height` to 46 px and
  the control radius, gap, gutter and review width from the same file. [verified]
- **SEL-571** Selko's design tokens shall meet 4.5:1 contrast for text and status tags, 7:1 for
  action labels on their fills, and 3:1 for action fills against surface and paper, in both
  themes. [verified]
- **SEL-572** Selko shall show the NEW tag in the neutral `newForeground`/`newBackground` tokens,
  never in the success colors.
  unverified: the token contract test checks the NEW pair's contrast, not its hue or that the
  badge uses it; checked by screenshot review.
- **SEL-573** Selko shall make every button and input target at least 48 px high.
  unverified: the test checks the CSS variable's value, not rendered controls; checked by
  screenshot review.
- **SEL-574** Selko's Included/Excluded control shall be a labeled switch with role `switch`,
  `aria-checked`, visible state text and a check mark, operable from the keyboard and inert
  while disabled. [verified]
- **SEL-575** Selko's web app shall start in the `selko-light` theme and switch to
  `selko-dark` before first paint when the browser prefers a dark color scheme.
  unverified: the screenshot spec captures both appearances but asserts nothing about the theme;
  checked by screenshot review.
- **SEL-576** Selko's sign-in, review, history and settings pages shall have no horizontal
  overflow at viewport widths from 375 to 1440 px. [verified]
- **SEL-577** Selko's peer action buttons shall never wrap their labels. [verified]

## Errors

- **SEL-580** When an error reaches a page, Selko shall show the API's message, "Unable to
  connect. Please check your internet connection." for a network failure, "The request timed
  out. Please try again." for a timeout, and "Your session has expired. Please log in again."
  for a missing session. [verified]
- **SEL-581** Selko's error alert shall have role `alert` with `aria-live`, and offer Retry only
  when the page can retry. [verified]

## Serving the web app

- **SEL-585** When a browser requests a page path (`/`, `/login`, `/register`, `/privacy`,
  `/app/...`), the API process shall answer with the built web app's `index.html` from
  `SELKO_WEB_DIR` and `Cache-Control: no-cache`. [verified]
- **SEL-586** When a browser requests a hashed asset under `/_app/immutable/`, the API process
  shall serve it with an immutable cache header. [verified]
- **SEL-587** If a requested path resolves outside the web folder, then Selko shall not serve
  the file. [verified]
- **SEL-588** Selko shall route API paths to the API, never to the web app shell. [verified]
