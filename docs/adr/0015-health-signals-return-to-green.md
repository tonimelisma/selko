# 0015. Health signals must be able to return to green, and measure what the API answers

- Status: accepted
- Date: 2026-11-28

## Context and problem

A gauge that can never read zero is ignored as fast as one that can never go red, and Selko
shipped both: counting permanent failures with actionable stuck rows pinned production to
`degraded`; a critical stale-poll alert fired for integrations that are deliberately not polled.
Meanwhile every health invariant was internal, so a route returned 500 to every request for eight
days with health green. Requirements: [SEL-641..658](../requirements/operations.md).

## Decision drivers

- Every signal can go red and can recover on its own.
- Health includes what users experience.

## Considered options

### Separate actionable from historical counts; publish server errors per hour (chosen)

- Good: health means something.
- Bad: more fields.
- Failure modes: a new gauge without a recovery path; reviewed per ADR.

### One aggregate count

- Good: simple.
- Bad: permanently degraded.
- Failure modes: alerts ignored.

## Decision

`health_work_state` reports `unclaimable_pending` (actionable, degrades the roll-up) separately
from `failed_emails` (terminal history, never degrades it). `request_metrics` counts responses by
outcome and `/health` publishes `requests.server_errors_per_hour`, which `scripts/assert-health.sh`
requires to be zero. Before adding a health signal, state what makes it return to green and whether
the system does that on its own.

## Consequences

`scripts/assert-health.sh` is the standard list; the image lane and the release `health` job run
it.

## Confirmation

`backend/tests/db/test_health.py` (SEL-641..649), `backend/tests/test_health_endpoints.py`
(SEL-650..658).

## Retirement proof

None expected; this is a rule for every new signal.

## Reversal plan

Not applicable.
