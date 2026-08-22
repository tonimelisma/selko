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
- **Rehearsal:** (`scripts/rehearse_cutover.py --faithful`) predicted vs actual
- **Affected table row counts:**

## Observation
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
