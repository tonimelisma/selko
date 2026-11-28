# 0017. Email is the only input

- Status: accepted
- Date: 2026-11-28

## Context and problem

Photo-library ingestion (Google Photos, later OneDrive) was parked on cost and value after
library-wide read access was revoked, then removed with its routes, worker and tables. Requirements:
[the ingestion requirements](../requirements/ingestion.md).

## Decision drivers

- Spend effort where the value is: email to calendar first, end to end.

## Considered options

### Email only; complete each journey before adding inputs (chosen)

- Good: one pipeline to make reliable.
- Bad: no photo or upload input today (#454).
- Failure modes: none.

### Keep photo ingestion

- Good: more inputs.
- Bad: provider access was revoked; cost exceeded value.
- Failure modes: a pipeline nobody uses rots.

## Decision

Gmail and Outlook mail are Selko's only inputs. Photo-library ingestion is not re-proposed until
its cost/value picture changes. New inputs or outputs (web upload, file storage, tasks) are tracked
as issues and must each complete a full journey before the next starts.

## Consequences

The removed design is in git history.

## Confirmation

Review rule; `backend/tests/test_reachability.py` keeps removed modules from lingering (SEL-678).

## Retirement proof

A changed cost/value picture, written up as research.

## Reversal plan

Restore from git history and re-review against today's architecture.
