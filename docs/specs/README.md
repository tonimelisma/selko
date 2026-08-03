# Specs

Implementation specifications for planned or in-progress features.

## Active plans

Status as of 2026-08-03.

- [Ingestion & recovery hardening](ingestion-recovery-hardening.md) — **planned,
  not started.** Top-up plan from the review of #229–#240. Increments 1–4 are
  P0 and gate the production cutover below: a substring error classifier that
  permanently dead-letters Gmail mail, unsupervised ingestion loops that die
  silently on one transient DB error, a race that lets the LLM claim an email
  before its attachment rows exist, and a red `main`. Increments 5–10 cover
  observability, provider-call efficiency, recovery-progress correctness,
  cleanups and the durability drills that have never been run.
- [Polling Email Ingestion v2](polling-email-ingestion-v2.md) — **built and
  merged (#231–#235), awaiting production cutover.** Durable polling is now the
  only ingestion path; the legacy `email_fetch` poller, APScheduler job and
  implementation flag are gone. See its "Production cutover runbook" and "Open
  items after cutover" sections — production Outlook has been suppressed by a
  stuck timer row since 2026-07-31 with ~456 messages outstanding.
- [OAuth reconnect catch-up](oauth-reconnect-catch-up.md) — **backend delivered
  (#236–#239 + review-fix migration) and UI projection delivered on web, iOS,
  and Android.** Remaining: live invalidation wiring (via `live-ui-updates.md`),
  reviewed legacy production repair, staging fault injection, and production
  rollout.
- [Live UI updates](live-ui-updates.md) — **planned, not started.** Private
  per-user Broadcast invalidations with lifecycle-safe catch-up across web, iOS,
  and Android.
- [Photo surface removal](photo-surface-removal.md) — **ready to implement, not
  started.** Deliberately deferred while photo ingestion is parked.
- [Cross-platform Review layout and action accessibility](cross-platform-review-accessibility.md)
  — **implemented**, except canonical Android screenshots, which are blocked by
  a repeatable Pixel_8 emulator crash after APK install.
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
