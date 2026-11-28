# 0008. Work arrives by signal, not by polling

- Status: accepted
- Date: 2026-11-28

## Context and problem

Constant polling costs egress and hides idle loops; a platform bandwidth alert once could not tell
polling apart from real downloads. Requirements: [SEL-632..640](../requirements/operations.md),
[SEL-659..661](../requirements/operations.md).

## Decision drivers

- No idle loops.
- Work is picked up immediately after the write that creates it.
- A lost wake-up must not lose work.

## Considered options

### In-process signals after commit, with a safety-net poll as a floor (chosen)

- Good: immediate wake-ups, near-zero idle cost.
- Bad: a missed signal waits for the floor.
- Failure modes: a signal published before commit would wake a worker that cannot see the row, so signals are buffered until COMMIT and dropped on rollback.

### Periodic polling

- Good: simple.
- Bad: constant cost; latency equals the interval.
- Failure modes: bandwidth grows with users, not with work.

## Decision

A committed write that creates work calls `tx.emit_work(...)`; `selko.db.bus.WorkSignals` wakes
the waiting worker after commit. Changes a user should see call `tx.emit_live(user, resource)`; the
in-process `Bus` fans them out to `GET /live`, a Server-Sent Events stream (Bearer token, 25 s
heartbeat, re-auth at expiry, at most 5 streams per user). The safety-net poll is a floor, not a
schedule. Every outbound byte is attributed to a destination and a bounded operation template
(`/health/egress`). Mail providers are still polled on their own cadence, because they offer Selko
no push channel; that cadence is the provider's floor, not a loop over idle work.

## Consequences

Any new unconditional periodic call must be justified in the PR body against these rules.

## Confirmation

`backend/tests/db/test_event_bus.py`, `backend/tests/db/test_live_route.py`,
`backend/tests/test_egress_budget.py`, `backend/tests/test_ingestion_runtime.py` (SEL-632..640).

## Retirement proof

A provider push channel or a second process that the in-process bus cannot reach.

## Reversal plan

Replace the bus with a database-backed queue; the emit calls are the seam.
