# Specs

**Unfinished plans only, in the order they are executed.** Nothing here is
finished. If a plan is done, it does not live here.

Status as of 2026-08-21.

---

## Execution order

Work top to bottom. A plan may not start until everything above it that it
declares a dependency on has landed.

| # | Plan | Increments | Status | Gate to start |
|---|---|---|---|---|
| 1 | [Stub rollback and gate repair](stub-rollback-and-gate-repair.md) | G1–G7 | Completed; retained as the gate-repair record | G1–G7 merged; staging access remains an operator check |
| 2 | [Parallel extraction, fenced commit](parallel-extraction-fenced-commit.md) | P1–P4 | P1–P3 implemented; P4 repair tooling implemented, production apply awaits seven-day observation and approval | G1–G4 merged, gate green ×3 |
| 3 | [Calendar identity and cancellation](calendar-identity-and-cancellation.md) | C1–C3 | C1–C3 implemented; staging verification and production observation remain operator gates | P1–P3 verified in production |
| 4 | [State ownership and deterministic recovery](state-ownership-and-deterministic-recovery.md) | S1–S5 | Implemented; local real-Postgres gate passes; staging schema/RPC gate green; **staging service/worker gate and §12 drill never run**; not deployed to production | P1–P3 and C1–C3 implemented; production incident repaired and audited |
| 5 | [Executable truth](executable-truth.md) | V1–V8, D1–D3 | Planned; nothing implemented | Gates plan 4's outstanding evidence — start before any further S-plan claim |
| 6 | [Foundation integrity](foundation-integrity.md) | F7b, F8 open; F9 complete with accepted history debt | Partially implemented | F7b needs staging access; F8 needs operator approval |
| 7 | [Cutover verification](cutover-verification-20260807.md) | Ordered checklist | Verified locally, not deployed | Executed *through* F7–F8, never directly |
| 8 | [OAuth reconnect catch-up](oauth-reconnect-catch-up.md) | Steps 7–9 open | Partially implemented | Independent; C3 adds `cancel_queued` to its recovery sets |
| — | [Review queue integrity](review-queue-integrity.md) | R1 defects repaired by G5; remaining text is normative | Not an implementation queue | R2–R5 superseded by plans 2 and 3 |

### 1 · Stub rollback and gate repair — completed record

G1–G7 removed the R2–R5 stub-ware, pinned enumerated CHECK domains, repaired
the real-database gate, enforced module reachability, fixed the R1 frontend
defects, pruned eval artifacts, and closed the ingestion incident. Its remaining
staging-access checks belong to Foundation Integrity; do not reopen this plan
as an implementation queue.

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

### 4 · State ownership and deterministic recovery

Separates email work, provider-discovery runs, event review, change proposals,
calendar delivery, and provenance into explicit state owners. S1 repairs
claimability and health; S2 makes every Calendar mutation worker-owned and
durable. The plan follows the production repair that found an orphaned Changes
card, unclaimable pending emails, and a stale running audit row while health
still reported ok. S3 makes proposals first-class; S4 migrates all clients;
S5 deletes compatibility state and dead mutators.

### 5 · Executable truth

Written after reviewing everything between the last committed plan and HEAD.
S1–S5 merged with no review and with the local real-Postgres gate refusing to
run, which is how two runtime SQL defects of an already-documented class
reached `main`. This plan makes the gates incapable of reporting success
without evidence (V1–V4), then fixes what the gates were hiding once they can
prove it (V5–V8): unattributed Graph egress, a dead failure ledger, an
unconditional idle poll, fencing that is a branch instead of a type, and the
half of the state-ownership collapse S5 left undone. Three decisions (D1–D3)
must be recorded before their dependent increments start.

Its governing rule: *if an invariant matters enough to write down, it matters
enough to assert; if it is not worth asserting, delete the sentence.*

### 8 · Review queue integrity — normative, not scheduled

R1's eight defects were repaired by **G5**, not by this file. R2–R5 are
unimplemented and superseded by plans 2 and 3. The file stays because **§1,
§3, §5, §7, §8 and §9 are the normative
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
