GOVERNS: backend/selko/services/events.py backend/selko/services/event_processing.py backend/selko/services/event_identity.py backend/selko/services/event_diff.py backend/selko/db/events.py backend/selko/db/proposals.py backend/selko/db/calendar_work.py

# Event lifecycle

How an email becomes an event, how the user reviews it, and how it reaches a calendar.
Decisions: [ADR 0010](../adr/0010-explicit-extraction-intent-and-declined-terminal.md),
[ADR 0011](../adr/0011-parallel-extraction-fenced-commit.md),
[ADR 0012](../adr/0012-one-state-owner-per-concern.md). Requirements:
[extraction](../requirements/extraction.md), [review](../requirements/review.md),
[calendar](../requirements/calendar.md).

## State owners

| Concern | Owner | Notes |
|---|---|---|
| LLM work on an email | `emails.processing_status` | A `pending` row is always claimable; `fail_email_processing` is the one fenced retry-or-terminate transition |
| Mail discovery | `email_sync_state` + `email_sync_runs` | Generation-fenced claim → heartbeat → complete/fail; at most one running run per integration |
| The user's decision | `events.review_status` | Never written by queueing calendar work |
| Update and cancellation review | `event_change_proposals` | At most one pending per event; requires `review_status='active'` |
| Provider writes | `calendar_work_items` | Action, generation, attempts, lease, error; workers are the only writers |
| Provenance | `event_sources` | Written only by the extraction commit |

Delivery status is derived from `review_status` plus the latest non-superseded work item; there is
no `events.status`. Recovery is automatic only when the next state is mechanically provable
(an expired lease is retried or failed, an older run is abandoned, an older calendar generation is
superseded); anything that would need a guess at user intent opens an incident instead.

## Extraction

- Extraction runs in parallel within and across users; only the commit
  (`selko.db.events.commit_email_extraction`) is checked, by a fingerprint of the
  `(user_id, local_day)` candidate band plus a hint fingerprint. A conflict writes nothing and the
  worker recomputes.
- Every decision states `intent` (`no_change`/`apply`/`review`/`record_only`) and, except for
  `record_only`, `fields.review_status`; the commit raises otherwise.
- Parseable `.ics` attachments are parsed directly and skip the LLM; malformed iCalendar parts are
  ignored and extraction proceeds.

## Identity: the resolution ladder

Identity is evidence, not one fingerprint (`services/event_identity.py` canonicalizes and hashes
content-free hints: UID/revision, provider thread, join URL, management URL):

1. authoritative `ical_uid` + recurrence id, from email or the calendar mirror, with SEQUENCE and
   DTSTAMP ordering revisions;
2. the same join URL and the same start and end;
3. the same provider thread with matching titles, which decides updates only, never creates;
4. any two supporting signals;
5. the LLM's local-day comparison, last.

No single weak hint (thread, join URL, management URL, title) may merge or cancel. Hint values are
hashed; logs carry only the hint kind and whether it matched.

## Review

- New events wait in the New lane; updates and cancellations to approved events wait in the Changes
  lane as proposals, except updates to an approved event Selko created, which apply automatically
  with an applied proposal kept for History and undo.
- Events adopted from the user's own calendar, and changes the model reads as cancellations, always
  wait for review; unknown provenance fails closed to review.
- Declined (`rejected`, `cancelled`) is terminal: later sources and hints are recorded, nothing is
  revived, except that a `booking_confirmed` email reopens a `rejected` event into the New lane
  (never to the calendar). `cancelled` never reopens.
- Cancellation cannot create: an unmatched or ambiguous cancellation is an audited email outcome
  (`cancellation_unmatched`/`cancellation_ambiguous`), never a New card.

## Calendar delivery

API requests never write to a provider. Approval, applying a proposal and undo enqueue
`calendar_work_items`; the calendar worker claims, writes and completes them under a lease
(`WorkItemLease`, the only completion argument). A cancellation racing an upsert wins, and a stale
completion cannot reset it. Two providers (Google, Outlook) share one code path
(`services/calendar_providers.py`); Outlook ids are stored as `outlook:<graph id>`. A mail-only
Outlook grant is not a writable calendar, and an Outlook calendar failure never marks the
integration expired, because that row also carries mail. Reconnect recovery:
[integrations](integrations.md).
