# Specs

**Unfinished plans only, in the order they are executed.** Nothing here is
finished. If a plan is done, it does not live here.

Status as of 2026-08-12.

---

## Execution order

Work top to bottom. A plan may not start until everything above it that it
declares a dependency on has landed.

| # | Plan | Increments | Status | Gate to start |
|---|---|---|---|---|
| 1 | [Stub rollback and gate repair](stub-rollback-and-gate-repair.md) | G1–G7 | Completed; retained as the gate-repair record | G1–G7 merged; staging access remains an operator check |
| 2 | [Parallel extraction, fenced commit](parallel-extraction-fenced-commit.md) | P1–P4 | P1–P3 implemented; P4 repair tooling implemented, production apply awaits seven-day observation and approval | G1–G4 merged, gate green ×3 |
| 3 | [Calendar identity and cancellation](calendar-identity-and-cancellation.md) | C1–C3 | C1 implemented; C2–C3 planned | P1–P3 verified in production |
| 4 | [Foundation integrity](foundation-integrity.md) | F7b, F8, F9 open | Partially implemented | F7b needs staging access; F8 needs operator approval |
| 5 | [Cutover verification](cutover-verification-20260807.md) | Ordered checklist | Verified locally, not deployed | Executed *through* F7–F8, never directly |
| 6 | [OAuth reconnect catch-up](oauth-reconnect-catch-up.md) | Steps 7–9 open | Partially implemented | Independent; C3 adds `cancel_queued` to its recovery sets |
| — | [Review queue integrity](review-queue-integrity.md) | R1 open | Partially implemented **and normative** | Not scheduled on its own — see below |

### 1 · Stub rollback and gate repair — **the next increment**

Both Tier 1 gates are red on `main`, and four increments merged over that red.
G1 removes the R2–R5 stub-ware and the five undeployed empty tables. G2 pins
every enumerated CHECK domain — the class-killer for the two constraint
truncations R2 and R4 shipped through a green gate. G3 makes the integration
suite order-independent and decouples Tier 1 from a live Google token. G4 fails
the build on unreachable modules. G5 fixes eight R1 frontend defects. G6
corrects the record and prunes 161 MB of eval artifacts. G7 closes out the
ingestion incident. Carries the full 17-defect register with file and line.

**G1 → G2 → G3 → G4 in that order.** G5 and G6 may run in parallel after G3.
Consider doing G3 before G1 so G1's gate result is trustworthy.

### 2 · Parallel extraction, fenced commit

Replaces `review-queue-integrity.md` R2 while **upholding its decisions 6 and
7**: extraction stays parallel within a user and across users, and every
resolution write stays fenced. The duplicate race is closed by optimistic
concurrency on the region that actually needs it — the commit re-checks the
`(user_id, local_day)` candidate band its decision was computed against, and
recomputes if it changed. One column, one RPC, no new tables, no second worker.
P4 carries the one-time production duplicate repair.

### 3 · Calendar identity and cancellation

Replaces `review-queue-integrity.md` R3 and R4 as three vertical slices —
parser, canonicalizer, table, matcher, test — under one rule: *a schema object
and the code that fills it land in the same increment.* That rule is why R3 and
R4 failed.

### 7 · Review queue integrity — normative, not scheduled

R1 is partially implemented with eight open defects, and those are repaired by
**G5**, not by this file. R2–R5 are unimplemented and superseded by plans 2 and
3. The file stays because **§1, §3, §5, §7, §8 and §9 are the normative
requirement text** those plans build against; only §6's mechanism is superseded,
and it carries an in-file banner so nobody starts building it.

---

## The status rule

| Status | Requires |
|---|---|
| **Planned** | Nothing merged. |
| **Partially implemented** | Some increments merged. The entry **names each increment individually**. A batch is never summarised in aggregate — that is how "#306–#312 delivered R2–R5" became true-sounding and false. |
| **Implemented** | Every increment merged, **and** a test executes each new code path against a real database or a real browser, **and** the reachability guard covers every new module, **and** the durable docs are updated. At that point the file is **deleted** — see below. |

**An increment is not done because its PR merged. It is done when something
that would fail if it were absent, passes.**

---

## Lifecycle — finished plans are deleted, not archived

1. Write the spec here and get it reviewed.
2. Implement it (worktree + PR workflow in `CLAUDE.md`).
3. Fold the durable "how it works" content into the right reference doc —
   `docs/database-schema.md`, `docs/gmail-integration.md`, `docs/job-queue.md`,
   `docs/microsoft-graph-failure-ledger.md`, `docs/backlog.md` — and update
   `CLAUDE.md`.
4. **Delete the spec file.** Git is the history.

This replaces the previous "mark Implemented and keep for history" rule, which
contradicted this directory's own definition of what belongs here and grew it to
twenty files, five of which were not even indexed. A reader could not tell which
three mattered.

Seventeen finished or parked specs were retired on 2026-08-12. Every one is a
`git show` away:

```bash
git show 837f830e:docs/specs/live-ui-updates.md
```

Their shipped behaviour is described in the reference docs; their *reasoning* is
in the commit history that implemented them.

---

## What belongs here

A detailed, step-by-step design for something **not yet built**, written to be
handed to a developer. Concrete: file paths, function signatures, SQL, edge
cases, and the test that must fail first.

## What does not

| Content | Home |
|---|---|
| How a shipped feature works today | `docs/` reference docs |
| Incident and postmortem records | `docs/microsoft-graph-failure-ledger.md` |
| Parked or deferred ideas | `docs/backlog.md` |
| Product requirements and architecture | root `PRD_ARCH.md` |
| History of a finished plan | git |

## Naming

`docs/specs/<feature-slug>.md`.
