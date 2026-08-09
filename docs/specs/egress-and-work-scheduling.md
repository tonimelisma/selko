# Egress and Work Scheduling

**Status:** implemented — arch A egress 1.5M→~3k RPCs/day, single scheduler + drain, egress meter + `/health/egress` (#241-#247). Residues → post-cutover R1/R3/R9. Historical P0 now closed.

## The issue

Production burns a flat **~39 MB/hour of egress, 24 hours a day**, while serving
essentially **zero inbound HTTP** (19 requests in 2.5 days, all bot 404s). Flat,
time-of-day-independent egress with no inbound traffic is a polling loop, not
users. That is **~0.94 GB/day ≈ 28 GB/month** on a deployment with no traffic.

It is not email. Nothing was downloading mail at that rate; nothing was
measuring anything at all.

### Root cause: work discovery is a busy-wait

`WorkerPool._process_any_work` (`backend/selko/workers/pool.py`) issues one
Supabase RPC per work type per tick:

| Call | Note |
|---|---|
| `claim_scheduled_task` (photo_fetch) | **parked feature** |
| `claim_pending_email` | duplicated by `IngestionRuntime` |
| `claim_pending_photo` | **parked feature** |
| `claim_approved_event_for_sync` | |
| `claim_integration_recovery` | not yet in production |
| `refresh_waiting_calendar_recoveries` | not yet in production |

The loop slept a **flat 1.0s with no backoff**. At `worker_pool_size=3` that is
~12 RPCs/second in the currently deployed code (~18 on `main`) — roughly
**1–1.5M round trips per day**.

### Why each poll is expensive

Every claim is a separate HTTPS round trip through PostgREST. The service-role
JWT is **219 characters and sent twice** per request (`apikey` and
`Authorization: Bearer`), so ~600–900 bytes of envelope leaves the box to ask
*"is there any work?"* and receive ~20–40 bytes of `null`. **~97% of this
traffic is envelope, not information.**

### Three compounding defects

1. **Busy-wait scheduling.** The system asks for one item, sleeps, repeats —
   converting "process a queue" into a permanent poll.
2. **Two schedulers.** `WorkerPool` and `IngestionRuntime` both run in the
   FastAPI process and both poll; email work is claimed by both.
3. **Polling for work that cannot exist.** Photo ingestion is parked, yet two
   of the calls poll for it forever.

### What was already done (stopgaps, not fixes)

- **PR #247** — `selko.services.egress` meters outbound bytes by destination and
  operation (`/health/egress`, periodic log line, httpx hook on the shared
  Supabase client, Gmail/Graph payload counters). This is the part worth
  keeping: it is how any of this becomes verifiable.
- **PR #247** — geometric idle backoff on the pool loop. **This is a band-aid.**
  It multiplies the interval, trades latency for bandwidth, and leaves the
  architecture untouched. It survives only as backoff for the safety-net poll in
  the target design.

## Current production state — read before touching anything

- `ENABLE_BACKGROUND_PROCESSING=false` is set on `selko-app-production`. The
  polling loops do not start. **The leak is stopped.**
- Setting that variable triggered a Render deploy, and **Render deploys branch
  HEAD**, not the running commit. Production therefore moved from `a50e1e4e`
  (Jul 31) to `e3edbd26` (latest `main`) — a 26-commit jump — **without the 9
  pending Supabase migrations**, because the GitHub workflow that runs
  `supabase db push` was not involved.
- The mismatch is currently inert: the code that needs the missing tables is the
  ingestion runtime, which is disabled. **It stops being inert the moment
  `ENABLE_BACKGROUND_PROCESSING` is flipped back on.**
- Recommended: roll back in the Render dashboard to
  `dep-d9m15qnqj5pc739u38c0` (`a50e1e4e`). The env var persists through a
  rollback, so bandwidth stays stopped and code/schema agree again.

## The fix: it is a batch, so run it as one

Provider sync is a scheduled batch. It does not need event plumbing, a
sleep-until-next-due query, or a direct Postgres transport — at ~12 passes per
hour instead of ~43,200 claim calls, per-call envelope cost stops mattering.
The defect is call **frequency**, not call **size**.

The rule: **drain the queue, then sleep until the next tick** — never "ask for
one item, sleep, repeat."

### Target shape

- **One scheduler per process**, not N independent pollers. It runs a pass and
  fans the actual I/O out to a concurrency-limited executor pool. Durability and
  multi-instance safety stay exactly where they are today: leases and
  `FOR UPDATE SKIP LOCKED`. Nothing about the ownership model changes.
- **A pass drains.** Claim and process until empty, then sleep to the next tick.
- **In-process nudge for the two user-initiated paths** — approving an event and
  `request_email_sync_now`. Both originate in the same FastAPI process that runs
  the workers, so an `asyncio.Event` wakes the scheduler immediately. No DB
  triggers, no `LISTEN/NOTIFY`, no new connection, no pooler constraints. If the
  nudge is ever missed (or a second instance is added), the next tick catches it
  — degraded latency, never lost work.
- **Delete what cannot produce work:** the parked photo polls.
- **One owner for email:** `IngestionRuntime` only; remove the duplicate
  `claim_pending_email` path from `WorkerPool`.

Expected idle egress: **single-digit MB/month**, with traffic thereafter
proportional to actual mail volume — and *lower* latency than today on the paths
users actually wait for, because the nudge beats both the old 1s poll and the
backed-off 30s one.

## Increments

| # | Change | Risk | Effect |
|---|---|---|---|
| 1 | Delete parked photo polls (`claim_pending_photo`, `photo_fetch` scheduled task) from the hot loop | trivial — pure removal | −33–50% of calls |
| 2 | Remove the duplicate `claim_pending_email` path from `WorkerPool`; `IngestionRuntime` owns email | low | removes second scheduler |
| 3 | Collapse N polling workers into 1 scheduler + concurrency-limited executors | medium | ÷`worker_pool_size` |
| 4 | Convert claim loops to drain-then-sleep on a fixed tick | medium | removes the busy-wait |
| 5 | In-process nudge on approve and `request_email_sync_now` | low | restores latency |
| 6 | Verify against `/health/egress` and Render metrics; then re-enable background processing | — | proves it |

1 and 2 are near-free and should land first. 4 is the actual architectural fix.

**Ordering constraint:** the ingestion-v2 cutover (9 migrations) must happen
**migrations first, code second, `ENABLE_BACKGROUND_PROCESSING` on last**, per
the atomic-deployment requirement in the deploy workflow. Increment 6 above
cannot run before that cutover is done deliberately, with
`docs/specs/ingestion-recovery-hardening.md` Increment 10 (cutover
verification) executed.

## Research topics — open questions, not assumptions

These are unresolved. Do not build on them without checking.

1. **Which provider sent the quota notification — Render or GitHub?** Not
   established. A `workflow_dispatch` run has been stuck `queued` for hours with
   zero steps while push-triggered runs succeed, which is unexplained. GitHub
   billing endpoints need a `user` auth scope that has not been granted.
2. **Does Render bill this traffic at all, and in which direction?** The
   analysis assumes outbound calls to Supabase count toward the metered
   `bandwidth_usage` figure. The metric correlates with the polling arithmetic,
   but Render's billing definition of egress has not been confirmed.
3. **What is the actual monthly quota and how much is left?** Unknown. All
   figures here are measured rates and extrapolations, not a billing statement.
4. **Is Supabase's own quota affected?** The same traffic is inbound requests to
   Supabase and counts against its limits. Not checked.
5. **What approve → calendar latency is acceptable?** Decides the tick interval
   and whether increment 5 is required or merely nice.
6. **Is multi-instance ever planned?** `numInstances: 1` today. An in-process
   nudge only wakes the local instance; the design degrades gracefully, but if
   horizontal scaling is planned this should be revisited.
7. **Actual per-call byte cost.** ~600–900 bytes is an estimate from header
   sizes. `/health/egress` will report the real number once running — confirm
   before quoting it again.
8. **Why is the `workflow_dispatch` run stuck?** No environment gate and no
   pending deployments were found. Cancel and re-dispatch is untried.
