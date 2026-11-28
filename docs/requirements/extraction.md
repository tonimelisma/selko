# Requirements: Event extraction

How Selko turns one claimed email into extraction decisions: the LLM gateway and its quotas and
logs, .ics parsing, civil time, identity hints, the resolution ladder, sender rules, and the
lease- and band-fenced commit `selko.db.events.commit_email_extraction`.

## LLM provider and gateway

- **SEL-100** Selko shall run production extraction on `LLM_PROVIDER=anthropic` with
  `LLM_MODEL=claude-haiku-5-5` and `LLM_FALLBACK_PROVIDER=none`, so email content reaches no
  provider other than Anthropic.
  unverified: deployment configuration, not code; checked against `.env.example` and the production
  environment when the privacy policy or provider settings change.
- **SEL-101** When `LLM_FALLBACK_PROVIDER` is `none` (any letter case), Selko shall configure no
  fallback provider or model, even when `LLM_FALLBACK_MODEL` and another provider's API key are set,
  and the gateway shall have only the `primary` route. [verified]
- **SEL-102** If `LLM_FALLBACK_PROVIDER` is unset, then Selko shall fill the fallback provider and
  model from the provisional pairing table for the primary provider (always a different provider),
  keeping any explicitly configured value. [verified]
- **SEL-103** When Selko calls `claude-haiku-5-5`, it shall send adaptive thinking with the
  configured effort and `max_tokens` 16000, with the Anthropic SDK's own retries set to 0 so that
  retries are owned by the gateway. [verified]
- **SEL-104** When a structured LLM call fails transiently (rate limit, 5xx, connection error),
  Selko shall retry the primary route up to `llm_primary_max_attempts` (default 3) times and then
  try a configured fallback up to `llm_fallback_max_attempts` (default 2) times. [verified]
- **SEL-105** If a response is empty, invalid JSON, schema-invalid or truncated, then Selko shall
  stop retrying that route and go straight to the fallback route when one is configured, logging
  the HTTP-success response as a failed attempt. [verified]
- **SEL-106** If the provider returns a permanent error (such as an invalid API key), then Selko
  shall raise `LLMAPIError` after one attempt without retrying or falling back. [verified]
- **SEL-107** If the provider refuses the request (`finish_reason` `refusal`), then Selko shall
  classify it as `REFUSAL` with the provider's refusal category, never retry it on the same model,
  and use a configured fallback route. [verified]
- **SEL-108** When a call's contents include images or PDFs and the primary model is text-only
  while the fallback is vision-capable, Selko shall send the call only to the fallback route.
  [verified]

## Per-user daily LLM quota

- **SEL-110** When the gateway makes a call for a user, Selko shall first check-and-increment that
  user's `llm_calls` quota and raise `QuotaExceededError` (quota type `llm_calls`, current count,
  limit) when the quota is spent. [verified]
- **SEL-111** Selko shall count quotas per user per UTC date in `usage_quotas`, creating the day's
  row from the `global_limits` defaults (`llm_calls_daily` 100, `email_syncs_daily` 50,
  `calendar_syncs_daily` 100), and a refused increment shall change no count. [verified]
- **SEL-112** If an administrator sets a user's limit above the `global_limits.max_allowed` value
  (1000 for `llm_calls_daily`), then Selko shall refuse it with `ValueError`; otherwise the new
  limit applies to that user's later checks. [verified]
- **SEL-113** If the quota check itself fails (database error), then Selko shall allow the call
  and log `QUOTA_SERVICE_ERROR` at ERROR level. [verified]
- **SEL-114** If a user's LLM quota is exceeded while an email is being processed, then Selko
  shall re-raise `QuotaExceededError` without marking the email `failed`.
  unverified: no test drives `process_email_for_events` into a quota refusal; checked by reading
  the `except QuotaExceededError: raise` branch in `services/events.py`.

## LLM call logging

- **SEL-116** When the gateway makes a provider attempt for a user, Selko shall write one
  `llm_call_log` row with the user, operation type, model, provider, email id, full prompt text,
  full response text (NULL on failure), token counts, latency, success flag, error type and an
  estimated cost. [verified]
- **SEL-117** When a prompt contains attachments, Selko shall log the prompt text with the
  attachment bytes replaced by a `[N attachment(s) included]` marker. [verified]
- **SEL-118** If writing an `llm_call_log` row fails, then Selko shall log the error and return no
  log id without failing the LLM call. [verified]
- **SEL-119** Selko shall read `llm_call_log` rows only scoped to their `user_id`, and no client
  API route shall read the LLM log. [verified]

## Extraction input

- **SEL-121** When Selko extracts events from an email, it shall send the fixed instructions as
  system text, then the attachments, then an `<email_context>` block (today's date in the user's
  timezone, the timezone, subject, sender, date sent) followed by `<email_body>` as the last part.
  [verified]
- **SEL-122** When an attachment is `text/plain`, `text/csv`, `text/markdown` or
  `text/tab-separated-values`, Selko shall send it as text wrapped in `<attachment filename=…>`,
  truncated to 40,000 characters with an `[attachment truncated]` marker, and shall never send a
  `text/calendar`/`.ics` attachment to the model. [verified]
- **SEL-123** If an image attachment is larger than `max_image_size_for_llm` (default 10 MB), then
  Selko shall skip it, while PDFs bypass the byte limit here and reach Anthropic as `document`
  blocks. [verified]
- **SEL-124** When a claimed email has stored attachments, Selko shall pass their stored bytes,
  MIME type and filename to the extraction. [verified]
- **SEL-125** When the model reports `booking_confirmed` (tickets bought, registration done, RSVP
  accepted), Selko shall carry that flag from the LLM response into the extraction result.
  [verified]

## Calendar files and invitations

- **SEL-127** When an email has a parseable `.ics` attachment (MIME `text/calendar` or `.ics`
  filename) with at least one VEVENT that has a SUMMARY and DTSTART, Selko shall build the events
  from it and skip the LLM extraction call. [verified]
- **SEL-128** If no `.ics` attachment parses into events, then Selko shall fall back to LLM
  extraction. [verified]
- **SEL-129** When a VEVENT has a DATE-only DTSTART, Selko shall mark it all-day, and when a timed
  VEVENT has no DTEND, Selko shall end it one hour after its start. [verified]
- **SEL-130** When an email is a calendar invitation (`is_calendar_invite`, or an `.ics` METHOD of
  REQUEST, REPLY, CANCEL, COUNTER or DECLINECOUNTER, a later attachment's invite METHOD winning over
  an earlier PUBLISH), Selko shall skip it with outcome `calendar_invite` and no LLM call only when
  one of its UIDs already has an `ical_uid` hint on a mirrored calendar entry, and otherwise process
  it. [verified]

## Civil time

- **SEL-132** When Selko stores an LLM-extracted datetime, it shall treat the clock face as local
  wall time in the user's timezone, discarding any offset the model emitted. [verified]
- **SEL-133** When Selko stores a datetime from a trusted source with `treat_as_civil=False`, it
  shall keep the absolute instant of an aware value. [verified]
- **SEL-134** If the user has no `user_calendar_settings` timezone, an empty or invalid one, or the
  read fails, then Selko shall use `America/New_York`. [verified]
- **SEL-135** When a timed event has no end, or an end at or before its start, Selko shall give it
  a one-hour duration, including for a proposed change's new start and end. [verified]
- **SEL-136** When an extracted event starts more than 24 hours before now (in the user's
  timezone), or has no start, Selko shall drop it without resolution or a decision, outside
  cancellation handling. [verified]
- **SEL-137** When Selko asks the LLM whether events match, it shall render every candidate's
  times as local wall-clock times in the user's timezone. [verified]

## Identity hints

- **SEL-139** When Selko derives an `ical_uid` hint, it shall store only the SHA-256 of the
  whitespace-collapsed, case-folded UID plus the recurrence id, with strength `authoritative`.
  [verified]
- **SEL-140** Selko shall namespace `provider_thread` hints by provider, normalize `join_url` hints
  by dropping tracking parameters (`utm_*`, `fbclid`, `gclid` and similar) and fragments, keep the
  full query of `management_url` hints (paths with manage/cancel/edit/portal/registration), and mark
  all three `supporting`. [verified]
- **SEL-141** When an ordinary email (no invite) is extracted, Selko shall derive a
  `provider_thread` hint from its provider and thread id. [verified]
- **SEL-142** When Selko reads a Google Calendar event, it shall derive an authoritative
  `ical_uid` hint from `iCalUID` with the occurrence's `originalStartTime` as recurrence id, plus a
  `join_url` hint from `hangoutLink` or a video conference entry point. [verified]
- **SEL-143** When a decision is committed, Selko shall upsert its hints in the same transaction,
  one row per (event, kind, value_hash, recurrence_id), moving an `ical_uid` hint's sequence and
  dtstamp only forward, and shall refuse a hint with an unknown kind or strength or an empty hash.
  [verified]
- **SEL-144** Selko shall require every `event_identity_hints` row to name exactly one entity: an
  event or a mirrored calendar entry. [verified]

## Resolution ladder

- **SEL-147** When Selko resolves an extracted event, it shall use as candidates the user's events
  and live (not deleted) mirrored calendar entries starting in the user's local day of the event's
  start, `[00:00, 00:00 next day)` converted to UTC, and never another user's rows. [verified]
- **SEL-148** When an incoming `ical_uid` hint names exactly one stored event, Selko shall match
  that event without an LLM call, and if the incoming SEQUENCE is lower (or equal with a DTSTAMP not
  newer) shall treat it as a stale, audited no-op. [verified]
- **SEL-149** If two events share only a `join_url` hint and their start or end times differ, then
  Selko shall not match them. [verified]
- **SEL-150** When an incoming `join_url` hint names an event with the identical start and end,
  Selko shall match that event without an LLM call.
  unverified: only the negative case is tested; checked by reading `_identity_match`.
- **SEL-151** When exactly one event shares the incoming `provider_thread` hint and the titles are
  equal or one is a prefix of the other after case-folding and trimming punctuation, Selko shall
  match it even on another date, and shall not match when the thread names several events, the
  titles differ or a title is empty. [verified]
- **SEL-152** When exactly one stored event shares two or more distinct supporting hint kinds with
  the incoming event, Selko shall ask the LLM comparison about that event alone, passing only the
  signal labels.
  unverified: no test covers `_strong_identity_candidates`; checked by reading `find_matching_event`.
- **SEL-153** When an incoming authoritative hint equals a live calendar event's `iCalUID` and
  recurrence id, Selko shall treat it as the same event, while a shared join URL alone shall never
  prove identity. [verified]
- **SEL-154** When Selko reads the user's live calendar for candidates, it shall skip provider
  events carrying a private `selko_event_id` property. [verified]
- **SEL-155** When the local-day LLM comparison runs, Selko shall offer one candidate per real
  event (a Selko row instead of its own mirror entry, one copy per provider id with the live copy
  preferred), and an LLM failure or an unknown returned id shall mean no match. [verified]
- **SEL-156** When the comparison matches a provider event that a Selko row already holds (whatever
  its review status), Selko shall resolve to that row, the oldest one first. [verified]
- **SEL-157** When the comparison matches a mirrored entry that the live read of the write calendar
  does not contain, Selko shall record it as on another calendar and create nothing. [verified]
- **SEL-158** When a calendar mirror sync writes an entry (not Selko-created, not deleted or
  cancelled) whose start equals a `pending_review` event's start and the LLM comparison matches
  them, Selko shall set that event to `rejected` only if it is still `pending_review`, and relabel
  its email `event_matched` when that was the email's only event. [verified]

## Change sets

- **SEL-160** When a matched event yields a `noop` change set, Selko shall write no decision for
  it. [verified]
- **SEL-161** When a proposed change only restates the same instant or makes a cosmetic title
  edit, Selko shall drop it from the change set. [verified]
- **SEL-162** If the email is older than the newest email already behind the event, then Selko
  shall drop its material field changes. [verified]
- **SEL-163** If an update would leave a timed event longer than 24 hours while the email itself
  describes a timed event of at most 24 hours, then Selko shall end the event at the new start plus
  the email's own duration and record that end change in the change set. [verified]

## Fenced commit

- **SEL-165** If the committing worker's `locked_by` and `lock_generation` no longer match the
  email, then Selko shall write nothing and return `{"fenced": true, "applied": 0}`. [verified]
- **SEL-166** If a decision's band fingerprint (events in `[window_start, window_end)`) or hint
  fingerprint (events and calendar entries its hint keys name) differs from the one computed when
  the decision was made, then Selko shall write nothing, leave the email `processing`, and return
  a conflict naming that decision's index. [verified]
- **SEL-167** Selko shall compute the producer's and the commit's fingerprints with the same
  function over the same rows, so an unchanged band always commits. [verified]
- **SEL-168** When a commit conflicts, Selko shall recompute the email's decisions and retry, and
  after 3 attempts shall raise `ResolutionConflictExhausted`. [verified]
- **SEL-169** When an email's decisions commit, Selko shall write all of them or none, set the
  email's terminal status and release its lease in the same transaction. [verified]
- **SEL-170** When two emails about the same local day commit concurrently, Selko shall create
  only one event and return a conflict to the other. [verified]

## Decision intent

- **SEL-172** If a decision has no intent or one outside `no_change`, `apply`, `review`,
  `record_only`, then the commit shall raise `InvalidArgument` and write nothing. [verified]
- **SEL-173** If a decision other than `record_only` has no `fields.review_status`, or one outside
  `pending_review`, `active`, `rejected`, `cancelled`, or a `calendar_action` other than `upsert` or
  `cancel`, then the commit shall raise `InvalidArgument` rather than default it. [verified]
- **SEL-174** If a `no_change` decision carries a change set, or an `apply` or `review` decision
  lacks a non-empty change set and snapshot, then the commit shall raise `InvalidArgument`.
  [verified]
- **SEL-175** When an `apply` or `no_change` decision is committed, Selko shall write only the
  fields present in `fields` (a JSON null clears the column), and shall queue calendar work only
  when its `review_status` is `active`. [verified]
- **SEL-176** When an `apply` decision with `calendar_action` `cancel` and review status `active`
  is committed, Selko shall record an applied `cancellation` proposal and queue a `cancel` work
  item with no desired payload. [verified]
- **SEL-177** If a `record_only` decision is not an update, or any update names an event the
  email's user does not own, then the commit shall refuse it. [verified]
- **SEL-178** When a decision is committed for an email that already has a source on that event,
  Selko shall update that `event_sources` row in place, and shall add `google_calendar` sources for
  calendar-adopted events. [verified]
- **SEL-179** When a created event omits importance or all_day, Selko shall store `action_required`
  and not all-day, and shall store naive timestamps as UTC. [verified]
- **SEL-180** When an extracted event matches nothing, Selko shall create it with intent
  `no_change` and review status `pending_review` (or `active` under an auto-approve rule). [verified]
- **SEL-181** Selko shall state a literal intent in every decision that `save_extracted_events`
  builds, and a literal `review_status` in every decision except `record_only`. [verified]

## Sender rules and processing flow

- **SEL-183** When Selko looks up a sender rule, it shall use the user's rule for the exact address
  first, then the rule for the address's domain, never another user's rule. [verified]
- **SEL-184** While the sender has an `ignore` rule, Selko shall mark the email `skipped` without
  calling the LLM or creating events. [verified]
- **SEL-185** While the sender has an `auto_approve` rule, Selko shall create new events as
  `active` and queue their calendar upsert. [verified]
- **SEL-186** When the user ignores a sender, Selko shall, in one transaction, record an `ignore`
  rule for the address (or the domain when no address is given, matched as a case-sensitive
  `@domain` suffix), reject that sender's `pending_review` events, and reject their pending
  proposals with reason `repair_operator` restoring the snapshot, touching no other user's rows.
  [verified]
- **SEL-187** When an `ignore` rule is deleted and no equivalent ignore rule remains, Selko shall
  requeue the sender's mail skipped in the last 30 days, and deleting an `auto_approve` rule shall
  requeue nothing. [verified]
- **SEL-188** When processing finishes, Selko shall mark the email `processed` with outcome
  `event_created` (new events), `event_matched` (an event matched with no change) or `no_event`
  (nothing extracted), store the `processing_result` counts, and release the lease. [verified]
- **SEL-189** If processing raises, then Selko shall mark the email `failed` with the error text and
  raise `EventsError`. [verified]
- **SEL-190** When an email is an organizer cancellation (an `.ics` or stored component METHOD
  CANCEL, or the model's `cancellation_detected`), Selko shall match only by strict identity, queue
  a calendar cancel for a matched active Selko event, and record `cancellation_unmatched` or
  `cancellation_ambiguous` when there is no single owned match.
  unverified: only the declined-event case is tested; checked by reading the `cancellation_mode`
  branch of `save_extracted_events`.
