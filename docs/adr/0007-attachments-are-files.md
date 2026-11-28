# 0007. Attachments are files in the data directory

- Status: accepted
- Date: 2026-11-28

## Context and problem

Attachments were objects in hosted storage. With one data directory, they can live next to the
database and be backed up with it. Requirements: [SEL-075..084](../requirements/ingestion.md),
[SEL-720..723](../requirements/privacy.md).

## Decision drivers

- One volume to back up.
- No path traversal.
- Owner-only access.

## Considered options

### Files under `<SELKO_DATA_DIR>/attachments/` (chosen)

- Good: no storage service; imported rows' paths stay valid.
- Bad: disk space is shared with the database (#452 tracks a storage surface).
- Failure modes: a full disk stops writes.

### Blobs in SQLite

- Good: one file.
- Bad: a large, slow database and backups.
- Failure modes: migrations copy gigabytes.

## Decision

Attachments are stored as `{user_id}/{uuid12}_{filename}` under `<SELKO_DATA_DIR>/attachments/`,
written to a temporary file, fsynced and renamed; any path that would resolve outside the directory
is refused. `GET /attachments/{id}/content` serves them to their owner only.

## Consequences

The SHA-256 of each file is stored but not used for deduplication.

## Confirmation

`backend/tests/db/test_attachments.py`, `backend/tests/test_attachments.py` (SEL-081..083),
`backend/tests/db/test_client_routes.py` (SEL-720).

## Retirement proof

A storage need the local disk cannot meet.

## Reversal plan

Write a storage adapter behind `services/attachments.py`; the layout is the key.
