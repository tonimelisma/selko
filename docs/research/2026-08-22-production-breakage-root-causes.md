# Production breakage by root cause (2026-08-22)

Eight weeks of production-breaking commits, classified by what would have caught them. The
conclusion drives the scope table in `CLAUDE.md`: file paths decide which lane runs, the risk
dimension decides what else must be checked.

| Root cause | Examples | Local tests catch it? |
|---|---|---|
| Config / environment | #218 prod env overrides, #217 workers off by default, #151 auth redirect URLs | No: invisible in a diff and locally |
| Production data shape | #351 rehearsal vs real rows, #196 review incident | No: the local database is empty or seeded |
| Elapsed time / runtime | #191 OOM (~2 MB/min), #235 Outlook token refresh mid-pass | No: needs hours of running |
| Observability gaps | #215 surface prod integration failures | No: you cannot test what is never reported |
| Tests hiding bugs | #232 "the production bugs it was hiding" | The tests were the problem |

Only the last row is code logic. Verification was dense on the axis that rarely breaks and thin on
the three that do, which is why "lots of tests" and "production broke again" were both true. Adding
unit tests does not move these numbers; matching the dimension does:

| Dimension a change touches | Required beyond the lanes |
|---|---|
| A one-line config or env var | Verify the value in the target environment; `.env.example` proves nothing |
| Migration touching a populated table | Run it on a production-shaped copy (`backend/tests/fixtures/imported_from_postgres.sql` at least; for a large table, a copy made on the server) |
| Worker, loop, or long-running path | Watch RSS and `/health/egress` over hours after the release |
| New user-owned table | Its `selko.db` functions take `user_id` (`backend/tests/db/test_ownership.py`) |
| New code path behind a flag or injected dependency | A test asserting the dependency reaches the call site |
| Pure logic, no schema or config change | The lanes are sufficient |

A 500-line refactor with no schema or config change is usually safer than a one-line env edit.
