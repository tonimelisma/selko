# Specs

Implementation specifications for planned, in-progress and shipped features.

**Status as of 2026-08-12.** Rewritten after the R1–R5 review found this index
contradicting the repository on two entries and omitting five files entirely.
**Every file in this directory is now listed below with an explicit call.**

---

## The status rule

Four statuses, and the evidence for each is mechanical, not editorial:

| Status | Requires |
|---|---|
| **Planned** | Nothing merged. |
| **Partially implemented** | Some increments merged. The entry **names each increment individually**. A batch is never summarised in aggregate — that is how "#306–#312 delivered R2–R5" became true-sounding and false. |
| **Implemented** | Every increment merged, **and** a test executes each new code path against a real database or a real browser, **and** the reachability guard covers every new module, **and** the durable docs are updated. |
| **Superseded** | Another spec, named and linked, owns the outcome now. |

**An increment is not done because its PR merged. It is done when something
that would fail if it were absent, passes.**

---

## Read this first

- [**Stub rollback and gate repair**](stub-rollback-and-gate-repair.md) —
  **Planned. This is the next increment; nothing else may merge before its
  G1–G4.** Both Tier 1 gates are red on `main` (`verify.sh backend` exits 1 on
  an order-dependent integration test; `verify.sh frontend` exits 1 on a flaky
  timeout with three unhandled rejections). G1 removes the R2–R5 stub-ware and
  the five undeployed empty tables. G2 pins every CHECK-constraint domain — the
  class-killer for the two constraint truncations R2 and R4 shipped through a
  green gate. G3 makes the integration suite order-independent and decouples
  Tier 1 from a live Google token. G4 fails the build on unreachable modules.
  G5 fixes eight R1 frontend defects. G6 corrects the record and prunes 161 MB
  of eval artifacts. G7 retires the stale ingestion incident record. Carries
  the full 17-defect register.

---

## Active — in dependency order

1. [**Stub rollback and gate repair**](stub-rollback-and-gate-repair.md) —
   **Planned.** G1–G7. Blocks everything below.

2. [**Parallel extraction, fenced commit**](parallel-extraction-fenced-commit.md) —
   **Planned.** P1–P4. Replaces `review-queue-integrity.md` R2 while **upholding
   its decisions 6 and 7**: extraction stays parallel within a user and across
   users, and every resolution write stays fenced. The duplicate race is closed
   by optimistic concurrency on the region that actually needs it — the commit
   re-checks the `(user_id, local_day)` candidate band its decision was
   computed against, and recomputes if it changed. One column, one RPC, no new
   tables, no second worker. P4 carries the one-time production duplicate
   repair. **Depends on G1–G4.**

3. [**Calendar identity and cancellation**](calendar-identity-and-cancellation.md) —
   **Planned.** C1–C3. Replaces `review-queue-integrity.md` R3 and R4. Each
   increment is a vertical slice — parser, canonicalizer, table, matcher, test
   — because R3 and R4 failed by shipping schema without its writer.
   **Depends on P1–P3 in production.**

4. [**Foundation integrity**](foundation-integrity.md) — **Partially
   implemented.** F1–F7 merged (#287–#294). F4's schema contract tests and F6's
   migration-order guard are the most valuable assets in the repository.
   **Open:** F7b staging worker drill and 24-hour soak; F8 production cutover;
   and F9, which merged `prune-eval-results.sh` but was never run — tracked
   eval results grew to 14 228 files / 161 MB, so D6 is open. Also records F4's
   blind spot, found by this review and closed by G2: the contract enumerates
   `SECURITY DEFINER` functions, so a status value written from Python is
   invisible to it.

5. [**Review Queue Integrity**](review-queue-integrity.md) — **Partially
   implemented and partly superseded.** R1 partially implemented (#305) with
   eight open defects, repaired by G5. R2–R5 not implemented and superseded as
   above. **§1, §3, §5, §7, §8 and §9 remain the normative requirement text**
   for the successor plans; only §6's mechanism is superseded, and it carries a
   banner saying so.

6. [**Cutover Verification**](cutover-verification-20260807.md) — **Verified
   locally, not deployed.** The single ordered cutover checklist (migrations →
   code → flag last). **Its recorded baseline is stale** — line 28 says
   production is at `a50e1e4e` / schema `20260803000002`; production is
   actually at `a9dab19b` with 80 migrations, and `main` carries 89. Refresh
   the baseline as the first step of `foundation-integrity.md` F8, and execute
   through F7–F8, never directly. Keep — it is the only ordered runbook.

7. [**OAuth reconnect catch-up**](oauth-reconnect-catch-up.md) — **Partially
   implemented.** Backend (#236–#239 + review-fix migration) and UI projection
   on web, iOS and Android are delivered. **Open:** reviewed legacy production
   repair, staging fault injection, production rollout. `calendar-identity-and-
   cancellation.md` C3 adds `cancel_queued` to its recovery sets.

---

## Retiring — do not treat as active

- [**Production email ingestion discovery — 2026-08-12**](production-email-ingestion-discovery-20260812.md)
  — **Resolved; being retired by G7.** This is an incident record, not a plan,
  and by the rules below it does not belong in this directory. Its
  "Next implementation increment" describes a fix that **shipped the same day**
  as #302 (`_normalize_pg_row` in `services/pg.py`) and #304, with the unit and
  real-database regression tests it asked for — so the document reads as open
  when it is not. G7 folds it into `docs/microsoft-graph-failure-ledger.md`,
  verifies the 10 retry items actually completed, and forces a written decision
  on the 12 historical `database_transient` dead letters, which have been
  carried as "reported separately" across three documents without anyone
  choosing.

---

## Implemented — kept for history

Do not re-derive decisions from these; check the code. Every one of the five
files previously missing from this index is now listed.

| Spec | Shipped in |
|---|---|
| [Direct-PG completion and live-UI hardening](direct-pg-completion-and-live-ui-hardening.md) | C1–C9 (#279–#286 + `0654d4fe`). Follow-on defects D1–D6 tracked in `foundation-integrity.md` §2. |
| [Live UI updates](live-ui-updates.md) | web #270, iOS #271, Android #272; hardened by #284, #285. **Known residue:** a single channel failure can emit both `CLOSED` and `CHANNEL_ERROR`, scheduling two rejoins. Add a bounded-attempt cap next time this file is opened. |
| [Direct Postgres work transport](direct-postgres-work-transport.md) | Inc0–6 (#262–#269). |
| [Post-cutover reliability and scale](post-cutover-reliability-and-scale.md) | R1–R9. |
| [Ingestion & recovery hardening](ingestion-recovery-hardening.md) | #241–#247 + Aug 6 egress work. |
| [Polling email ingestion v2](polling-email-ingestion-v2.md) | #231–#235. Durable polling is the only ingestion path. **Its duplicated cutover runbook section is superseded** — use `cutover-verification-20260807.md`. |
| [Outlook email support](outlook-email-support.md) | Implemented. Reference behaviour now lives in `docs/gmail-integration.md` and `docs/microsoft-graph-failure-ledger.md`. |
| [Reliable email ingestion fix-forward](reliable-email-ingestion-fix-forward.md) | Implemented (2026-07-12). Largely subsumed by polling v2 above; kept only as the record of why cursors and folder inclusion work the way they do. |
| [Review-list quality fixes](review-list-quality-fixes.md) | Implemented through #194. **Partly superseded:** its "Interaction with existing events" trade-off assumed the user's calendar is the source of truth for cancellations. `review-queue-integrity.md` decision 10 overrides that for pending Review rows; `calendar-identity-and-cancellation.md` C3 implements the override. |
| [Calendar policy, LLM fallback and incremental evals](calendar-policy-llm-fallback-and-incremental-evals.md) | WS1–WS7. Stage A/B full spend recorded as provisional in its own header — that caveat is still open and belongs to whoever next changes model routing. |
| [Warmth design system](warmth-design-system.md) | Implemented. Canonical tokens are `design/tokens.json` and `docs/brand-guide.md`; treat those as the source of truth over this file. |
| [Egress and work scheduling](egress-and-work-scheduling.md) | 1.5 M → ~3 k RPCs/day. |
| [Review action contrast, sizing and grouping](review-action-contrast-and-sizing.md) | #273. |
| [Cross-platform Review layout and action accessibility](cross-platform-review-accessibility.md) | Implemented except canonical Android screenshots, blocked by a repeatable Pixel_8 emulator crash after APK install. Decisions 5, 8 and 11 superseded by the contrast/sizing spec. |
| [Photo surface removal](photo-surface-removal.md) | #201. |

## Parked

- [OneDrive photo ingestion](onedrive-photo-ingestion.md) — parked 2026-07-13
  on cost/value. Do not re-propose without new information.

---

## Nothing was deleted, and why

Every implemented spec is retained: they carry the *reasoning* behind decisions
the code cannot express, and several are still cited as normative by active
plans. The two files that genuinely do not belong here are handled explicitly
rather than left to rot — the ingestion incident record moves to the failure
ledger under G7, and R2–R5's superseded mechanism carries an in-file banner so
a reader cannot start building it by accident.

The failure mode this directory has to avoid is not too many files. It is a
file whose header says something the repository does not.

---

## What belongs here

**Specs / implementation plans** — a detailed, step-by-step design for something
not yet built, written to be handed to a developer. Concrete: file paths,
function signatures, SQL, edge cases, and the test that must fail first.

## What does not

- **Reference docs** (how a shipped feature works today) go in `docs/` —
  `docs/gmail-integration.md`, `docs/database-schema.md`.
- **Incident and postmortem records** go in the relevant ledger, e.g.
  `docs/microsoft-graph-failure-ledger.md`.
- **Product requirements and architecture** live in the root `PRD_ARCH.md`.

## Lifecycle

1. Write the spec here and get it reviewed.
2. Implement it (worktree + PR workflow in `CLAUDE.md`).
3. Fold the durable "how it works" parts into `docs/`, update
   `docs/database-schema.md` and `CLAUDE.md`, then mark the spec
   **Implemented** against the rule at the top of this file.

## Naming

`docs/specs/<feature-slug>.md`.
