# 0002. One owner per data directory

- Status: accepted
- Date: 2026-11-28

## Context and problem

SQLite is safe for one writer process. Two servers started on the same data directory (a stale
container, a manual run beside the service) would both run workers and both migrate. Requirements:
[SEL-605..608](../requirements/operations.md).

## Decision drivers

- Two owners must be impossible, not merely unlikely.
- Operator commands must still run beside the server.

## Considered options

### An exclusive `flock` on `<SELKO_DATA_DIR>/.selko.lock` held for the process lifetime (chosen)

- Good: the kernel releases it when the process dies; no stale-lock cleanup.
- Bad: does not protect against a second host mounting the same disk.
- Failure modes: a second owner refuses to start, loudly.

### Rely on the host tooling alone

- Good: nothing in the app.
- Bad: one mistake runs two owners.
- Failure modes: silent double processing and interleaved migrations.

## Decision

`selko.api` and `selko.worker_app` take the lock in `selko.db.datalock` before opening the
database and hold it while they run; a second owner exits. `selko.admin` takes no lock and runs
beside the server. The host's tooling also prevents two containers on one directory; the lock is
the second safeguard.

## Consequences

Because there is exactly one owner, every lease found at startup belongs to a dead run and is
released before the workers start (SEL-630).

## Confirmation

`backend/tests/db/test_datalock.py` (SEL-605..608); the image lane checks the lock in the
running container.

## Retirement proof

A design with more than one process writing the directory (see ADR 0001) would supersede this.

## Reversal plan

Remove the lock call; the host tooling remains the only guard.
