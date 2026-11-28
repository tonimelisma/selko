# Requirements: Email ingestion

How Selko discovers, acquires and stores mail from Gmail and Outlook: sync leases and runs, provider
cursors, folder eligibility, the atomic email save, attachments on disk, the email work state the
extraction worker claims, reprocessing, and the Microsoft Graph transport and failure ledger.

## Sync state, leases and runs

- **SEL-001** When an `integrations` row is inserted, or its `status` or `provider` is updated, so
  that the provider is `gmail` or `outlook` and the status is `active`, Selko shall ensure an
  `email_sync_state` row exists with `next_poll_at` set to now, resetting `consecutive_failures`
  to 0 and `last_error_code` to NULL, and leaving `next_poll_at` alone while a live lease is held.
  [verified]
- **SEL-002** Selko shall create no `email_sync_state` row for an integration whose provider is
  not `gmail` or `outlook`. [verified]
- **SEL-003** When a worker claims a due sync, Selko shall pick only an `active` integration whose
  `next_poll_at` has passed and whose lease is absent or expired, ordered by `next_poll_at` and
  then never-succeeded integrations first. [verified]
- **SEL-004** When a sync is claimed, Selko shall increment `lease_generation`, set `lease_owner`
  and a `lease_expires_at` at least one second ahead, and open an `email_sync_runs` row with status
  `running`, the same generation, and `run_kind` `initial` before the first success or
  `incremental` after it. [verified]
- **SEL-005** Selko shall keep at most one `running` row in `email_sync_runs` per integration: a
  new claim marks the previous running run `abandoned` with a `completed_at`, and a second running
  insert is refused by a unique constraint. [verified]
- **SEL-006** While concurrent workers claim syncs, Selko shall never hand the same integration to
  two workers, and an expired lease shall become claimable again. [verified]
- **SEL-007** When a worker heartbeats or completes a sync, Selko shall accept it only from the
  lease owner with the current `lease_generation` and an unexpired lease, and otherwise change
  nothing and return false. [verified]
- **SEL-008** When a sync completes, Selko shall clear the lease, set `last_success_at` and
  `last_discovery_at` to the same time, reset the failure count, schedule `next_poll_at` one poll
  interval ahead (`email_poll_interval_seconds`, default 300), and mark the run `completed`.
  [verified]
- **SEL-009** If a sync fails, then Selko shall release the lease, increment
  `consecutive_failures`, schedule the next poll after min(retry max, retry base x 2^min(failures
  - 1, 5)) seconds (defaults 60 and 1800), and mark the run `failed` with the error code cut to 100
  characters and the detail cut to 500. [verified]
- **SEL-010** If a sync fails with an authentication failure (`provider_auth_expired`: missing
  credentials, a revoked refresh token, HTTP 401, or a 403 insufficient-scope reason), then Selko
  shall set the integration's status to `expired`, which makes it unclaimable; any other failure
  shall leave it `active`. [verified]
- **SEL-011** While an integration is not due for a normal poll and was last reconciled more than
  one day ago or never, Selko shall claim it for reconciliation, never-reconciled first, as
  `weekly_reconcile` when the last reconciliation is at least seven days old and `daily_reconcile`
  otherwise, and a reconciled completion shall set `last_reconciled_at`. [verified]
- **SEL-012** When the owner calls `request_email_sync_now` for an integration, Selko shall set its
  `next_poll_at` to now unless a live lease is held, and shall return false and change nothing
  for another user, an anonymous caller, or an integration without sync state. [verified]
- **SEL-013** When a user requests a manual email sync, Selko shall fetch nothing inline, return
  zero counts, and bring forward `next_poll_at` only for that user's own active mail integrations
  that hold no live lease, failing with `NoGmailIntegrationError` when the user has no active Gmail
  integration. [verified]

## Discovery

- **SEL-020** Selko shall build the Gmail first-sync search as `after:<date 14 days ago>` with
  `-in:spam -in:trash -in:drafts -in:sent -category:promotions -category:social -category:forums`,
  quoting and escaping any excluded label name as `-label:"..."`. [verified]
- **SEL-021** When an incremental Gmail poll runs with a stored History cursor, Selko shall drain
  every `history.list` page, return each message id once, take the last `historyId` as the next
  cursor, commit it to `integrations.sync_cursor` with the page, and not fetch the user profile.
  [verified]
- **SEL-022** If Gmail History reports the stored cursor expired, then Selko shall read the
  replacement `historyId` from the profile before running the bounded listing and commit that
  replacement as the cursor. [verified]
- **SEL-023** When Selko fetches Gmail message metadata during discovery, it shall use one batched
  call for the listed ids, turn a per-message 404 into a `removed` identity, and raise on a 5xx or
  an authentication error inside the batch rather than drop the message. [verified]
- **SEL-024** If a discovered Gmail message carries SPAM, TRASH, DRAFT, SENT, CATEGORY_PROMOTIONS,
  CATEGORY_SOCIAL or CATEGORY_FORUMS, or a label whose `email_folders.is_included` is false, then
  Selko shall record it with `change_kind` `removed` instead of `upsert`. [verified]
- **SEL-025** When a Gmail reconciliation pass runs, Selko shall skip identities already in
  `email_ingestion_items` (queried in chunks of at most 200 ids) and cap the remainder at
  `email_reconcile_max_identities`, so the next pass resumes where this one stopped; incremental
  polls shall not be bounded this way. [verified]
- **SEL-026** When Selko discovers Outlook folders, it shall request immutable ids
  (`Prefer: IdType="ImmutableId"`), resolve well-known folders by alias, never return or traverse
  junk, sent, search-folder or conversation-history trees, and build nested paths as
  `Parent/Child`. [verified]
- **SEL-027** When Selko polls an Outlook folder, it shall follow `@odata.nextLink` to the
  `@odata.deltaLink`, record `@removed` entries as `removed`, and store the delta link on that
  folder's `email_folders.sync_cursor` within the same integration only. [verified]
- **SEL-028** If Graph answers 410 for an Outlook delta cursor, then Selko shall restart that
  folder from a fresh delta query, and if that also needs a resync, fail the run without ever
  persisting the resync sentinel as the folder cursor. [verified]
- **SEL-029** If Graph answers 404 for an Outlook folder during discovery, then Selko shall delete
  that `email_folders` row and continue polling the remaining folders. [verified]
- **SEL-030** If an Outlook access token expires partway through a discovery pass (Graph 401),
  then Selko shall force one token refresh and retry the call, keeping the integration `active`.
  [verified]
- **SEL-031** While discovery runs, Selko shall heartbeat the sync lease before and after each long
  provider listing and before each page write, and if a heartbeat fails it shall stop with
  `LeaseLostError` without writing the page or advancing any cursor. [verified]
- **SEL-032** When a discovery page is written, Selko shall insert new identities as `pending`
  `email_ingestion_items`, union `provider_folder_ids` for known ones, return `retry` items to
  `pending`, leave `processing`, `dead_letter` and `completed` statuses unchanged, and keep a
  completed item's `change_kind`. [verified]
- **SEL-033** If one discovery page names the same provider message id twice, then Selko shall
  reject the whole page and write nothing. [verified]
- **SEL-034** When a discovery page is written, Selko shall add its seen, inserted and existing
  counts to the run only while the run is `running`, skip empty message ids, advance a cursor only
  when the page supplies one, and emit exactly one `item_pending` wake-up per commit. [verified]
- **SEL-035** Selko shall refuse a discovery page of more than 100 identities.
  unverified: enforced in `EmailIngestionRepository.upsert_discovered`; no test sends an oversized
  page; checked by code reading.
- **SEL-036** While the integration's folders were refreshed less than
  `email_folder_refresh_seconds` (default 3600) ago, Selko shall skip re-listing Gmail labels or
  Outlook folders on a poll.
  unverified: tests only assert that a refresh stamps `folders_refreshed_at`; the skip branch is
  checked by code reading of `_discover_gmail` and `_discover_outlook`.

## Folder eligibility and preferences

- **SEL-040** When Selko upserts a discovered eligible system folder (such as Inbox), it shall store
  it as system, scannable and included with no user override, without calling the folder
  classifier, even when an older row had excluded it. [verified]
- **SEL-041** When a folder is rediscovered, Selko shall keep its row id, its `sync_cursor` and any
  user override with its `is_included` value. [verified]
- **SEL-042** When Selko classifies a user folder with the LLM, it shall send only the provider,
  folder name and full path, never message content, and store the returned decision and reason.
  [verified]
- **SEL-043** When the ingestion worker discovers a new user folder, Selko shall store it with
  decision `uncertain` and `is_included` true without calling the LLM classifier, and shall store
  provider-excluded folders (Gmail SPAM/TRASH/DRAFT/SENT/category labels, Outlook junk, deleted
  items, sent, drafts, outbox and hidden system folders) as excluded and not scannable.
  unverified: the worker passes no gateway to `upsert_discovered_folders`; no test drives a new
  user folder or an excluded system folder through it; checked by code reading.
- **SEL-044** Selko shall change `email_folders.is_included` only through
  `set_email_folder_preference`, which sets `user_override`, clears `sync_cursor`, refuses system,
  permanently excluded and other users' folders, and raises without an authenticated user.
  [verified]
- **SEL-045** When a user lists folders for `gmail` or `outlook`, Selko shall return only that
  user's non-system folders ordered by full path without `sync_cursor`, and when the user enables
  a folder it shall persist the override, clear the cursor and make the integration due now,
  answering 404 for system or foreign folders. [verified]

## Acquisition and the atomic save

- **SEL-050** When an acquisition worker claims an item, Selko shall take the oldest
  `email_ingestion_items` row that is `pending`, `retry` or `processing` with an expired lease, has
  `attempts < max_attempts` (default 8) and a due `next_retry_at`, mark it `processing`, increment
  `attempts` and lease it, never giving one row to two workers. [verified]
- **SEL-051** Selko shall take an executor slot before claiming acquisition work, keep at most
  `email_acquisition_concurrency` items in flight, and keep a full acquisition executor from
  blocking attachment claims. [verified]
- **SEL-052** If an acquisition or attachment executor runs longer than
  `email_executor_timeout_seconds` (default below `email_lease_seconds`), then Selko shall free the
  slot and fail the work as retryable with code `executor_timeout`. [verified]
- **SEL-053** Selko shall complete or remove an ingestion item only for the worker holding its
  lease, recording `email_id` and `completed_at` on completion and `removed` on removal. [verified]
- **SEL-054** When a claimed item's `change_kind` is `removed`, or the provider reports the message
  missing (404), Selko shall close the item as `removed` instead of failing it.
  unverified: the worker branch in `_process_acquisition_item` has no test; only the fenced
  database removal is tested; checked by code reading.
- **SEL-055** If acquisition fails, then Selko shall put the item in `retry` with
  next_retry_at = min(retry max, retry base x 2^min(attempts - 1, 5)), dead-lettering only when
  attempts are exhausted or the error is a `ProviderPermanentError`, store the classified code cut
  to 100 characters, and ignore a failure reported by a worker that no longer owns the lease.
  [verified]
- **SEL-056** Selko shall classify ingestion errors by type and status, never by message text, into
  stable codes (`provider_auth_expired`, `provider_rate_limited`, `provider_forbidden`,
  `provider_transient`, `provider_not_found`, `provider_permanent`, `provider_message_missing`),
  and shall replace any error detail mentioning authorization, bearer or token values
  with a generic message. [verified]
- **SEL-057** When an email is acquired, Selko shall save the email row, its attachment
  descriptors and its calendar components in one transaction through
  `save_email_with_attachment_descriptors`, without a per-message integrations lookup. [verified]
- **SEL-058** When an email is saved again, Selko shall upsert on (`user_id`, `email_provider`,
  `provider_message_id`) and update only the supplied whitelisted columns, ignoring any other key
  in the payload (including `processing_status` and `id`). [verified]
- **SEL-059** When an email is saved, Selko shall insert a `pending` attachment row for each
  descriptor with a non-empty `provider_attachment_id` (filename falling back to `name` then
  `unnamed`, MIME type to `contentType` then `application/octet-stream`, size to 0), leave rows
  that already exist untouched, and roll back the whole save on an invalid value. [verified]
- **SEL-060** When an email is saved with a non-empty calendar component list, Selko shall replace
  that email's `email_calendar_components`; an empty or missing list shall leave earlier
  components in place, and a component without a method shall fail the whole save. [verified]
- **SEL-061** When an email is saved, Selko shall store `date_sent` in UTC, converting an offset
  and treating a naive time as UTC. [verified]
- **SEL-062** When Selko parses iCalendar payloads, it shall emit one component per event with its
  method, a SHA-256 `uid_hash`, sequence, status and `THISANDFUTURE` recurrence range, and return
  no components for a malformed payload without raising. [verified]
- **SEL-063** When an Outlook message carries meeting metadata, Selko shall build a calendar
  component with method `CANCEL` for a cancellation, `REPLY` for a response and `REQUEST`
  otherwise, with a NULL `uid_hash` when the message has no `iCalUId`. [verified]
- **SEL-064** When a Gmail message is acquired, Selko shall parse calendar components from its
  inline `text/calendar` parts and from downloaded `text/calendar` or `.ics` attachments.
  unverified: no test drives `acquire_item` with calendar parts; checked by code reading.

## Message parsing and bodies

- **SEL-070** When a Gmail message has both plain and HTML parts, Selko shall store as `body_text`
  whichever says more after HTML is rendered to text, so a placeholder plain part beside a full
  HTML body yields the HTML text and a genuine plain body is kept as is. [verified]
- **SEL-071** When Selko renders HTML to text, it shall drop script and style content, unescape
  entities, separate block elements onto lines, keep http(s) link targets and omit `mailto:` and
  `cid:` targets. [verified]
- **SEL-072** When Selko parses an Outlook message, it shall store a text body verbatim, render an
  HTML body to text, never store markup, and synthesize `UNREAD`, `IMPORTANT` and `STARRED` labels
  from read state, importance and flag. [verified]
- **SEL-073** Selko shall mark an email `is_calendar_invite` when an Outlook message is an event
  message, or when a Gmail `text/calendar` part declares method REQUEST, REPLY or CANCEL in its
  header or inline body, but not for PUBLISH. [verified]
- **SEL-074** When Selko parses Gmail headers, it shall split quoted display names from addresses
  per RFC 5322 and fall back to Gmail's `internalDate` when the `Date` header is unparseable.
  [verified]

## Attachments

- **SEL-075** When an attachment worker claims work, Selko shall take the oldest due attachment
  that is `pending`, `retry` or `processing` with an expired lease and below `max_attempts`
  (default 8), and accept a finish only from the lock holder with one of `stored`, `unsupported`,
  `retry` or `dead_letter`. [verified]
- **SEL-076** While any of an email's attachments is `pending`, `processing` or `retry`, Selko
  shall not let the extraction worker claim that email. [verified]
- **SEL-077** If attachment work fails, then Selko shall leave the integration's cursors and sync
  state untouched, because attachment work is a separate claim. [verified]
- **SEL-078** Selko shall store attachment types only from one accept-set shared by the worker and
  the file store (`image/*`, `text/*`, PDF, RTF, iCalendar and the Word, Excel and PowerPoint
  types), finishing any other type as `unsupported` without retries, with code
  `attachment_type_rejected` when the store refuses it. [verified]
- **SEL-079** If storing an attachment fails for any reason other than a type refusal while
  attempts remain, then Selko shall finish it as `retry`. [verified]
- **SEL-080** When Selko acquires a Gmail attachment, it shall look up the descriptor among both
  regular and inline CID images; for Outlook it shall store only `fileAttachment` content decoded
  from base64 and finish an `itemAttachment` as `unsupported`. [verified]
- **SEL-081** When Selko stores an attachment, it shall write it under the attachments directory at
  `<user_id>/<unique id>_<ASCII-safe filename>` through a temp file and rename with mode 0600,
  leave no partial file on failure, and record `storage_path`, the SHA-256 `content_hash` and
  `size_bytes` only for the worker holding the lock. [verified]
- **SEL-082** If a storage path is empty, absolute, contains `..` or would resolve outside the
  attachments directory, then Selko shall refuse to read or write it, and a filename shall never
  steer the path out of the user's directory. [verified]
- **SEL-083** When the owner requests `GET /attachments/{id}/content`, Selko shall stream the stored
  file with its MIME type and filename, and answer 404 for another user's attachment, an
  unstored one, or a stored path outside the attachments directory. [verified]
- **SEL-084** When Selko prepares an attachment for an LLM provider, it shall discard types outside
  its ingestible set and all visual content for text-only providers, pass PDFs through only to
  Gemini and Anthropic, render PDFs to PNG pages for other vision providers, and always convert
  BMP, TIFF and HEIC to PNG. [verified]

## Email work state and reprocessing

- **SEL-085** When the extraction worker claims an email, Selko shall take the claimable email with
  the oldest `date_sent` (NULLs last) that is `pending`, below `max_attempts` (default 3), unleased
  or lease-expired and past `next_retry_at`, set it `processing`, increment `attempts` and
  `lock_generation`, and lease it for at least one second, never to two workers. [verified]
- **SEL-086** Selko shall refuse, by a CHECK constraint, a `pending` email whose `attempts` reach
  `max_attempts`. [verified]
- **SEL-087** When the extraction worker claims, Selko shall first reclaim one email whose
  `processing` lease has expired: back to `pending` (emitting `email_pending`) when attempts remain,
  otherwise `failed` with `dead_letter_reason` `lease_expired_at_limit`. [verified]
- **SEL-088** If `fail_email_processing` is called by a caller whose worker id or lock generation
  does not match the row, then Selko shall change nothing and report the call as fenced. [verified]
- **SEL-089** When extraction of an email fails, Selko shall return it to `pending` with
  next_retry_at = min(retry max, retry base x 2^min(attempts - 1, 5)) while attempts remain, and
  otherwise mark it `failed` with the code (cut to 100 characters) as `dead_letter_reason`.
  [verified]
- **SEL-090** When extraction of an email completes, Selko shall mark it `processed`, set
  `processed_at`, and clear `processing_error` and the lock in the same write. [verified]
- **SEL-091** When a user posts `/emails/{id}/reprocess`, Selko shall reset the user's email to
  `pending` with `attempts` 0 and its outcome, result, error and dead-letter fields cleared, and
  answer 409 when the email is under a live lease or is not the user's. [verified]
- **SEL-092** When a user requests `/emails/history`, Selko shall return that user's processed,
  failed and calendar-invite-skipped emails, undated first and then newest `date_sent`, with the
  total count and offset paging. [verified]

## Graph transport, runtime supervision

- **SEL-095** When Selko calls Microsoft Graph, it shall send a fresh `client-request-id` with
  `return-client-request-id: true` and any requested `Prefer` header, wait the `Retry-After`
  seconds after a 429 before retrying, and never retry a POST after a 5xx. [verified]
- **SEL-096** When a Graph call fails, Selko shall record it in `graph_api_failures` with its
  integration, run, surface, HTTP method, status and Graph error code, and a URL template that
  replaces message and folder ids with placeholders and drops delta and skip tokens. [verified]
- **SEL-097** While background processing is enabled, Selko shall run the coordinator, acquisition
  and attachment loops under a watchdog that respawns any task ending before `stop()` and keeps a
  loop alive after a failed iteration; with background processing off it shall start none of
  them. [verified]
- **SEL-098** While a claim loop finds no work, Selko shall wait a geometrically growing idle
  backoff capped at `email_worker_idle_max_seconds`, staying at the cap however long the queue is
  idle, and reset it as soon as work is found. [verified]
- **SEL-099** When a sync run ends, successfully or not, Selko shall log exactly one
  `ingestion_sync_run` line with `run_kind`, `provider`, `duration_ms`, `provider_ids_seen`,
  `items_inserted`, `items_existing` and `error_code` (the classified code on failure). [verified]
