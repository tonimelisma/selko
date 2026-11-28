# 0004. No hosted database

- Status: accepted
- Date: 2026-11-28

## Context and problem

Selko once used a hosted Postgres with row-level security, a connection pooler and database
notifications. After the move to SQLite, any surviving import of those clients would be a second
data path. Requirements: [SEL-677](../requirements/operations.md), [SEL-629](../requirements/operations.md).

## Decision drivers

- One data layer; no credentials for a database service anywhere.
- The guard must fail, not warn.

## Considered options

### Forbid every hosted-database client in code and in the lock file (chosen)

- Good: a regression is a red test.
- Bad: an import for an unrelated reason is refused too.
- Failure modes: none known.

### Rely on review

- Good: no guard to maintain.
- Bad: the old clients drift back in.
- Failure modes: two data paths that disagree.

## Decision

No Python file imports supabase, postgrest, asyncpg or psycopg, and `uv.lock` carries none of
them. The database the one-time importer made from the hosted database is kept as
`backend/tests/fixtures/imported_from_postgres.sql`, and every migration must still apply to it.

## Consequences

Ownership that row-level security used to enforce is now the `user_id` argument of every
data-layer function ([ADR 0016](0016-ownership-by-user-id-in-the-data-layer.md)).

## Confirmation

`backend/tests/test_no_hosted_database.py` (SEL-677); `backend/tests/db/test_imported_fixture.py`
(SEL-629).

## Retirement proof

Superseding ADR 0001 with a database server.

## Reversal plan

Delete the guard test; port `selko.db` to the server.
