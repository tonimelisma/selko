# Production deploy log

One entry per production deploy, named `<date>-<short-sha>.md`.

## Why this exists

Eight weeks of production-breaking commits classified by root cause:

| Root cause | Examples | Caught by local tests? |
|---|---|---|
| Config / environment | #218 prod env overrides, #217 workers off by default, #151 auth redirect URLs | No — invisible in a diff and locally |
| Production data shape | #351 rehearsal vs real rows, #196 review incident | No — the local DB is empty or seeded |
| Elapsed time / runtime | #191 OOM (~2 MB/min), #235 Outlook token refresh mid-pass | No — needs hours of running |
| Observability gaps | #215 surface prod integration failures | No — you cannot test what is never reported |
| Tests hiding bugs | #232 "the production bugs it was hiding" | The tests were the problem |

Only the last one is a code-logic failure. Our verification is dense on the axis
that rarely breaks (logic, locally, at t=0, empty database) and thin on the three
that do (config, real data, elapsed time). More unit tests cannot move those
numbers. Two of these categories are **only** observable after deploy, which is
what this log is for.

## Required fields

Copy `TEMPLATE.md`. The observation windows are not optional: a deploy is not
finished when it is applied, it is finished when it has been watched.

The field that compounds is **"which gate should have caught it"**. That is how
an incident becomes a permanent gate improvement instead of folklore.
