# 0016. Ownership is the user_id argument of every data-layer function

- Status: accepted
- Date: 2026-11-28

## Context and problem

Without row-level security, nothing in the database stops one user's query from reading another
user's rows. Requirements: [SEL-440..442](../requirements/accounts.md), [SEL-720](../requirements/privacy.md).

## Decision drivers

- Ownership enforced in one place, testable as such.
- No existence oracle across users.

## Considered options

### Every public `selko.db` function that touches a user-owned table takes `user_id` and scopes by it (chosen)

- Good: one rule, checked by a scan.
- Bad: worker-wide functions need an allowlist with reasons.
- Failure modes: a new function without `user_id` fails the build.

### Check ownership in routes

- Good: flexible.
- Bad: every route repeats the check.
- Failure modes: one forgotten check leaks data.

## Decision

Ownership is the `user_id` argument of every public `selko.db` function that touches a user-owned
table; worker-wide functions are allowlisted by name with a reason. A route answers another user's
row with 404, never 403. An operation has exactly one implementation: never a second path for the
same operation.

## Consequences

Every client route has a cross-user test; adding a route without one fails.

## Confirmation

`backend/tests/db/test_ownership.py` (SEL-440), `backend/tests/db/test_client_routes.py`
(SEL-441, SEL-720), `test_no_compat_shims_in_workers` in `backend/tests/test_workers.py` (SEL-680).

## Retirement proof

A database engine with enforced row-level security adopted instead.

## Reversal plan

Not planned.
