# Reliable Email Ingestion and History

**Status:** Planned

## Goal

Make Gmail and Outlook ingestion idempotent and gap-free across long pauses, cover
Archive and custom folders without processing obvious marketing folders, and show a
small user-facing email processing history alongside the existing action history.

## Product decisions

- Include Archive and custom folders for both providers.
- Exclude provider Spam/Junk, Trash/Deleted Items, Sent, Drafts, Outbox, and Gmail's
  Promotions, Social, and Forums categories.
- On Outlook, use a one-time LLM classification when discovering a folder whose name
  strongly suggests marketing (for example, `Promotions`). Present those suggested
  exclusions in Settings for the user to review. A folder named `Newsletters` is not
  excluded by default. Folder inclusion is a persisted setting, not re-decided for
  each message.
- Never exclude a custom folder solely because of a fuzzy heuristic. The LLM must
  return a structured recommendation and short user-facing reason; uncertain folders
  remain included.
- Do not show excluded emails in History.
- Show excluded folders in Settings, where users can include or exclude folders.
- Initial synchronization covers the previous 14 days. Subsequent synchronization
  drains every change since the stored cursor, regardless of count.
- The production Render API will run on an always-on Starter instance.
- History remains a simple user-facing list with no expanded debug view, links,
  filters, raw prompts, raw responses, or newly generated LLM explanations.
- History provides a Reprocess button for an included historical email.
- History shows structured outcomes already known by the system: processed, failed,
  and the events/actions produced. If an existing LLM response already contains a
  suitable user-facing explanation, it may be displayed; no additional LLM call is
  made to create one.
- Production failed and dead-letter extraction cases become regression eval fixtures.
  The existing eval suite remains the base; this work does not redesign it.

## 1. Gmail: cursor-based, idempotent synchronization

Replace newest-50 polling with Gmail History API synchronization.

1. During first sync, list all eligible messages received in the last 14 days,
   following every page, and save them by provider message ID.
2. Persist the mailbox `historyId` only after the complete synchronization round
   succeeds.
3. On later runs, follow every history page since the stored cursor and fetch every
   added or changed message.
4. If a history cursor expires, run a paginated recovery scan with an overlap, then
   establish a new cursor.
5. Apply provider exclusions before storing or processing a message. Gmail custom
   labels and archived messages remain eligible.
6. Keep the existing unique provider-message constraint so overlapping scans and
   retries cannot create duplicate email rows or duplicate extraction work.

Required tests cover more than 50 missed messages, page draining, crash before cursor
commit, cursor expiry, overlap deduplication, Archive/custom labels, and provider
category exclusions.

## 2. Outlook: synchronize all included folders

Microsoft Graph message delta cursors are folder-specific, so replace the single
Inbox cursor with one cursor per integration and folder.

1. Discover the complete folder hierarchy, including Archive and nested custom
   folders.
2. Exclude well-known Junk Email, Deleted Items, Sent Items, Drafts, and Outbox.
3. For each remaining newly discovered custom folder, ask the configured LLM for a
   structured `include`, `exclude`, or `uncertain` marketing-folder recommendation
   based on the folder name and path only. Treat `uncertain` as included.
4. Persist the folder decision and its short explanation. Never send message content
   for folder classification and never classify the folder again unless the user asks
   or its name/path changes.
5. Show every folder and its included/excluded state in Settings. User choices override
   provider defaults and LLM recommendations.
6. First-sync each included folder for the previous 14 days, following every page.
7. Persist and drain a delta cursor independently for every included folder.
8. Request immutable message IDs where Graph supports them. Upsert by provider message
   ID and reconcile moves so moving a message between included folders does not trigger
   duplicate extraction.
9. Treat removal from a folder as a move/removal, not as proof that the message is in
   Trash. Set `is_trash` only from actual Deleted Items membership.

Required tests cover nested folders, folders populated directly by rules, Focused and
Other Inbox mail, page draining, per-folder cursor expiry, moves between folders,
Archive moves, user overrides, and LLM folder recommendations including `Promotions`
and `Newsletters`.

## 3. Scheduling

Keep the current 15-minute scheduler and scheduled-task mechanism. The production API
must run on an always-on Render instance so the scheduler is not stopped by free-tier
sleep.

The only required scheduling properties are:

- At most one pending/processing fetch per user and provider.
- Retrying a fetch is safe.
- A cursor advances only after all pages and messages in that round are durably saved.
- A later run catches everything after a long pause.

Do not add alerting, health dashboards, scan-run analytics, or a new scheduling system
as part of this work.

## 4. User-facing Settings

Add a simple folder section for each connected email provider:

- Folder name and nesting context.
- Included or excluded state.
- Provider-controlled exclusions identified as such.
- For suggested marketing-folder exclusions, the existing short recommendation reason.
- A control to include or exclude eligible custom folders.

Changing a folder from excluded to included starts a 14-day sync for that folder.
Changing it to excluded stops future ingestion; it does not add excluded mail to
History.

## 5. User-facing History

Keep the existing action history and add a simple email-processing list. Each row shows
only:

- Received time.
- Sender and subject.
- Gmail or Outlook.
- Processing state: processed or failed.
- Structured result already available from processing, such as no event, event created,
  event updated, or event cancelled.
- An existing user-suitable explanation only when the normal LLM response already
  provides one.
- A Reprocess button.

There is no expanded view, debug data, raw LLM trace, external-provider link, search,
or filtering in this scope. Excluded emails never appear.

Reprocessing resets the selected email to pending, clears its prior processing error,
and lets the normal worker claim it again. The existing event comparison/update path
must prevent duplicate event creation. While reprocessing is pending or active, disable
the button; on completion, replace the row's structured outcome with the latest result.
Add regression tests for repeated clicks, concurrent claims, an email that still
produces no event, and an email matching an already-created event.

## 6. Processing state integrity

Successful completion must always clear stale error state. Update both processing
status paths so transitions to `processing`, `processed`, or another non-failure state
set `processing_error` to null, while a failed transition records the current error.
`complete_email_processing()` must clear `processing_error` atomically with setting
`processing_status = processed` and releasing its lock.

Add regression tests that fail an email, retry it successfully, and verify that the
final row is processed with no processing error. Include a production data correction
that clears `processing_error` for rows already marked processed; this currently
affects 14 emails.

## 7. Production failure eval fixtures

Inspect every current production email with `processing_status = failed` or a
dead-letter state.

For each distinct extraction failure:

1. Identify whether the failure is a model-quality case, unsupported/oversized input,
   malformed content, provider bug, or transient infrastructure error.
2. Add a privacy-safe eval fixture when the email content exercises extraction
   behavior. Preserve the structure and detail that caused the failure while replacing
   personal identifiers, addresses, account numbers, and private links.
3. Set the expected result from the actual user-visible intent of the message, not from
   the failed production output.
4. Deduplicate failures with the same underlying content/pattern.
5. Do not turn authentication, database, network, or scheduler failures into LLM eval
   fixtures; cover those with ordinary unit/integration tests if needed.
6. Validate all added fixtures with the eval dry run and run the relevant backend unit
   tests.

## 8. Production reconciliation

After deployment:

1. Correct Outlook messages marked Trash solely because they left Inbox.
2. Clear stale `processing_error` values from successfully processed rows.
3. Retry current failed/dead-letter extraction rows after their regression fixtures and
   fixes are in place.
4. Run the 14-day Gmail and Outlook backfill.
5. Confirm repeated scans and manual reprocessing produce no duplicate emails or
   duplicate event actions.

## Definition of done

- Gmail and every included Outlook folder resume from durable cursors and drain every
  page after an arbitrarily long pause.
- Archive and custom folders are included unless excluded by provider policy, an
  accepted marketing-folder recommendation, or the user.
- Excluded folders are visible and controllable in Settings; excluded emails do not
  appear in History.
- First sync covers 14 days.
- Folder moves do not become false Trash records or duplicate extraction work.
- History presents only the narrow structured user-facing email outcomes above.
- Historical included emails can be safely reprocessed without duplicate event actions.
- Successful processing never retains an earlier `processing_error`, and existing stale
  production errors are corrected.
- Distinct production extraction failures have privacy-safe regression eval fixtures.
- The production API runs continuously on the paid Render instance.
