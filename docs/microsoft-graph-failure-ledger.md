# Microsoft Graph Failure Ledger

Durable record of Microsoft Graph and Graph-adjacent production failures seen
by Selko. Read this ledger before changing Outlook or OneDrive retry, cursor,
attachment, or authentication behavior. Add an entry whenever a new production
signature appears or Microsoft documents behavior that needs a workaround.

This file records operational facts, not email content. Never include access or
refresh tokens, authorization headers, message subjects, sender/recipient
addresses, provider message IDs, attachment contents, complete Graph payloads,
or raw HTML error pages.

## How to add an entry

Use the next `GRAPH-NNN` identifier. Include:

- first and most recent observation timestamps in UTC;
- affected Graph surface and safe environment/account label;
- HTTP status, Graph error code, request ID/client-request ID when available;
- bounded, redacted response summary;
- whether the failure is Graph, OAuth/MSAL, transport, or downstream storage;
- retry/resync behavior actually observed;
- current workaround and implementation/test status;
- links to primary Microsoft documentation and repository tests/specs.

Do not infer that every error returned during a Graph-backed operation is a
Microsoft server defect. Classify ownership explicitly.

## Required runtime capture

Polling Email Ingestion v2 must persist structured occurrences in a service-only
`graph_api_failures` table and use this document for human-curated conclusions.
The table should contain:

```text
id
occurred_at
environment
integration_id
graph_surface            # outlook_mail | onedrive
operation                # delta | list | message_get | attachment_get | token
http_method
safe_url_template        # no tenant, user, item, token, or query values
http_status
graph_error_code
request_id
client_request_id
retry_after_seconds
failure_class            # auth | throttle | cursor_reset | transport | server | client | downstream
response_summary         # redacted and length-capped
run_id
attempt
will_retry
resolved_at
```

Retention should be at least 180 days. Add indexes on `(graph_surface,
occurred_at DESC)`, `(failure_class, occurred_at DESC)`, and unresolved
failures. RLS must allow service-role access only. Store a normalized URL
template such as `/me/mailFolders/{folder-id}/messages/delta`, never a delta or
next-link token.

When Graph supplies `request-id`, `client-request-id`, `Retry-After`, or a safe
error code, retain them. Generate and send a `client-request-id` for each Graph
request and set `return-client-request-id: true` so a failure can be correlated
with Microsoft support without storing private request data.

## Entries

### GRAPH-001: Outlook delta or message request returned malformed-token 401

- **First observed:** 2026-07-29 UTC
- **Most recently observed:** 2026-07-30 UTC
- **Surface:** Outlook Mail production
- **Classification:** OAuth/MSAL or client token handling; not proven to be a
  Graph server failure
- **Signature:** HTTP 401 with `IDX14100: JWT is not well formed, there are no
  dots`.
- **Impact:** Entire Outlook folder/mailbox fetch failed. Repeated polls did not
  complete.
- **Likely meaning:** A non-JWT value reached the Graph Authorization header.
  This can result from treating an MSAL error field as an access token or from
  persisting/reading the wrong credential value.
- **Required fix:** `get_access_token` must return a token only when MSAL returns
  a non-empty `access_token` string with JWT shape. Otherwise classify the MSAL
  response, mark the integration expired only for terminal auth failures, and
  preserve sanitized MSAL error codes in the runtime ledger.
- **Regression test:** Simulate an MSAL response without `access_token` and
  prove no Graph request is issued.
- **Status:** Open; must be fixed by Polling Email Ingestion v2.

### GRAPH-002: Outlook request returned empty-detail 401

- **First observed:** 2026-07-30 UTC
- **Surface:** Outlook Mail production
- **Classification:** Authentication; ownership undetermined without Graph
  error code and request IDs
- **Signature:** HTTP 401 with no usable response detail.
- **Impact:** Outlook polling stopped and the integration/task state became
  inconsistent (`active` integration with failed fetches).
- **Required fix:** Capture Graph error code and request correlation headers;
  perform one bounded token refresh/retry; if the refreshed request is also
  401, atomically mark the integration expired, clear its lease, open an
  incident, and require reconnect.
- **Status:** Open.

### GRAPH-003: Outlook delta cursor requires resynchronization

- **Surface:** Outlook Mail
- **Classification:** Documented Graph delta behavior
- **Signature:** HTTP 410, `syncStateNotFound`, or another documented 40X
  invalid-state response.
- **Microsoft behavior:** Delta state tokens are opaque and can expire. For
  Outlook, token lifetime has no fixed upper limit and depends on Microsoft's
  internal delta-token cache. A synchronization reset can return HTTP 410 with
  a `Location` header for a fresh enumeration.
- **Required fix:** Retain the entire `@odata.deltaLink` URL unchanged. On reset,
  resynchronize only the affected folder using a bounded overlap, durably record
  every discovered immutable ID, then commit the new delta link. Do not clear
  unrelated folder cursors.
- **Sources:** [Delta query overview](https://learn.microsoft.com/en-us/graph/delta-query-overview),
  [message delta](https://learn.microsoft.com/en-us/graph/api/message-delta?view=graph-rest-1.0).
- **Status:** Partially implemented; v2 must add durable identity discovery and
  structured reset logging.

### GRAPH-004: Graph throttling requires server-directed retry

- **Surface:** Outlook Mail and OneDrive
- **Classification:** Documented Graph service protection
- **Signature:** HTTP 429, normally with `Retry-After`.
- **Microsoft behavior:** Wait for the `Retry-After` interval and retry. If no
  header is present, use exponential backoff. Requests in JSON batches are
  throttled individually.
- **Required fix:** Centralize retry behavior in `services/msgraph.py`; honor a
  bounded `Retry-After`, add jitter only when Graph did not specify the delay,
  record each occurrence, and heartbeat the Selko lease while waiting. Do not
  treat 429 as expired OAuth.
- **Source:** [Microsoft Graph throttling guidance](https://learn.microsoft.com/en-us/graph/throttling).
- **Status:** Open; the OneDrive spec proposed this but current Outlook code
  raises immediately.

### GRAPH-005: Transport connection terminated during Outlook operation

- **First observed:** July 2026
- **Surface:** Outlook Mail production
- **Classification:** Transport or upstream service; not enough correlation
  data to assign ownership
- **Signature:** HTTP/2-style `ConnectionTerminated` errors and transient read
  failures.
- **Impact:** Entire fetch runs failed and repeated work from the old cursor.
- **Required fix:** Use bounded connect/read/overall timeouts and retry safe GETs
  with exponential backoff. Preserve the durable discovery cursor until a page
  is recorded. Log correlation IDs when a Graph response exists; otherwise log
  only the normalized transport class.
- **Status:** Open.

### GRAPH-006: OneDrive delta token reset

- **Surface:** OneDrive `/me/drive/root/delta`
- **Classification:** Documented Graph behavior; not yet observed in Selko
  production because photo ingestion is parked
- **Microsoft behavior:** An invalid/expired token or changed server state can
  return HTTP 410 with a `Location` header containing a fresh enumeration URL.
  The client must enumerate to a new `@odata.deltaLink` and compare server state
  with local state. `token=latest` intentionally skips existing history and is
  inappropriate for a completeness repair.
- **Required fix before OneDrive restoration:** Follow the supplied restart URL,
  persist intermediate next-link progress durably, enumerate to completion,
  reconcile IDs, then commit the new delta link.
- **Source:** [driveItem delta](https://learn.microsoft.com/en-us/graph/api/driveitem-delta?view=graph-rest-1.0).
- **Status:** Planned in `docs/specs/onedrive-photo-ingestion.md`; not implemented.

### GRAPH-007: Unsupported attachment MIME failed Outlook mailbox sync

- **First observed:** July 2026
- **Most recently observed:** 2026-07-30 UTC
- **Surface:** Outlook Mail operation, Supabase Storage write
- **Classification:** Selko/downstream storage bug, not a Graph API failure
- **Signature:** Storage HTTP 415 for `video/mp4` and
  `application/vnd.google-apps.document`.
- **Impact:** Because attachment upload was inside Outlook folder processing,
  one unsupported attachment failed the entire folder run and prevented cursor
  advancement. The same poison item was retried repeatedly.
- **Required fix:** Persist message identity/body first. Model attachments as
  independent work. Mark unsupported MIME types terminal `unsupported`; never
  fail provider discovery or later messages. Record Graph attachment metadata
  separately from downstream storage failure ownership.
- **Status:** Open; mandatory v2 acceptance blocker.

## Research conclusions for Selko

- Outlook message delta is explicitly folder-scoped. Keep one complete delta
  link per included folder.
- Follow `@odata.nextLink` and `@odata.deltaLink` URLs verbatim; their opaque
  tokens already contain initial query parameters.
- A response page can be empty and still have a next link. Completion is the
  presence of a delta link, not a non-empty page.
- The same item can appear more than once or in an unexpected page order. Merge
  by immutable identity.
- `Prefer: IdType="ImmutableId"` is request-scoped and must be sent on every
  request that returns Outlook item IDs. Immutable IDs remain stable across
  folder moves inside one mailbox, but are case-sensitive.
- Outlook delta links work with either ID format, so existing state can migrate
  to immutable IDs without discarding the cursor.
- OneDrive and Outlook both use opaque delta tokens and can require a fresh
  enumeration, but their data and recovery semantics must remain separate.

Primary sources:

- [Outlook message delta](https://learn.microsoft.com/en-us/graph/api/message-delta?view=graph-rest-1.0)
- [Outlook immutable IDs](https://learn.microsoft.com/en-us/graph/outlook-immutable-id)
- [Microsoft Graph delta overview](https://learn.microsoft.com/en-us/graph/delta-query-overview)
- [Microsoft Graph throttling](https://learn.microsoft.com/en-us/graph/throttling)
- [OneDrive driveItem delta](https://learn.microsoft.com/en-us/graph/api/driveitem-delta?view=graph-rest-1.0)
- [Get attachment](https://learn.microsoft.com/en-us/graph/api/attachment-get?view=graph-rest-1.0)

