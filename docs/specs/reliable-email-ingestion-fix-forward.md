# Reliable Email Ingestion Fix-Forward

**Status:** Implemented in fix-forward PR

## Context

PR #183 implemented the first version of reliable Gmail/Outlook ingestion, folder
classification and settings, email History, reprocessing, and processing-state cleanup.
It is merged but not production-ready. This plan starts from that merged code and
defines the shortest complete path to a green, deployable implementation.

Do not redesign the feature or add monitoring, operational dashboards, filters, debug
views, external email links, or new LLM-generated explanations.

## Product contract

- Initial sync covers 14 days.
- Gmail and Outlook then resume idempotently from durable cursors and drain every page.
- Archive and user-created folders/labels are included by default.
- Every newly discovered or renamed user folder/label receives the shared, one-time,
  open-ended LLM marketing-folder classification. Only clearly marketing-oriented
  folders are excluded; uncertain and all other folders are included.
- Permanently irrelevant provider locations are never configurable or scanned: Spam or
  Junk, Trash or Deleted Items, Sent, Drafts, and Outbox. Gmail Promotions, Social, and
  Forums are also permanently excluded.
- Excluded messages are outside ingestion. Outlook never requests messages or deltas
  from excluded folders. Gmail excludes them from the initial search and filters History
  results using label metadata before fetching full content. They create no email row,
  attachment, extraction call, rejection record, or History row.
- Settings shows only eligible user-created folders and labels, including those excluded
  by the LLM. The user can override the LLM, but cannot see or enable permanent system
  exclusions.
- History remains a narrow user-facing surface: received time, sender, subject, provider,
  structured processing outcome, and a Reprocess button. No expanded view or filters.
- Reprocessing is idempotent and visibly resolves to the latest processed or failed state.
- Successful processing never retains a stale `processing_error`.
- Eval inputs remain source-faithful and never contain evaluator-authored answer cues.

## 1. Correct Outlook system-folder identification

Microsoft Graph v1.0 does not return `wellKnownName` on listed `mailFolder` objects.
Remove the assumption in `normalize_mail_folders()` that it does.

1. Resolve every permanently excluded well-known folder through its Graph alias and
   collect its immutable folder ID:
   - `junkemail`
   - `deleteditems`
   - `sentitems`
   - `drafts`
   - `outbox`
2. Use those resolved IDs when normalizing the discovered hierarchy.
3. Do not pass permanent folders to the LLM classifier.
4. Do not persist them as user-configurable rows. If retaining internal rows is useful
   for reconciliation, they must be service-only, permanently excluded, and absent from
   every user query.
5. Do not recursively scan irrelevant hidden/system trees such as search folders,
   synchronization issues, server failures, or recoverable/deletion trees. Resolve and
   exclude all applicable well-known roots before requesting child folders.
6. Create delta and message requests only for included eligible folders.
7. Clean up any PR #183 rows that incorrectly persisted a permanent or hidden system
   folder as configurable.

Tests must use realistic Graph v1.0 folder payloads without a `wellKnownName` property.
Prove that localized display names do not affect exclusion and that no listing, delta,
subscription, LLM call, Settings row, or email ingestion occurs for forbidden folders.

## 2. Close the Gmail expired-cursor race

The normal initial sync captures a mailbox `historyId` before its 14-day backfill. Make
expired-cursor recovery follow the same ordering.

1. When Gmail reports an expired History cursor, obtain the replacement mailbox
   `historyId` before starting the recovery search.
2. Run the paginated overlap/backfill search.
3. Check label metadata before fetching full content.
4. Save every eligible message and attachment.
5. Persist the pre-backfill replacement cursor only after the complete recovery succeeds.
6. If any page, content fetch, upsert, or eligible attachment operation fails, leave the
   previous cursor unchanged so the next run repeats recovery safely.

Add a regression test that injects a message during recovery after its search position
has passed. The message must be returned by the next History run. Also cover repeated
recovery, duplicate overlap, page draining, and failure before cursor commit.

## 3. Enforce system-folder immutability in the database

The current `email_folders` UPDATE policy allows an authenticated client to change a
system row to `is_system = false` and enable it. API validation is insufficient because
frontends have direct Supabase access.

1. Remove broad authenticated UPDATE access to `email_folders`.
2. Add a narrowly scoped `SECURITY DEFINER` function for a user to change only the
   inclusion preference on a row that is already:
   - owned by `auth.uid()`;
   - `is_system = false`;
   - an eligible Gmail or Outlook user folder/label.
3. The function may set only `is_included`, `user_override`, `sync_cursor`, and
   `updated_at`. It must not accept or mutate ownership, provider identity, folder IDs,
   system state, classification, or folder metadata.
4. Revoke direct authenticated mutation privileges that bypass the function.
5. Have the backend preference endpoint invoke this function using the authenticated
   user session.

Add database tests proving users cannot mutate another user's row, cannot turn a system
row into a user row, cannot enable a forbidden folder, and can update an eligible folder.

## 4. Make reprocessing visibly complete

The current History UI changes a row to `pending` and then leaves it spinning forever.

1. After a successful Reprocess request, keep the row visible.
2. Poll that email's narrow processing state until it becomes `processed` or `failed`.
   Use a modest bounded interval and stop on navigation/unmount.
3. Replace the row with its latest structured outcome when processing completes.
4. Re-enable Reprocess after completion.
5. Surface a user-facing error and stop polling on terminal API failure or timeout.
6. Prevent repeated clicks while the email is pending or processing.
7. Ensure concurrent requests still create only one processing attempt.

Do not add a general monitoring framework or realtime dependency for this. A small,
component-owned status refresh is sufficient.

## 5. Complete email History pagination

History currently displays only the newest 20 emails and a count.

1. Add a simple Load More action matching the existing action-history behavior.
2. Append the next page without duplicates.
3. Preserve the narrow row design and add no search or filters.
4. Keep failed and processed emails visible; pending/processing rows are retained only
   when the user initiated reprocessing from the current page.

## 6. Represent extracted no-change events honestly

An email can contain an event that matches an existing event without creating or
updating anything. This is not `no_event`.

1. Add a structured outcome such as `event_matched` for extraction that found one or
   more events but produced no material changes.
2. Reserve `no_event` for extraction that returned no events.
3. Update the database constraint, backend outcome selection, API/frontend types,
   translation, and History label.
4. Keep outcomes derived from existing structured processing data. Do not add another
   LLM call or synthesize an explanation.

Cover no-event, created, updated, created-and-updated, cancelled, matched/no-change,
failed, and reprocessed transitions.

## 7. Repair frontend CI and test isolation

PR #183's frontend unit job fails before collecting History tests because the new
`email-history.js` imports the real Supabase singleton without test environment values.

1. Mock the email-history service or Supabase dependency in the History page tests
   before importing the component.
2. Add focused History tests for:
   - email rows and every outcome;
   - failed rows;
   - Reprocess pending state;
   - eventual processed and failed completion;
   - polling timeout/error cleanup;
   - repeated-click prevention;
   - email Load More pagination.
3. Add Settings tests for Gmail and Outlook included/excluded user folders, user
   overrides, classifier reasons, and permanent-system-folder absence.
4. Make tests independent of a developer's local `.env` so the same command behaves
   identically locally and in GitHub Actions.

## 8. Add the missing ingestion regression coverage

The existing six backend tests cover helpers but not the end-to-end invariants. Add
tests at the worker/service boundary for:

### Gmail

- Initial 14-day search and every result page.
- More than 50 eligible messages.
- Incremental History pagination.
- Metadata rejection before full-content fetch.
- No row, attachment, or extraction for excluded labels.
- Cursor commit only after the entire successful round.
- Crash/failure before cursor commit.
- Expired-cursor recovery race and overlap deduplication.
- New and renamed label classification, uncertain default, and durable user override.

### Outlook

- Real Graph v1.0 folder discovery with separately resolved well-known IDs.
- Localized system-folder display names.
- Nested custom folders and rule-routed messages.
- No requests for forbidden or user-excluded folders.
- One independent cursor per included folder.
- More than one delta page.
- Cursor expiry and 14-day recovery.
- Moves between included folders without duplicate extraction.
- Moves to Archive without false Trash state.
- Moves to excluded/deleted folders without scanning those folders.
- Immutable message IDs and idempotent attachment storage.
- New and renamed folder classification, uncertain default, and durable user override.

### Shared processing state

- Fail then succeed clears `processing_error`.
- Reprocess is atomic and rejects concurrent pending/processing requests.
- Reprocessing an existing event creates no duplicate event/action/source.
- Folder classifier failure includes by default without exposing message content.

## 9. Reconcile merged PR #183 state

Before staging verification:

1. Remove incorrectly discovered Outlook system-folder rows.
2. Ensure no forbidden folder cursor survives.
3. Clear stale `processing_error` only for successfully processed rows.
4. Preserve legitimate user overrides on eligible folders.
5. Preserve already-ingested eligible email history.
6. Do not ingest or create rejection records for messages in newly corrected excluded
   folders.

Use an idempotent migration or reconciliation function so rerunning deployment is safe.

## 10. Verification and delivery

This is a source-code change and must use the repository worktree, feature branch, PR,
and merge-cleanup workflow.

Required local gates:

1. Backend unit tests:
   `uv run pytest backend/tests/ -m "not integration"`
2. Frontend unit tests using the same coverage command as CI:
   `npm run test:coverage`
3. Frontend unit-test command required by the repository.
4. `npm run check`
5. `npm run build`
6. Apply migrations to local Supabase and confirm a clean schema diff.
7. `./scripts/capture-all-screenshots.sh web`, then review History and Settings desktop
   and mobile output.

After merging, inspect post-merge CI. Fix forward any attributable failure, including
staging migration or integration failures. Do not deploy production until all local
gates pass, post-merge staging deployment/integration checks have completed successfully,
and the user explicitly approves production deployment.

## Definition of green

- Outlook resolves and excludes permanent system folders by ID using Graph v1.0 and
  never scans or exposes them.
- Authenticated clients cannot bypass system-folder exclusions through Supabase.
- Gmail initial, incremental, and expired-cursor recovery scans cannot skip mail and
  commit cursors only after complete success.
- Excluded messages remain entirely outside ingestion.
- Reprocess visibly reaches a final state and remains idempotent.
- Email History can page beyond 20 rows.
- Extracted unchanged events are not mislabeled as no-event.
- All required ingestion, Settings, History, and state-transition regressions exist.
- Backend tests, frontend coverage/unit tests, checks, build, migrations, and screenshots
  pass locally.
- GitHub Actions is green after merge, including staging deployment and integration
  tests.
- No production deployment has occurred without explicit approval.
