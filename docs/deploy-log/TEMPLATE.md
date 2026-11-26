# <date> — <short-sha>

## Shipped
- **Code sha:**
- **Schema version:**
- **Migrations applied:**
- **Config / env changed:** (list every variable; a correct diff plus a missing value is an outage)
- **Risk dimensions touched:** config / production-data / long-running / observability / logic

## Pre-deploy evidence
- **Verification run id:** (`.verify/runs/<id>.json`)
- **Prod lanes green:** yes / no — if no, why deploying anyway
- **Rehearsal:** (`scripts/ops.py dispatch rehearse-cutover`, run URL) predicted vs actual
- **Deploy run:** (`scripts/ops.py dispatch deploy-production …` run URL; its last step is the T+0 health check)
- **Affected table row counts:**

## Observation

Run `./scripts/check-production-health.sh` at each window and paste the result.
RSS is `/health` → `memory.rss_bytes` (and `cgroup_current_bytes` against
`cgroup_limit_bytes`, what the OOM killer acts on).
It asserts the invariants that must hold whatever the worker posture: no dead
letters, no stale or unclaimable work, workers alive, listener connected.
| Window | /health | ingestion | egress | RSS | dead letters | task restarts |
|---|---|---|---|---|---|---|
| T+0 | | | | | | |
| T+15m | | | | | | |
| T+24h | | | | | | |

## Outcome
- **Verdict:** clean / degraded / rolled back
- **What broke:**
- **Which gate should have caught it:**
- **Gate change made as a result:** (link the commit; "none" is an acceptable answer only with a reason)
