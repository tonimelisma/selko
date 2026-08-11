# Specs

Implementation specifications for planned or in-progress features.

## Active plans

Status as of 2026-08-10.

- [Foundation integrity](foundation-integrity.md) — **planned, nothing implemented.**
  The next plan to pick up. Written after reviewing the C1–C9 batch: every defect
  that batch repaired shares one cause — the DoD gate (`pytest -m "not integration"`)
  never executes the system, so SQL is never run, the asyncpg pool is never opened
  and triggers never fire. Builds a real execution gate (`scripts/verify.sh`),
  adds schema contract tests that make the `20260809000001`/`20260809000003` class
  of defect structurally unrepeatable, fixes the defects the review found
  (D1–D8), and closes the 96-commit / 21-migration production gap. Increments F1–F9.
  **Establishes two verification tiers, neither of them CI** — Tier 1 local
  (pre-merge, real Postgres), Tier 2 staging (post-merge, real Supavisor/Render/
  OAuth/egress) — because local Supabase has no Supavisor and therefore cannot
  reach the pooler hypotheses at all (D8). **Start with F1.4 (D7): `.env.test`
  and `.env.production` have no `SUPABASE_DB_URL` while `.env.production` sets
  `ENABLE_BACKGROUND_PROCESSING=true`, so deploying `main` today hard-fails the
  API at startup.**
- [Post-Cutover Reliability and Scale](post-cutover-reliability-and-scale.md) — **implemented R1-R9 (#248-#251 + 8b94c53a, de9694eb, 766961d1, 9b14e0ca, a6d8d0c4) — counted health, Gmail batch, unified nudge, heartbeat+anti-starve, cutover gate, observability, recovery, drills, config tidy.** Gate before `ENABLE_BACKGROUND_PROCESSING=true` satisfied.
- [Ingestion & recovery hardening](ingestion-recovery-hardening.md) — **built and merged (PRs #241–#247 + Aug 6 egress arch A, inc 1–10).** The history now; remaining open Finding 30 (rollback asserted, never rehearsed) and the health/efficiency residue are carried forward to the post-cutover plan above.
- [Polling Email Ingestion v2](polling-email-ingestion-v2.md) — **built and
  merged (#231–#235), awaiting production cutover.** Durable polling is now the
  only ingestion path; the legacy `email_fetch` poller, APScheduler job and
  implementation flag are gone. See its "Production cutover runbook" and "Open
  items after cutover" sections — production Outlook has been suppressed by a
  stuck timer row since 2026-07-31 with ~456 messages outstanding. Ordered cutover now lives in [Cutover Verification](cutover-verification-20260807.md); do not use this file's duplicated runbook section.
- [OAuth reconnect catch-up](oauth-reconnect-catch-up.md) — **backend delivered
  (#236–#239 + review-fix migration) and UI projection delivered on web, iOS,
  and Android.** Remaining: live invalidation wiring (via `live-ui-updates.md`),
  reviewed legacy production repair, staging fault injection, and production
  rollout.
- [Egress and Work Scheduling](egress-and-work-scheduling.md) — **built and merged (egress arch A, 1.5 M → ~3k RPCs/day).** Busy-wait removed via single scheduler + drain-then-sleep + in-process nudge; duplicate email owner and parked photo polls removed; egress meter + `/health/egress` shipped. Remaining soft spots (dual idle model, 5 s floor invisibility, dead `num_workers`) carried forward to the post-cutover plan.
- [Cutover Verification](cutover-verification-20260807.md) — **verified locally,
  not deployed.** Ordered checklist (migrations → code → flag last); the sole
  ordered gate — the two other duplicated runbook sections now point here.
  **The gap has grown:** its line 28 records prod at code `a50e1e4e` / schema
  `20260803000002`; `main` is now **96 commits and 21 migrations** ahead. Its
  line 3 also states prod must stay `ENABLE_BACKGROUND_PROCESSING=false`, while
  `.env.production:31` says `true` — reconcile before cutover. Execute via
  [foundation-integrity.md](foundation-integrity.md) F7–F8, not directly.
- [Direct-PG completion and live-UI hardening](direct-pg-completion-and-live-ui-hardening.md)
  — **implemented (C1–C9: #279–#286 + 0654d4fe).** Remediation of the Aug 6–9
  batch: the asyncpg session-pooler pool is mandatory at startup, the whole
  worker coordination surface runs over it with the PostgREST twins deleted,
  the LISTEN/NOTIFY WorkListener is live, executor concurrency is real on all
  four paths, the dead code/config is purged, all three clients refresh
  realtime auth / catch up / rejoin, Broadcast fan-out collapses to one
  message per transaction, and the R5 schema gate compares versions instead of
  counts. **Six defects found reviewing this batch are open** — see
  [foundation-integrity.md](foundation-integrity.md) §2 (D1–D6). Notably the R5
  gate still cannot fail: it greps all 14-digit versions out of
  `supabase migration list`, which includes the *local* column, so a local-only
  migration reads as applied (D2).
- [Live UI updates](live-ui-updates.md) — **implemented — web #270, iOS #271,
  Android #272**, hardened by C6 #284 (auth refresh, lifecycle catch-up,
  terminal-channel rejoin) and C7 #285 (per-transaction fan-out collapse).
  **Open:** the web rejoin backoff never advances past 1 s because
  `rejoinAttempts` is re-declared by each `start()` call, so an unauthorized
  private channel retries at 1 Hz forever; iOS and Android are correct. See
  [foundation-integrity.md](foundation-integrity.md) D1.
- [Photo surface removal](photo-surface-removal.md) — **implemented in #201 (2026-07-13).** Connect surfaces removed; photo-source rendering retained (see spec for restoration).
- [Review action contrast, sizing and grouping](review-action-contrast-and-sizing.md)
  — **implemented in #273 (2026-08-09).** One solid AAA peer-action construction per theme, intrinsic row never stacks.
- [Cross-platform Review layout and action accessibility](cross-platform-review-accessibility.md)
  — **implemented**, except canonical Android screenshots, which are blocked by
  a repeatable Pixel_8 emulator crash after APK install. Decisions 5, 8 and 11
  are superseded by the contrast/sizing spec above.
- [OneDrive photo ingestion](onedrive-photo-ingestion.md) — **parked
  (2026-07-13)** on cost/value. Do not re-propose without new information.

## What belongs here

- **Specs / implementation plans** — a detailed, step-by-step design for a feature
  that hasn't been built yet (or is being built). Written to be handed to a developer
  who then implements it. Concrete: file paths, function signatures, SQL, edge cases.

## What does NOT belong here

- **Reference docs** (how a shipped feature works today) go in `docs/` — e.g.
  `docs/gmail-integration.md`, `docs/database-schema.md`.
- **Product requirements / architecture** live in the root `PRD_ARCH.md`.

## Lifecycle

1. Write the spec here and get it reviewed.
2. Implement it (following the worktree + PR workflow in `CLAUDE.md`).
3. Once shipped, fold the durable "how it works" parts into the relevant `docs/`
   reference file and update `docs/database-schema.md` / `CLAUDE.md` as needed.
   The spec can then be marked **Implemented** (keep it for history) rather than
   duplicating reference docs.

## Naming

`docs/specs/<feature-slug>.md` — e.g. `outlook-email-support.md`.
