# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## MANDATORY: Bash Command Rules

- **Always `cd` to the worktree/project directory first** in a separate Bash call, then run commands with relative paths. Do NOT use absolute paths to files/directories.
- **Never use `cd` as part of a command** (e.g., `cd foo && make`). Change directory in a separate Bash call first.
- **Never chain unrelated commands with `&&`.** Run each command as a separate Bash tool call.
- All three rules are required — violating them breaks Claude Code's permission system.

---

## Project Overview

**Selko** is an AI-powered assistant that automates personal organization by analyzing digital inputs (emails; photo-library ingestion is parked) to manage schedules, to-do lists, and digital filing systems. See `PRD_ARCH.md` for complete product requirements and architecture.

---

## MANDATORY: Discovery Before Implementation

Every non-trivial task starts with read-only research and discovery in the main
repository. Diagnose or reproduce the issue, identify the likely root cause,
and form a concrete increment plan before creating a branch/worktree, editing
files, claiming review comments, or making other implementation writes.

- **Worktree creation marks the start of an implementation increment.** Do not
  create one merely to investigate.
- A request to **fix, implement, or change** something authorizes proceeding
  once the issue and increment plan are sufficiently understood; a ceremonial
  approval pause is not required.
- If the user primarily asks questions, requests investigation/discovery, or
  raises several uncertain symptoms, present the findings and proposed
  increment first, then wait for them to choose whether to implement it.
- Simple, low-risk changes with an obvious cause may proceed after a brief
  confirmation in the existing code. Use judgment; the goal is understanding
  before mutation, not process for its own sake.
- Run the late-review audit in Definition of Done step 0 only when a **source
  code increment** actually begins, not during discovery or a docs/config-only
  increment. Never claim or absorb PR review comments into a docs/config-only
  increment; leave them unclaimed for the next source code increment.

---

## MANDATORY: Worktree Workflow

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Source code (backend/, frontend/src/, ios/, android/, cli/)           │
│    → MUST use worktree + feature branch + PR                           │
│                                                                         │
│  Config files (.env, docs/, CLAUDE.md, scripts/, supabase/)            │
│    → CAN edit directly in main repo                                    │
└─────────────────────────────────────────────────────────────────────────┘
```

**Why:** Multiple AI agents work simultaneously. Worktrees isolate each task. PRs ensure CI runs before merging.

### Naming

| Type | Branch | Worktree |
|------|--------|----------|
| Feature | `feat/add-login` | `selko-feat-add-login` |
| Bugfix | `fix/api-timeout` | `selko-fix-api-timeout` |

Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`

### Setup & Usage

See `docs/parallel-agents.md` for the full pre-work checklist (sync, create worktree, copy env files, install deps).

> **CRITICAL:** After setup, your working directory MUST be the worktree (`~/Development/selko-<type>-<task>/`). All commands run from there. If a Bash command is rejected, you're probably in the wrong directory — verify with `pwd`.

### Enforcement

A Claude Code hook **blocks source code edits** in the main repo. You'll see:
```
BLOCKED: Cannot edit source code in the main repository.
```

---

## Definition of Done

**The DoD scales to what you changed. Run only what your change actually touches — nothing more.** A backend-only change never runs web, iOS, or Android tests or screenshots.

### 0. Check for unaddressed PR review comments (source code increments only)

Review comments often land **after** a PR has already been squash-merged (async reviewers, bots, ultrareview). At the start of each work increment:

**Skip this entire step for docs/config-only increments.** Do not inspect,
claim, or fix unrelated PR comments while doing documentation or configuration
work. Run it only when the current increment will edit source code.

1. `gh pr list --state merged --limit 10` — check the last 10 merged PRs.
2. For each, check for review comments that haven't been addressed yet (`gh pr view <number> --comments` or `gh api repos/<owner>/<repo>/pulls/<number>/comments`). Skip comments already marked fixed/claimed by a prior increment.
3. **Claim** any unclaimed, unaddressed comment by posting a reply that you'll fix it, so parallel agents don't duplicate the work.
4. **Fix it** as part of the current increment (same worktree/branch as whatever else you're doing, or its own small PR if unrelated to the current task).
5. **Close the loop** — post a follow-up comment on the original PR explaining how it was fixed (link the commit/PR that fixed it).

This keeps stale review feedback from silently rotting once a PR is merged and out of sight.

## MANDATORY: Verification tiers

CI is not a tier. It may never run. Both tiers below run from your machine.

**Tier 1 — local, before the PR merges.** `./scripts/verify.sh backend`.
Real Postgres via `supabase start`, all migrations applied, unit + integration
tests. This is the merge gate.

**Tier 2 — staging, immediately after the PR merges.** `./scripts/verify.sh staging`.
Real Supavisor pooler, real Render, real OAuth, real Realtime, real egress.

Tier 2 is not optional and not deferrable, because Tier 1 *cannot* reach what
Tier 2 covers:

- Local Supabase has **no Supavisor**. `.env` points at port 54322, direct
  Postgres. Every session-pooler property — LISTEN/NOTIFY survival, host
  resolution, idle-timeout behaviour — is unreachable locally by construction.
- A missing environment variable is invisible locally and invisible in a diff.
  `SUPABASE_DB_URL` was absent from `.env.test` and `.env.production` while
  `ENABLE_BACKGROUND_PROCESSING=true`; every test passed and the deploy would
  have hard-failed at startup.
- Egress, memory ceilings and token expiry do not exist on a laptop.

**A red Tier 2 run is the top-priority next increment**, ahead of new feature
work. Fix forward. Never let a second increment merge on top of a red staging.
An explicit user instruction to deploy to production after the Tier 2 gap has
been disclosed is an operator waiver for that deployment: report the waiver,
then proceed without another staging detour or approval loop. The waiver does
not authorize unrelated production-data mutations.

### 1. Scope your change

| You changed | Required before merge (Tier 1) | Required after merge (Tier 2) |
|-------------|-------------------------------|-------------------------------|
| `backend/**`, `cli/**` | `./scripts/verify.sh backend` — unit **+** integration against local Supabase | `./scripts/verify.sh staging` |
| `supabase/**` (schema/migrations) | `./scripts/verify.sh backend` — the integration run is what proves the migration executes | `./scripts/verify.sh staging` — **required**, migrations must reach staging before prod |
| `frontend/src/**` | Frontend unit tests + `npm run check` + **web** screenshots |
| `ios/**` | iOS tests + **iOS** screenshots |
| `android/**` | Android tests + **Android** screenshots |
| `docs/`, `*.md`, `.env*`, `scripts/`, `.claude/`, config only | Nothing to test — commit & push |

- **Only the platform you edited counts.** Editing `backend/` requires no web/iOS/Android tests or screenshots. Editing one frontend requires nothing from the others.
- **Bug fixes MUST include a regression test** in the module you fixed.
- **Production LLM failures MUST also become anonymized regression eval fixtures**
  under `backend/tests/eval/fixtures/`, with hand-written expected output. Run the
  specific fixture before shipping; if the prompt changes, run the broader eval
  suite required by `docs/evals-process.md` to check for regressions.
- **Screenshots** only for the platform whose UI you changed (see "Screenshot Updates"). Skip for backend/docs/config.
- **Every new table in a migration MUST include `ENABLE ROW LEVEL SECURITY` in
  the same migration.** `emails_body_html_backup` reached production holding
  email bodies with RLS off because a spec said "create a backup table" and
  nobody asked whether it needed securing (#277).
- **An increment is not implemented until its call sites are wired.** Do not
  mark a spec increment done, and do not write "next PR wires the call sites",
  when the new code has no callers. Direct-pg increments 3–5 shipped this way:
  `asyncpg` was never installed, `pg_pool` was never passed to any worker, and
  `WorkListener.start()` was a stub that reported healthy — all with a green
  test suite. If you add a code path behind a flag or an injected dependency,
  add a test that asserts the dependency actually reaches the call.
- **Unreachable code fails the build.** A new module under `backend/selko/`
  must be transitively importable from `selko.api` or `selko.worker_app`
  (`backend/tests/test_reachability.py`). This rule exists because the call-site
  rule above was stated three times and broken three times: direct-pg Inc3–5,
  and then `workers/event_resolution.py` (#307), which merged as "fenced
  per-user event resolution" with zero call sites and a green gate. Mocks cannot
  notice a module nobody imports; an import graph can.
- **Never narrow a CHECK constraint without checking its writers.** Enumerated
  text domains are pinned in
  `backend/tests/integration/test_schema_contract.py::EXPECTED_CHECK_DOMAINS`.
  R2 dropped `'skipped'` from `emails.processing_status` and R4 dropped
  `'syncing'/'synced'/'sync_failed'` from `events.status`; both writers are
  Python, so no `SECURITY DEFINER` contract saw them, and both needed an
  emergency repair migration the same night (#312).
- **SQL that has never been executed has not been tested.** A migration is not
  done because it applies cleanly. It is done when a test has called the
  function it defines or fired the trigger it creates, against a real database.
  `20260809000001` (inserted into `attachments` columns that have never existed)
  and `20260809000003` (referenced `NEW.sync_status` on `events`, breaking every
  UPDATE) both applied cleanly, passed the full mocked suite, and were broken on
  their first real call.
- **Configuration is part of the change.** If your increment adds a required
  environment variable, it is not done until that variable is set in every
  environment that runs the code. A correct diff plus a missing value is an
  outage. Verify on staging (Tier 2), not by reading `.env.example`.

### 2. Ship it

- [ ] Source code → feature branch in a worktree. Config/docs → edit `main` directly (`git push origin main`).
- [ ] The scoped tests above pass locally — **local tests are the gate, not CI**
- [ ] Commit (conventional format), push, `gh pr create`
- [ ] `./scripts/merge-and-cleanup.sh <pr_number>` — squash-merges and does full cleanup: deletes remote + local branch, fast-forwards `main`, removes the worktree, prunes. **Does not wait on CI.**
- [ ] If your change ships to a server (`backend`/`supabase`/`frontend`), **the last sentence of your final report MUST be: "Should I deploy this to production?"** Never deploy to prod without an explicit yes. Once the user says yes, deploy; a previously disclosed staging failure does not require another confirmation. Apply production migrations locally, then dispatch `test.yml` with `staging_action=none` and `deploy_production=true`; that explicit job owns the secret Render hooks.

See `docs/parallel-agents.md` for the full workflow. See `docs/ci-cd.md` for CI architecture details.

### CI Ownership — never gate, never funded

**We will never top up GitHub Actions minutes. Never trust CI to run.**

Verification is two tiers, both run from your machine: Tier 1 (local, pre-merge)
and Tier 2 (staging, post-merge). See "Verification tiers" above. CI is a bonus.
If it runs and fails, fix forward; if it never runs, that is expected.

The `deploy-staging` and `integration-tests-staging` jobs in `test.yml` require
Actions minutes and therefore do not run. `./scripts/verify.sh staging` is what
actually deploys and verifies staging. Do not read those jobs as a live path.

If CI does run and fails, fix forward:
1. **Diagnose** — `gh run view <id> --log-failed`
2. **Google OAuth expired** (`RefreshError: invalid_grant`): run `uv run python -m cli.cli_seed_tokens --sync --provider gmail` (copies working dev↔staging token to stale side); only if both are stale, re-auth one side then re-run `--sync`, then re-trigger *only if minutes exist — otherwise ignore and proceed locally*.
3. **Code issue** — follow-up PR.

Production migrations are pushed locally after `./scripts/assert-schema-code-compat.sh` (R5 gate). Production code is deployed with `gh workflow run test.yml -f staging_action=none -f deploy_production=true`, because the secret Render hooks live in that explicit, dependency-free job. Do not wait for unrelated test jobs after the production deploy job succeeds. `./scripts/poll-and-merge.sh` is deprecated.

### Worktree Cleanup Rules

`merge-and-cleanup.sh` cleans up for you. For any manual removal the safety rule stands:

**NEVER force-remove a worktree (`--force`) without first inspecting uncommitted work.**
1. `cd` to the worktree, run `git status`
2. Uncommitted/untracked files? **Review them manually** — they may hold real work or artifacts
3. Use `git worktree remove` (no `--force`). If it refuses, that's the safety mechanism — inspect first
4. `git worktree remove --force` destroys uncommitted work with no recovery — treat it like `rm -rf`

---

## Essential Commands

| Command | Purpose |
|---------|---------|
| `supabase start` / `supabase db reset` | Local Supabase |
| `uv run pytest backend/tests/ -v` | Backend tests |
| `npm run test:unit -- --reporter=json --outputFile=test-results.json` | Frontend tests (from `frontend/`) |
| `uv run python -m selko.api` | Start FastAPI server |
| `./gradlew testDebugUnitTest` | Android tests (from `android/`) |
| `xcodebuild test -project ios/iOS.xcodeproj -scheme iOS -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -resultBundlePath ios/TestResults.xcresult` | iOS tests |

> **iOS gotcha:** Scheme is `iOS` (not "Selko"). Remove old `ios/TestResults.xcresult` before re-running.

See `docs/testing-guide.md` for the full test guide and `docs/manual-email-to-calendar-walkthrough.md` for CLI tools and end-to-end walkthrough.

---

## Platform Preferences

### iOS — Pure SwiftUI
- **Never import UIKit** unless absolutely unavoidable (e.g., `UIApplication` for opening URLs)
- For adaptive light/dark colors: use **asset catalog color sets**, not `UIColor { traits in ... }`
- Brand font is bundled Figtree (declared in `Info.plist` under `UIAppFonts`); use `Font.custom(_:size:relativeTo:)` so Dynamic Type scaling keeps working
- Project is `ios/iOS.xcodeproj`, scheme is `iOS` (not "Selko" — common mistake)
- Uses `PBXFileSystemSynchronizedRootGroup` — Swift files in `Selko/` are auto-discovered, no `project.pbxproj` edits needed for new files
- `ASSETCATALOG_COMPILER_GENERATE_SWIFT_ASSET_SYMBOL_EXTENSIONS = YES` — color sets (e.g., `SelkoSuccess.colorset`) auto-generate `Color.selkoSuccess` extensions. Do NOT create manual Color extensions that duplicate asset catalog names (causes "invalid redeclaration")
- Available simulators: iPhone 17 Pro, iPhone 17, iPhone Air (no iPhone 16)
- Must `rm -rf ios/TestResults.xcresult` before re-running tests

### Android — Pure Jetpack Compose
- **No legacy View system** — no XML layouts, no `android.widget` imports
- Material3 (`androidx.compose.material3`) exclusively
- Koin for dependency injection (`koinViewModel()`)
- `dynamicColor = false` — brand colors always override Material You
- Font resources must be **lowercase with underscores** (e.g., `inter_regular.ttf` in `res/font/`)
- For icons beyond basics, add `material-icons-extended` dependency

### Web — SvelteKit + DaisyUI
- SvelteKit 2 with Svelte 5 (runes syntax)
- DaisyUI semantic colors only — never use raw Tailwind colors (`text-blue-500` etc.)
- Custom themes `selko-light` and `selko-dark` in `tailwind.config.js`
- `svelte-check` CI is strict about types — use JSDoc annotations where needed
- `design/tokens.json` is the canonical cross-platform control contract. Use
  semantic control primitives; static statuses are plain icon/text, NEW is
  neutral, Included/Excluded is a labeled switch, and all targets are ≥44.

---

## UI Testing & Visual Verification

**Standard workflow:** Use `./scripts/capture-all-screenshots.sh <platform>` to capture screenshots, then review them for visual correctness. The script handles seeding, building, and capturing automatically.

**MCP tools** (Playwright, XcodeBuildMCP, mobile-mcp) are for **manual debugging only** — e.g., clicking a new button, testing a specific interaction, or investigating a visual bug that screenshots alone can't diagnose. Do NOT use MCP tools or `/verify-*` slash commands as a standard verification step.

**Key warnings:** Screenshots must be **≤ 2000 px** in both dimensions (resize with `sips --resampleHeight 1920`). Never use `fullPage: true` in Playwright.

**Full details:** `docs/ui-testing-guide.md`

---

## Screenshot Updates (DoD)

**When to update:** Only when UI-visible code changed. Skip for backend-only, docs, or config changes.

**One command — do NOT manually seed data, run individual scripts, or use MCP tools:**

| Changed files | Command |
|---------------|---------|
| `frontend/src/` | `./scripts/capture-all-screenshots.sh web` |
| `ios/` | `./scripts/capture-all-screenshots.sh ios` |
| `android/` | `./scripts/capture-all-screenshots.sh android` |
| Shared code (Supabase schema, seed data) affecting all UIs | `./scripts/capture-all-screenshots.sh` |

The unified script handles seeding, booting, building, testing, pulling, and resizing. See `docs/screenshot-guide.md` for details.

**Pre-warming:** Boot the simulator/emulator early so startup overlaps with coding time:

```bash
# iOS
xcrun simctl boot "iPhone 17 Pro" 2>/dev/null || true
# Android (if no emulator running)
adb devices | grep -q emulator || (emulator -avd Pixel_8 -no-audio &)
```

**Keep running:** Do NOT close or terminate simulators/emulators between testing and screenshots — they're reused for both.

---

## Architecture Principles

- **Direct Supabase Access:** Frontends query Supabase directly. Python API only for operations requiring secrets (OAuth, Gmail sync, LLM processing).
- **Two transports, no fallback between them.** RLS-scoped client and API traffic uses PostgREST with the *user's* JWT. Trusted-worker coordination (claim/heartbeat/complete/lease) uses asyncpg over the Supavisor **session pooler, port 5432** — PostgREST costs ~1,690 B/call of pure envelope for a service-role caller that bypasses RLS anyway. **An operation has exactly one implementation.** Never write `if pg_pool is not None: ... else: ...`; never add a `_via_pool` twin. This is enforced by the guard tests in `backend/tests/test_workers.py` (`test_no_worker_module_retains_a_postgrest_fallback`, `test_no_compat_shims_in_workers`) and the wiring test `test_worker_pool_claims_over_the_pool`.
- **Reliable email ingestion:** Gmail uses paginated initial scans plus History cursors; Outlook resolves immutable well-known folder IDs before traversing and uses one delta cursor per included folder. Eligible provider folders are scannable but hidden from Settings, permanent/hidden trees are excluded, and folder preferences use the restricted `set_email_folder_preference` RPC. Email outcomes/reprocessing are exposed through the paginated History workflow.
- **Calendar component capture:** Email acquisition parses every inline/attachment Gmail `text/calendar` part and Outlook meeting metadata into service-only `email_calendar_components` through the single atomic `save_email_with_attachment_descriptors` RPC. Empty component payloads never erase an earlier parse.
- **Calendar identity matching:** `event_identity.py` canonicalizes content-free UID, provider-thread, join, and management hints. The resolution ladder applies authoritative UID/revision matching, exact join/time duplicates, and only two-signal supporting correlation before the local-day LLM fallback. Hints are written only by the fenced `commit_email_extraction` RPC, whose hint lookup set is fingerprinted and advisory-locked with the local-day band.
- **Pending-change integrity:** `event_change_proposals` is the authoritative owner of update/cancellation review state; `event_sources` retains only compatibility provenance mirrors during S3/S4. A deferred database constraint requires exactly one pending proposal for `events.status='pending_change'`. Apply, reject, reopen, and repair transitions use service-only proposal RPCs, and review clients fail closed when proposal details are unavailable.
- **Durable email polling:** the only email ingestion path. `IngestionRuntime` starts inside the FastAPI process (async monolith — no separate Render service) whenever `ENABLE_BACKGROUND_PROCESSING` is on, and owns leased provider discovery, durable identity acquisition, independent attachment retries, reconciliation, and safe health notifications. Single ownership comes from database leases (`FOR UPDATE SKIP LOCKED` + lease expiry), not process topology. There is no APScheduler and no `email_fetch` task — the coordinator owns its own cadence. New integrations become pollable via the `integrations_ensure_email_sync_state` trigger; `request_email_sync_now` asks for a prompt poll. `selko.worker_app` runs the identical task set standalone for staging drills.
- **Durable email work state:** a `pending` email is invariant-guaranteed claimable (`emails_pending_is_claimable_check`: `attempts < max_attempts`, no owner, no unexpired lock). `claim_unprocessed_email` opportunistically reclaims one expired `processing` lease per call before claiming fresh work, so a crashed worker's row recovers on the next claim, never on a restart or a periodic sweep. `fail_email_processing` is the single fenced retry-or-terminate RPC; a stale `(worker_id, lock_generation)` is a no-op. Provider discovery leases (`email_sync_state`/`email_sync_runs`) are generation-fenced end to end via claim → heartbeat → complete/fail, and at most one `running` run exists per integration by a partial unique index. `health_work_state` is the single counted health RPC behind both `/health` and `/health/ingestion`; see `docs/specs/state-ownership-and-deterministic-recovery.md` S1–S3 for the current plan (S4–S5 remain open; S2 adds worker-owned `calendar_work_items`, S3 adds first-class `event_change_proposals`).
- **Single-owner calendar sync:** Approval only queues an event by setting `status='approved'`. Automatic cancellation queues a matched provider event as `status='cancel_queued'` with `calendar_sync_action='cancel'`; background workers are the sole Google Calendar writers for both upserts and cancellations. Explicit `/events/{id}/sync` requests idempotently observe or requeue worker-owned sync state.
- **Reviewed repair tooling:** `scripts/repair_review_queue_integrity.py` is dry-run by default; production mutation requires an absolute manifest, exact confirmed user, `--environment production`, `--apply`, and a redacted reverse-operation artifact. It uses the service-only `event_repair_audit` table and `queue_event_cancellation` transition; never run production apply without explicit approval.
- **Reconnect recovery:** Google Calendar reauthorization atomically creates a durable `integration_recoveries` generation (via `complete_integration_reauthorization`) that requeues OAuth-blocked events; email resumes from provider cursors via the `integrations_ensure_email_sync_state` trigger with no recovery record. Auth failures are classified in `events.sync_failure_code` (`oauth_required`/`oauth_scope_required`) and never trip the global provider circuit breaker. The ConnectionRecovery card on web/iOS/Android shows catch-up progress (`integration_recoveries` is RLS-readable by the owner).
- **Outbound traffic is metered:** `selko.services.egress` attributes every outbound byte to a destination (`supabase`/`gmail`/`graph`) and a bounded operation template, exposed at `/health/egress` and logged every `EGRESS_LOG_INTERVAL_SECONDS`. Supabase traffic is captured by an httpx response hook on the single shared service client in `get_service_client`, so it cannot be bypassed by a new call site — do not construct a second service client without that hook. This exists because a platform bandwidth alert reports a total with no attribution, which cannot tell constant polling apart from real provider downloads. Idle loops must not exist. Work arrives by notification; the safety-net poll is a floor, not a schedule. Any new unconditional periodic database call must be justified in the PR body against the two rules above: work arrives by notification, and the safety-net poll is a floor rather than a schedule.
- **Fenced-resolution health:** `/health` exposes content-free, process-local resolution conflicts-per-hour, retry histogram, fenced-write count, conflict-exhaustion count, and pending-email age gauges. Event extraction writes are committed only through `commit_email_extraction`; direct event inserts in services/workers are guarded by AST tests. Google Photos ingestion remains parked.
- **End-to-End First:** Complete full journeys before expanding scope. First journey: Email → Calendar Event.
- **LLM-Centric AI:** All intelligence uses multimodal LLMs (multi-provider registry; default primary `gemini-3.5-flash-lite`, fallback `qwen3.7-flash`).
- **YAGNI:** Add complexity only when measured need exists.

**Details:** `PRD_ARCH.md`

---

## Self-Maintenance Rule

**This CLAUDE.md is the single source of truth for all AI agents.** After major changes (new tables, endpoints, routes, CLI commands, docs, env vars, or architectural shifts), update this file. Keep it concise — link to detailed docs rather than duplicating content. Every linked doc must exist; remove stale links.

---

## Environment & Config

| File | Purpose |
|------|---------|
| `.env` | Local development (Docker) |
| `.env.test` | Staging environment |
| `.env.production` | Production environment |
| `.env.example` | Template for setup |

**Supabase Instances:** Local (`localhost:54321`), Staging (`lxmysergoeaegxlyfzwk`), Production (`khahcozfbnpykspvatrg`)

Microsoft Outlook OAuth uses `MICROSOFT_CLIENT_ID` and `MICROSOFT_CLIENT_SECRET`
from a Microsoft Entra app registration.

### MANDATORY: Environment separation

**Never move production credentials or data into staging or development, and
never seed burner tokens into production.** Production holds real users' OAuth
refresh tokens; a lower-trust environment is a lower-trust environment.

- `cli_seed_tokens` is **development ↔ staging only**. Production is rejected at
  the argparse surface and inside `seed_tokens()` (CI imports the function
  directly, so the CLI layer alone is not enough). Do not reintroduce it.
- When a development or staging OAuth token dies, **do not ask the user to reauth** —
  check both dev and staging and copy the working token to the stale side:
  `uv run python -m cli.cli_seed_tokens --sync --provider gmail` (checks both
  envs, copies `development→staging` or `staging→development` whichever is
  working→stale; no-op if both fresh). If both are stale, re-auth one side
  then run `--sync` again. Also supports `--all-providers`.
- Reading production state for diagnosis is fine (status, expiry, row counts).
  Print no tokens and copy nothing.

---

## Reference Index

| Topic | Document | When to Read |
|-------|----------|--------------|
| **Email-to-Calendar walkthrough** | `docs/manual-email-to-calendar-walkthrough.md` | For end-to-end manual testing |
| **Worktree workflow** | `docs/parallel-agents.md` | Before any source code task |
| **Testing** | `docs/testing-guide.md` | Before running tests |
| **Database schema** | `docs/database-schema.md` | When working with data |
| **Frontend queries** | `docs/supabase-frontend-queries.md` | When building UI features |
| **API workflow** | `docs/api-workflow.md` | When working with Python API |
| **CI/CD** | `docs/ci-cd.md` | When troubleshooting CI |
| **Job queue** | `docs/job-queue.md` | When working with background jobs |
| **Gmail integration** | `docs/gmail-integration.md` | When working with email sync |
| **Microsoft Graph failure ledger** | `docs/microsoft-graph-failure-ledger.md` | Before changing Graph request/retry/resync behavior or after any production Graph failure |
| **OAuth reconnect catch-up** | `docs/specs/oauth-reconnect-catch-up.md` | When implementing automatic email/calendar recovery after OAuth reauthorization |
| **Cutover verification** | `docs/specs/cutover-verification-20260807.md` | The single ordered production cutover checklist (migrations → code → flag last). Execute it through foundation-integrity F7–F8, never directly |
| **Foundation integrity** | `docs/specs/foundation-integrity.md` | Read after the stub-rollback plan above. Builds a real execution gate (integration tests against local Postgres) because the mocked-only DoD gate is why broken SQL, unreachable code and a non-functional schema gate all shipped green. Carries the six open defects (D1–D6) from the C1–C9 review and the production cutover |
| **Stub rollback and gate repair** | `docs/specs/stub-rollback-and-gate-repair.md` | Gate-repair record for G1–G7; G1–G5 are merged, while G6/G7 and the production checks remain tracked. Read before changing the execution gates. |
| **Parallel extraction, fenced commit** | `docs/specs/parallel-extraction-fenced-commit.md` | Before touching worker concurrency, `save_extracted_events`, or how extracted events are persisted. Extraction stays parallel; the commit is fenced on the candidate band it was computed against. Replaces review-queue-integrity R2 |
| **Calendar identity and cancellation** | `docs/specs/calendar-identity-and-cancellation.md` | Before touching iCalendar parsing, event identity/dedup, or cancellation. Replaces review-queue-integrity R3–R4 |
| **Review queue integrity** | `docs/specs/review-queue-integrity.md` | Normative requirements for web Review (§5), identity (§7), cancellation (§8) and the production repair (§9). Decisions 6–7 stand; **§6's fenced-lane mechanism is superseded** — see parallel-extraction-fenced-commit |
| **LLM integration** | `docs/llm-integration.md` | When working with LLM features |
| **Architecture** | `PRD_ARCH.md` | For product requirements and architecture |
| **UI user journeys** | `docs/ui/01-user-journeys.md` | When planning frontend work or understanding user flows |
| **Screen specifications** | `docs/ui/02-screen-specs.md` | When implementing any web screen |
| **UI patterns & components** | `docs/ui/03-patterns-and-components.md` | Before building any UI component, to follow conventions |
| **Brand guide** | `docs/brand-guide.md` | When implementing any UI, choosing colors, fonts, or terminology |
| **UI testing** | `docs/ui-testing-guide.md` | When writing E2E tests or using MCP visual verification |
| **Screenshot capture** | `docs/screenshot-guide.md` | When capturing product screenshots across web, iOS, and Android |
| **LLM eval system** | `backend/tests/eval/README.md` | When working with LLM evaluation or benchmarking |
| **Evals process** | `docs/evals-process.md` | When running evals, interpreting results, or iterating on prompts |
| **Implementation specs** | `docs/specs/` | When planning or implementing a new feature (detailed build plans; see `docs/specs/README.md`) |

---

## License

This is **proprietary, commercially copyrighted software** - NOT open source. Copyright (c) 2026 Toni Melisma. See LICENSE file.
