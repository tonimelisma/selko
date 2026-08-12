# Production Email Ingestion Discovery — 2026-08-12

**Status:** discovery complete; acquisition fix is intentionally not implemented
in this increment.

**Scope:** the production rollout of durable Gmail/Outlook polling, the UUID
serialization failures found during rollout, and the remaining acquisition
failure after discovery recovered.

## Executive outcome

The deployment is live and the discovery half of polling now works in
production. The system is **not fully healthy**: the worker discovers new
messages, but the acquisition worker moves those messages to `retry` with
`last_error_code=unknown`. The remaining defect must be fixed and verified in
a new source-code increment. No production data was reset, requeued manually,
or deleted during this investigation.

The correct stopping point is here because the remaining failure is a new
production defect, not a reason to add another speculative bandaid to an
already-deployed patch series.

## Completed and integrated work

`main` is clean at `a9dab19b` and contains the following merged fixes:

| Commit | Change | Production result |
| --- | --- | --- |
| `e15dc9c5` / PR #299 | Await Gmail/Outlook discovery dispatches | Removed the coroutine-never-awaited path. |
| `df5a6103` / PR #300 | Normalize provider message/folder IDs before JSON encoding | Removed the discovery-page UUID serialization failure. |
| `a9dab19b` / PR #301 | Normalize `SyncClaim` UUID fields at the asyncpg boundary | Allowed the real production discovery path to complete. |

Each source increment used an isolated worktree, a regression test, the
backend Tier 1 gate, a pull request, merge-and-cleanup, staging verification,
and a production deployment.

## Evidence collected

### Local and staging gates

- PR #301 Tier 1: **1,066 unit tests passed**, **229 integration tests passed**,
  **13 expected skips**.
- Staging schema/code compatibility: **80 migrations applied**.
- Staging API and web deployed the exact main commit `a9dab19b`.
- Staging API and web health checks returned 200.
- Staging Tier 2: **20 tests passed**, including real Gmail, OAuth, attachment,
  RLS, and end-to-end sync checks.
- Production schema/code compatibility: **80 migrations applied**.

### Production deployment and transport

- Production API and web are live on `a9dab19b`.
- The public API domain is `https://api.selkoapp.com`; the Render service
  hostname returns the expected blocked-subdomain response and is not the
  public health URL.
- `GET /health` returns `{"status":"ok"}` through the public API domain.
- `GET /health/egress` reports `transport: "asyncpg"`, with Supabase, Graph,
  and Gmail traffic attributed. No post-deploy `RuntimeWarning`, traceback, or
  UUID serialization match was found in the Render log window.
- All four ingestion tasks are alive and the LISTEN/NOTIFY listener is
  connected.

### Fresh post-deploy poll

At approximately 03:10 UTC, after the durable backoff expired:

- Gmail run completed successfully: **1 provider ID seen, 1 item inserted**.
- Outlook run completed successfully: **10 provider IDs seen, 9 inserted,
  1 existing**.
- Both provider sync states reset `consecutive_failures` to **0**, cleared
  their error fields, and recorded fresh `last_success_at` timestamps.

This proves PRs #299–#301 fixed the discovery path. It does **not** prove the
full email journey, because acquisition then failed for the newly discovered
items.

### Remaining production failure

Immediately after the successful discovery runs, the latest ingestion items
showed:

- 10 new items in `retry` with `last_error_code=unknown` and recent error
  timestamps;
- 12 older Outlook items in `dead_letter` with `database_transient`, which
  predate this rollout and remain an open historical condition;
- `/health/ingestion` remains `degraded` with `items_pending`, historical dead
  letters, and open historical incidents.

The production sync ledger is therefore healthy at discovery but not healthy
end-to-end at acquisition.

## Root-cause analysis

The remaining failure is the same class of boundary mistake, one layer later:

1. `EmailIngestionRepository.claim_item()` returns a row from
   `claim_email_ingestion_item()` through asyncpg.
2. PostgreSQL UUID columns in that row are `uuid.UUID` objects, including
   `integration_id`, `user_id`, and `id`.
3. `EmailIngestionWorker.acquire_item()` copies `item["integration_id"]` into
   the provider-agnostic email payload.
4. `EmailIngestionRepository.save_email_with_attachment_descriptors()` calls
   `json.dumps(email_payload)` before invoking the atomic RPC.
5. A UUID in that payload is not JSON serializable, so acquisition fails and
   `fail_email_ingestion_item()` correctly schedules a retry.

The source evidence is in:

- `backend/selko/services/email_ingestion.py` — `claim_item()` returns
  `dict(row)` without normalizing UUID values, while
  `save_email_with_attachment_descriptors()` JSON-encodes the payload.
- `backend/selko/workers/email_ingestion.py` — `acquire_item()` copies the
  claimed `integration_id` into `parsed` before calling the atomic save.
- `supabase/migrations/20260801000001_polling_email_ingestion_v2.sql` — the
  claim function returns the `email_ingestion_items` row, whose `id`,
  `integration_id`, `user_id`, and optional `email_id` columns are UUIDs.

The database retry behavior is correct; the bug is that a database-native row
was allowed to cross into a JSON-bound service contract without normalization.

## Next implementation increment

Create an isolated source worktree and implement one explicit claimed-row
boundary contract:

1. Add a small normalization helper at the repository boundary for every UUID
   field emitted by `claim_email_ingestion_item()` (`id`, `integration_id`,
   `user_id`, and `email_id` when present). Preserve `None` and leave provider
   text/array fields unchanged.
2. Make `claim_item()` return the normalized row so Gmail, Outlook, removal,
   completion, and error paths all receive the same declared string contract.
3. Add unit regression coverage that supplies asyncpg `UUID` values and asserts
   the claimed item is JSON-safe before the worker uses it.
4. Add or extend a real integration test that claims an item and executes the
   atomic email-plus-attachment-descriptor RPC with a provider fixture. The
   test must prove the SQL function is called, not merely mocked.
5. Run `./scripts/verify.sh backend` before the PR is created.
6. Merge through the repository cleanup script, then repeat the staging schema
   gate, staging deployment, staging Tier 2 suite, production schema gate, and
   production deployment.
7. After deployment, verify a fresh provider poll through the ledger and
   require both discovery **and acquisition** to complete before declaring the
   incident resolved.

## Definition of done for the next increment

The next increment is not done until all of the following are true:

- no claimed UUID reaches `json.dumps()` as a UUID object;
- Gmail and Outlook fresh runs are `completed` with no error code/detail;
- newly discovered items transition out of `retry` into `completed` (or a
  provider-deletion `removed` outcome when independently justified);
- `/health/ingestion` has alive tasks, a connected listener, no new repeated
  failure/stale-poll incidents, and no new dead letters;
- the historical 12 dead letters and their incident are reported separately
  and are not silently erased or requeued as part of the code fix;
- `/health/egress` still reports `asyncpg` transport and bounded attributed
  traffic;
- post-deploy logs contain no UUID serialization error, unhandled traceback,
  or async coroutine warning;
- `main` is clean and the worktree cleanup has preserved every uncommitted
  artifact before removal.

## Explicit non-actions taken

- No production secret values are recorded here.
- No production database rows were manually updated to force an earlier poll.
- No dead-letter rows were deleted or blindly requeued.
- No acquisition implementation was committed after the evidence above was
  collected.
