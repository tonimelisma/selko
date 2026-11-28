# 0001. One process over one SQLite file

- Status: accepted
- Date: 2026-11-28

## Context and problem

Selko serves a web app, an API and long-running background work (mail polling, LLM extraction,
calendar writes) for a modest number of users. It used to run as several hosted services over a
hosted Postgres database, and most production failures came from the seams between them
(configuration, notification channels, connection pools). Requirements:
[SEL-600..604](../requirements/operations.md).

## Decision drivers

- Fewest moving parts to run, back up and restore.
- No network hop and no credentials between the code and its data.
- The workload is I/O bound (mail, Graph, LLM APIs), not CPU bound.

## Considered options

### One process: FastAPI + in-process workers + built web app over one SQLite file (chosen)

- Good: one thing to run; the data directory (`selko.db` + `attachments/`) is the whole state; WAL readers beside one writer make leases and fences simple.
- Bad: a crash stops web, API and workers together; no point-in-time recovery beyond disk snapshots and pre-migration copies.
- Failure modes: a blocked event loop stalls everything; blocking SQLite and CPU work therefore runs in threads (`db.run`).

### Separate API and worker services over a database server

- Good: scales each part independently.
- Bad: two processes contending for one store need a queue or notification channel, credentials and operations.
- Failure modes: the channel or pool silently stops delivering, and health that checks each part stays green.

### Serverless (Cloud Run, Lambda)

- Good: no idle cost.
- Bad: instances scale to zero, which kills the in-process ingestion loop; a local file needs one long-lived owner.
- Failure modes: work stops whenever nothing pings the instance.

## Decision

The image runs one uvicorn worker that serves the built web app, the API and the background
workers on one port. All state lives in `SELKO_DATA_DIR` (`/data` in the image). The root
filesystem is never written. Settings come from the environment (an env file on the server).

## Consequences

Scaling steps are ordered: a process pool for CPU work first, batching writes if the single
writer is measured to be the bottleneck (`DbBusy`, write latency), a database server last. There is
no hosted staging: the image lane (the exact image under the server's limits) stands in for it.
The old Django/microservice/serverless options stay rejected unless a measured limit demands them.

## Confirmation

`backend/tests/test_web_serving.py` (SEL-601, SEL-602), the data-directory tests (SEL-603), and
`scripts/image-check.sh` in the image lane (read-only root, one volume, 400 MB). Review rule: a new
process, queue or database server needs a new ADR that supersedes this one.

## Retirement proof

A measurement showing one process cannot carry the load (CPU saturation that a process pool
does not fix, or writer contention that batching does not fix), recorded in a research note.

## Reversal plan

Split the workers into a second process over the same file first (they already coordinate
through leases); moving to a database server means porting `selko.db` and is weeks of work.
