# 0011. Parallel extraction with a fenced commit

- Status: accepted
- Date: 2026-11-28

## Context and problem

Two emails about the same event, extracted at the same time, created duplicates. Serializing
extraction per user would lose most of the parallelism (a cold start took about half an hour).
Requirements: [SEL-165..170](../requirements/extraction.md).

## Decision drivers

- Keep extraction parallel within and across users.
- No duplicate events.
- Never hold a transaction or lock across an LLM call.

## Considered options

### Optimistic concurrency on the `(user_id, local_day)` candidate band (chosen)

- Good: only the commit is checked; different days never conflict.
- Bad: a conflict costs a recompute.
- Failure modes: a fingerprint computed differently by producer and commit would conflict forever, so both use one function.

### Per-user lanes, one in-flight email per user, a lock held across the LLM call, a per-day version table, a semantic unique index

- Good: each closes the race.
- Bad: three tables and six functions; lost parallelism; long locks; timezone logic in triggers; false merges.
- Failure modes: throughput collapse or wrong merges.

## Decision

Extraction runs concurrently (8 by default). `selko.db.events.commit_email_extraction` re-checks a
fingerprint of the candidate band the decision was computed against, plus a hint fingerprint over
events and calendar entries reached through identity hints; on mismatch it returns a conflict,
writes nothing, and the worker recomputes (up to 3 times, then the normal retry). The lease fence
(`locked_by`, `lock_generation`) is orthogonal: it stops a zombie worker, and a stale generation
writes nothing. Events are written only by this commit.

## Consequences

`backend/tests/test_single_data_layer.py` fails on any SQL that writes `events` elsewhere.

## Confirmation

`backend/tests/integration/test_integration_fenced_event_commit.py`,
`backend/tests/test_fenced_event_commit.py` (SEL-165..170), `backend/tests/test_single_data_layer.py`
(SEL-679).

## Retirement proof

A different concurrency model (for example a single extraction worker) shown to keep throughput.

## Reversal plan

Serialize extraction per user in the pool; the commit fence can stay.
