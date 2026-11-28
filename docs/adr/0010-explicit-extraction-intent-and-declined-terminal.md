# 0010. Explicit extraction intent; declined events are terminal

- Status: accepted
- Date: 2026-11-28

## Context and problem

Extraction once derived auto-apply from `review_status='active'`, the same value a pending
proposal requires, so an unstated decision silently wrote to the user's calendar. Separately,
emails about an event the user had declined kept reviving it. A ticket receipt for an event the
user had rejected was then swallowed. Requirements: [SEL-172..181](../requirements/extraction.md),
[SEL-222..234](../requirements/review.md).

## Decision drivers

- A stalled extraction is recoverable; a silent calendar write is not.
- The user's decline is respected, except when the user's own later action reverses it.

## Considered options

### Every decision states its intent; commit raises otherwise; declined is terminal with one booking exception (chosen)

- Good: fail closed; no implicit writes.
- Bad: every producer must be explicit.
- Failure modes: an unstated decision stops the email (retry), visible in health.

### Infer intent from review status

- Good: less code.
- Bad: the silent-write bug.
- Failure modes: calendar writes nobody approved.

## Decision

Every extraction decision states an explicit `intent` (`no_change`/`apply`/`review`/`record_only`)
and, except for `record_only`, an explicit `fields.review_status`; `commit_email_extraction` raises
rather than defaulting either. Delivery follows `review_status`, never `intent`. Updates to an
approved event Selko created apply automatically (`intent="apply"`, calendar upsert, an applied
proposal kept for History and undo); an event adopted from the user's own calendar
(`source_origin='google_calendar'`), or a change the model reads as a cancellation, waits in the
Changes lane; unknown provenance fails closed to review. A declined event (`rejected` or
`cancelled`) is terminal: later emails still record provenance and identity hints, which keeps the
match working and prevents a duplicate in the New lane, but never revive it. One exception: an email
the extractor flags `booking_confirmed` (ticket receipt, completed registration, accepted RSVP)
reopens a `rejected` event into the New lane, never to the calendar; `cancelled` (the organizer's
word) stays terminal. Queueing calendar work never promotes review status and refuses an upsert for
a declined event.

## Consequences

Design detail: `docs/design/event-lifecycle.md`.

## Confirmation

`backend/tests/test_extraction_decision_intent.py`,
`backend/tests/integration/test_integration_extraction_intent.py` (SEL-172..181),
`backend/tests/test_declined_event_terminality.py` (SEL-230..234),
`backend/tests/test_selko_managed_updates.py` (SEL-222..225).

## Retirement proof

A product decision to let some sources revive declined events.

## Reversal plan

Relax the terminal check in `services/events.py`; the hints are already recorded.
