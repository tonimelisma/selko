# 0012. One state owner per concern; workers are the only provider writers

- Status: accepted
- Date: 2026-11-28

## Context and problem

A production repair once found an orphaned Changes card, unclaimable pending emails and a stale
running audit row while health still reported ok: several places wrote the same state. Requirements:
[SEL-085..092](../requirements/ingestion.md), [SEL-300..336](../requirements/calendar.md),
[SEL-212..220](../requirements/review.md).

## Decision drivers

- Each fact has one writer.
- Recovery is deterministic: automatic only when the next state is provable.
- API requests never wait on a provider write.

## Considered options

### Explicit owners and fenced work items (chosen)

- Good: invariants live in the schema (partial unique indexes, CHECKs, a pre-commit check).
- Bad: more tables.
- Failure modes: an owner bypassed by raw SQL; guarded by tests.

### Status columns written wherever convenient

- Good: less code.
- Bad: contradictory state.
- Failure modes: stuck work health cannot see.

## Decision

`emails.processing_status` owns LLM work; `email_sync_state`/`email_sync_runs` own discovery
(generation-fenced, at most one running run per integration); `events.review_status` owns only the
user's decision; `event_change_proposals` owns update and cancellation review (at most one pending
per event); `calendar_work_items` owns every provider write (action, generation, attempts, lease,
error); `event_sources` holds provenance only. `events.status` does not exist: delivery is derived
from the latest non-superseded work item. API requests enqueue fenced work; background workers are
the sole calendar writers, for upserts, cancellations and undo compensation. A `pending` email is
always claimable (`emails_pending_is_claimable_check`), and a crashed worker's row is reclaimed at
the next claim, never by a periodic sweeper that changes status by age.

## Consequences

Ambiguous states (user intent) are never repaired automatically; they open an incident.

## Confirmation

`backend/tests/test_state_ownership_s5.py`, `backend/tests/db/test_calendar_work.py`,
`backend/tests/db/test_emails.py`, `backend/tests/db/test_proposals.py` (SEL-085..092, SEL-300..336,
SEL-212..220).

## Retirement proof

A simpler model that keeps every invariant above asserted.

## Reversal plan

Not cheap: each owner's invariants would move into application code.
