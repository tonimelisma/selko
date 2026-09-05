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

## MANDATORY: The verification process

This is the whole loop. Do not invent a different one per task.

1. **Run the lanes. Never hand-roll verification.**
   `./scripts/verify-lanes.py --gate prod` before any production deploy.
   `--gate mobile` for iOS/Android. Lanes cache on input content, so a re-run
   after a fix executes only what changed.
2. **Read the printed table, not your memory of what you ran.** It states each
   lane's status, duration, and whether it executed or was reused.
3. **Red or BLOCKED means stop.** Fix, re-run, repeat. A lane that cannot run
   is red — never "probably fine".
4. **Report the table plus a recommendation.** Never ask "should I deploy?"
   with no evidence attached.
5. **After deploying, fill in `docs/deploy-log/<date>-<sha>.md`.** T+0 and T+15m
   before you report done; T+24h next day.

### Checking that production is actually healthy

```bash
./scripts/check-production-health.sh          # production (api.selkoapp.com)
./scripts/check-production-health.sh <url>    # any deployment
```

It runs the invariants in `scripts/assert-health.sh` — the standard list:

| Surface | Must hold |
|---|---|
| `work-state` | `items_dead_letter`, `attachments_dead_letter`, `stale_processing_emails`, `unclaimable_pending` are **all zero**, whatever the worker posture. `failed_emails` is *not* asserted — terminal failures are permanent history, and requiring them to be zero made this check unsatisfiable forever after the first one |
| `ingestion` | status ok, background processing on, every task alive, pg listener connected |
| `root` | publishes a 40-character build SHA (which build answered), and `requests.server_errors_per_hour` is **zero** — a deployment answering 5xx is not healthy, whatever its queues look like |
| `egress` | worker transport is asyncpg |

Those assertions existed for months but were wired only to
staging — `verify-staging.sh` and CI called them and nothing else. Pointed at
production for the first time, they immediately went red — and the red was
partly the check's own fault: the count conflated terminal failures (permanent,
expected) with stuck pending rows (actionable). `20260901000001` split them.
**A check that never runs against the environment that matters is not a check**,
and one that cannot return to green is ignored just as fast as one that cannot
go red.

**Production is `https://api.selkoapp.com`.** The `.onrender.com` host 404s and
the primary domain appears only in Render's deploy logs. `selko.onrender.com` is
*staging*, on the free plan, so it spins down and reports degraded — its state
has already been mistaken for production's twice.

### Long-running commands: one at a time, stop what you start

These rules exist because all three were broken in one session: a `uvicorn`
left running for 1h47m, two `xcodebuild` runs driving the same simulator
simultaneously, and an exit code read from `echo` instead of the command.

- **A background task is finished when the harness reports it exited** — not
  when its output looks complete. `xcodebuild` prints test results and then
  stays alive for up to 600s collecting simulator diagnostics.
- **Never start a command that shares a resource** (the simulator, port 8000,
  the local database) **while another holds it.** Check with
  `ps -eo pid,etime,command | grep xcodebuild`. `verify-lanes.py` enforces this
  with a per-lane lock and reports `BUSY` rather than running anyway.
- **Stop every process you start**, in the same session, as soon as its
  consumer finishes. Never kill a process you did not start — it may be the
  operator's.
- **Never end a command with `; echo "exit=$?"`.** That reports `echo`'s status.
  Let the command's own exit code propagate.
- **Prefer a declared precondition over a hand-started dependency.** If a lane
  needs a service, declare it in `scripts/lanes.toml` under `[[lanes.X.requires]]`
  so it fails closed with a remedy instead of passing only on the machine where
  someone happened to start it.

### Never trust a signal that cannot fail

Every serious defect in this codebase came from a green signal that meant less
than it looked like. A `/health` probe satisfied by *any* server on the port. A
UI test whose assertions sat behind `guard ... else { return }`. An initializer
parameter accepted and discarded. Before trusting a gate, ask: **if this were
broken right now, would this check actually go red?** If not, it is decoration.

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
  R2 dropped `'skipped'` from `emails.processing_status`; event delivery is
  now derived from `events.review_status` and `calendar_work_items`, so there
  is no legacy `events.status` domain or writer to keep in sync.
- **SQL that has never been executed has not been tested.** A migration is not
  done because it applies cleanly. It is done when a test has called the
  function it defines or fired the trigger it creates, against a real database.
  `20260809000001` (inserted into `attachments` columns that have never existed)
  and `20260809000003` (referenced `NEW.sync_status` on `events`, breaking every
  UPDATE) both applied cleanly, passed the full mocked suite, and were broken on
  their first real call.
- **A client query string is schema, not text.** Frontend PostgREST `.select()`
  strings are pinned against the live database by
  `backend/tests/integration/test_schema_contract.py::test_frontend_select_columns_exist_in_the_live_schema`.
  The frontend unit tests stub `supabase.from` wholesale, so a select string is
  otherwise only ever asserted against itself and stays green after the column
  it names is dropped. That is how `event_sources.is_undone` survived
  `20260826000001` and made every History load answer 400 (#380) — PostgREST
  names embedded relations `<relation>_1`, so the error named a table that
  appears nowhere in the source. The regression also arrived by stale branch
  rather than by a bad edit: a squash-merge of a branch cut before its
  neighbour silently restores the lines that neighbour changed.
- **Configuration is part of the change.** If your increment adds a required
  environment variable, it is not done until that variable is set in every
  environment that runs the code. A correct diff plus a missing value is an
  outage. Verify on staging (Tier 2), not by reading `.env.example`.

### 1a. Pick verification by risk dimension, not just by file path

File paths decide *which lane runs*. They do not decide whether the change is
dangerous. Eight weeks of production-breaking commits, classified:

| Root cause | Examples | Local tests catch it? |
|---|---|---|
| Config / environment | #218 prod env overrides, #217 workers off by default, #151 auth redirect URLs | **No** — invisible in a diff and locally |
| Production data shape | #351 rehearsal vs real rows, #196 review incident | **No** — the local DB is empty or seeded |
| Elapsed time / runtime | #191 OOM (~2 MB/min), #235 Outlook token refresh mid-pass | **No** — needs hours of running |
| Observability gaps | #215 surface prod integration failures | **No** — you cannot test what is never reported |
| Tests hiding bugs | #232 "the production bugs it was hiding" | The tests *were* the problem |

Only the last row is code logic. Our verification is dense on the axis that
rarely breaks and thin on the three that do, which is why "lots of tests" and
"production broke again" are both true at once. Adding unit tests does not move
these numbers. Match the dimension instead:

| Dimension your change touches | Required beyond the lanes |
|---|---|
| A one-line config or env var | Verify the value **in the target environment**. A correct diff plus a missing value is an outage; `.env.example` proves nothing |
| Migration touching a populated table | `scripts/rehearse_cutover.py --faithful` against production row shapes. A migration that applies cleanly to an empty table has not been tested |
| Worker, loop, or long-running path | Watch RSS and `/health/egress` over hours, recorded in the deploy log. A laptop has no memory ceiling and no token expiry |
| New table | `ENABLE ROW LEVEL SECURITY` in the same migration |
| New code path behind a flag or injected dependency | A test asserting the dependency actually reaches the call site |
| Pure logic, no schema/config change | The lanes are sufficient |

**A 500-line refactor with no schema or config change is usually safer than a
one-line `.env` edit.** Scope verification to that reality.

### 1b. Run the lanes, don't hand-roll the verification

```bash
./scripts/verify-lanes.py --gate prod     # blocks a production deploy
./scripts/verify-lanes.py --gate mobile   # ships via app stores; never blocks prod
./scripts/verify-lanes.py --gate observe  # measures running production; blocks nothing
./scripts/verify-report.py                # what each lane costs and has caught
```

**`observe` is deliberately not a deploy gate.** It measures the *currently
deployed* production, so blocking a deploy on it deadlocks: a degraded
production makes the gate red, and the change that would heal it can never
ship. Run it after deploying — `docs/deploy-log/TEMPLATE.md` calls it at each
observation window.

Lanes are declared in `scripts/lanes.toml`. The runner fingerprints each lane's
declared inputs by **content**, so a lane that already passed for exactly those
inputs is reused rather than re-run: fix one lane, run again, and only that lane
executes. Results are keyed by fingerprint, so reverting an edit restores the
cached result instead of forcing a re-run.

Every lane execution appends to `.verify/ledger.jsonl` (duration, outcome,
executed-or-reused) and each run writes `.verify/runs/<id>.json`. That history is
what makes verification improvable: `verify-report.py` shows which lanes have
ever caught a real failure and what each costs, so a lane that has never fired
across many runs can be demoted on evidence rather than kept on faith.

**A lane that cannot run is RED, never skipped.** `schema-compat` reports failure
without `SUPABASE_ACCESS_TOKEN` and a linked project, because a local-only check
proves nothing. Silence is not success.

**`prod` and `mobile` are separate gates.** Production is backend + supabase +
frontend. iOS and Android ship through app stores. A red iOS suite has never been
a reason to hold a backend deploy, and treating it as one has cost hours.

### 2. Ship it

- [ ] Source code → feature branch in a worktree. Config/docs → edit `main` directly (`git push origin main`).
- [ ] The scoped tests above pass locally — **local tests are the gate, not CI**
- [ ] Commit (conventional format), push, `gh pr create`
- [ ] `./scripts/merge-and-cleanup.sh <pr_number>` — squash-merges and does full cleanup: deletes remote + local branch, fast-forwards `main`, removes the worktree, prunes. **Does not wait on CI.**
- [ ] **After any production deploy, open a `docs/deploy-log/<date>-<sha>.md` entry from `TEMPLATE.md` and fill the T+0 and T+15m rows before reporting done.** The T+24h row is filled the next day. Config, real-data and elapsed-time failures are only observable here — a deploy is not finished when it is applied, it is finished when it has been watched. Always fill in "which gate should have caught it"; that is what turns an incident into a permanent gate improvement instead of folklore.
- [ ] **Check CI on `main` and fix forward if it ran and failed** — `gh run list --branch main --limit 3`. Not a merge gate, but never left red. See "CI Ownership" below.
- [ ] If your change ships to a server (`backend`/`supabase`/`frontend`), **report the `--gate prod` lane table and state a recommendation**, then ask whether to deploy. A bare "Should I deploy this to production?" with no evidence attached asks the operator to adjudicate a question the lane table already answers. Never deploy to prod without an explicit yes. Once the user says yes, deploy; a previously disclosed staging failure does not require another confirmation. Apply production migrations locally, then dispatch `test.yml` with `staging_action=none` and `deploy_production=true`; that explicit job owns the secret Render hooks.

See `docs/parallel-agents.md` for the full workflow. See `docs/ci-cd.md` for CI architecture details.

### CI Ownership — never a gate, but never ignored

**We will never top up GitHub Actions minutes, and CI is never a merge gate.**
Verification is two tiers, both run from your machine: Tier 1 (local, pre-merge)
and Tier 2 (staging, post-merge). See "Verification tiers" above.

**But CI does run, and a red CI is never left red.** The previous version of
this section claimed `deploy-staging` and `integration-tests-staging` "require
Actions minutes and therefore do not run." That was false: those jobs have been
running on every push to `main`, and `deploy-staging` was failing on `main`
across three consecutive runs while this file said it could not execute. A
status nobody reads is worse than no status.

**MANDATORY — after every merge to `main`, check CI and fix forward.** This is
step 3 of "Ship it" and is not optional. Never leave `main` red.

```bash
gh run list --branch main --limit 3
```

If it failed:
1. **Diagnose** — `gh run view <id> --log-failed`
2. **Missing configuration** — the most common cause, and the one a diff cannot
   show. `gh secret list` shows what exists; a referenced secret that is not in
   that list expands to the empty string silently. Fix the workflow or tell the
   operator which secret to add — do not paper over it by disabling the check.
3. **Google OAuth expired** (`RefreshError: invalid_grant`): run `uv run python -m cli.cli_seed_tokens --sync --provider gmail` (copies working dev↔staging token to stale side); only if both are stale, re-auth one side then re-run `--sync`.
4. **Code issue** — follow-up PR.

**A CI job may never imply coverage it does not have.** If a job cannot run part
of its verification, it says so in its own output rather than passing quietly —
`deploy-staging` prints exactly what it did and did not verify. A green tick
that reads as more than it is has caused more damage here than a red one.

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
- **Event review integrity:** `event_change_proposals` is the authoritative owner of update/cancellation review state; `event_sources` retains provenance only. Pending proposals require `events.review_status='active'`; event `status` never represents the Changes lane. Apply, reject, reopen, and repair transitions use service-only proposal RPCs, and review clients fail closed when proposal details are unavailable. **Every extraction decision states an explicit `intent`** (`no_change`/`apply`/`review`/`record_only`) and, except for `record_only`, an explicit `fields.review_status`; `commit_email_extraction` raises rather than defaulting either. It used to derive auto-apply from `review_status='active'` — the same value a pending proposal requires — so an unstated decision silently applied the change and wrote to the user's calendar. Delivery follows `review_status`, never `intent`. A **declined event (`rejected`/`cancelled`) is terminal**: later emails still record provenance and identity hints, which is what keeps the match working and prevents a duplicate in the New lane, but never revive it (`docs/specs/review-queue-integrity.md` §8.2). `_enqueue_calendar_work` no longer promotes review status and refuses an upsert for a declined event.
- **Durable email polling:** the only email ingestion path. `IngestionRuntime` starts inside the FastAPI process (async monolith — no separate Render service) whenever `ENABLE_BACKGROUND_PROCESSING` is on, and owns leased provider discovery, durable identity acquisition, independent attachment retries, reconciliation, and safe health notifications. Single ownership comes from database leases (`FOR UPDATE SKIP LOCKED` + lease expiry), not process topology. There is no APScheduler and no `email_fetch` task — the coordinator owns its own cadence. New integrations become pollable via the `integrations_ensure_email_sync_state` trigger; `request_email_sync_now` asks for a prompt poll. `selko.worker_app` runs the identical task set standalone for staging drills.
- **Durable email work state:** a `pending` email is invariant-guaranteed claimable (`emails_pending_is_claimable_check`: `attempts < max_attempts`, no owner, no unexpired lock). `claim_unprocessed_email` opportunistically reclaims one expired `processing` lease per call before claiming fresh work, so a crashed worker's row recovers on the next claim, never on a restart or a periodic sweep. `fail_email_processing` is the single fenced retry-or-terminate RPC; a stale `(worker_id, lock_generation)` is a no-op. Provider discovery leases (`email_sync_state`/`email_sync_runs`) are generation-fenced end to end via claim → heartbeat → complete/fail, and at most one `running` run exists per integration by a partial unique index. `health_work_state` is the single counted health RPC behind both `/health` and `/health/ingestion`; it reports `unclaimable_pending` (actionable, degrades the rollup) separately from `failed_emails` (terminal history, never degrades it) — merging them made `degraded` permanent after the first exhausted retry; see `docs/specs/state-ownership-and-deterministic-recovery.md` S1–S5 for the implemented current model. Local real-Postgres evidence and production observation/cutover remain explicit operator gates.
- **Single-owner calendar sync:** Approval and proposal application enqueue `calendar_work_items`; the item owns action, generation, attempts, lease, error, and provider-write fencing. `events.review_status` owns the user decision — queueing calendar work never writes it, so each caller states the decision itself before enqueueing — while API and clients derive delivery state from the latest non-superseded work item. Automatic cancellation enqueues an item with `action='cancel'`. Background workers are the sole Google Calendar writers for both upserts and cancellations. Explicit `/events/{id}/sync` requests idempotently observe or requeue worker-owned work.
- **Reviewed repair tooling:** `scripts/repair_review_queue_integrity.py` is dry-run by default; production mutation requires an absolute manifest, exact confirmed user, `--environment production`, `--apply`, and a redacted reverse-operation artifact. It uses the service-only `event_repair_audit` table and `queue_event_cancellation` transition; never run production apply without explicit approval. `cli.cli_resync_email_bodies` follows the same posture for a different class: it re-fetches stored Gmail messages whose saved body says less than the provider snippet and upserts the re-parsed content, dry-run by default. It exists because **a fix to the sync path cannot heal history** — `reprocess_email` re-runs extraction on stored data and never re-fetches, so Reprocess appears to do nothing on a row saved with a placeholder body (#381).
- **Measure what the API answers, not only what the workers are doing.** Every
  health invariant here was internal — dead letters, worker liveness, listener,
  transport — so `POST /events/{id}/apply-change` could return 500 to *every*
  request for eight days with all of them green. `request_metrics` counts
  responses by outcome and `/health` publishes `requests.server_errors_per_hour`,
  which `assert-health.sh` requires to be zero.
- **A route no test calls has not been tested.** The service function under
  `apply-change` was well covered; the route itself had no test, so
  `applied["status"]` was never executed and survived the deletion of
  `events.status` in `20260829000001`. This is the HTTP twin of the SQL rule
  above: coverage of the layer underneath proves nothing about the layer users
  actually reach.
- **An unhandled exception must still return a CORS-bearing response.**
  Starlette's `ServerErrorMiddleware` sits outside `CORSMiddleware`, so a bare
  crash produces a 500 the browser refuses to read — the client reports a
  network failure ("Load failed" in Safari) and the real error is invisible.
  `app.py` registers a catch-all handler so a 500 arrives as a readable 500.
- **Health signals must be able to return to green.** A gauge that can never
  read zero is ignored exactly as fast as one that can never go red, and this
  codebase has shipped both. `unclaimable_emails` counted permanent terminal
  failures alongside actionable stuck rows, so one failed email pinned
  production to `degraded` forever (fixed by `20260901000001`, which splits
  `unclaimable_pending` from `failed_emails`). The incident evaluator raised a
  *critical* `stale_poll` against integrations that are deliberately not polled,
  so an expired OAuth token did the same for 18 days. Before adding a health
  signal, ask what makes it go back to green, and whether that is something the
  system does on its own.
- **Reconnect recovery:** Google Calendar reauthorization atomically creates a durable `integration_recoveries` generation (via `complete_integration_reauthorization`) that requeues OAuth-blocked calendar work items; email resumes from provider cursors via the `integrations_ensure_email_sync_state` trigger with no recovery record. Auth failures are classified on `calendar_work_items.failure_code` (`oauth_required`/`oauth_scope_required`) and never trip the global provider circuit breaker. The ConnectionRecovery card on web/iOS/Android shows catch-up progress (`integration_recoveries` is RLS-readable by the owner).
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
| **Deploy log** | `docs/deploy-log/` | Before and after every production deploy. Config, real production data, and elapsed-time failures are invisible to local tests; two of those categories are only observable after deploy. Records what shipped, T+0/T+15m/T+24h observations, and **which gate should have caught** anything that broke |
| **Executable truth** | `docs/specs/executable-truth.md` | **Read before trusting any gate, drill, or spec status.** V1–V8 make gates incapable of reporting success without evidence, then fix what they were hiding: unattributed Graph egress, a Graph failure ledger with no writer, an unconditional idle poll, fencing implemented as a branch, and the half of the S5 state collapse left undone. Carries decisions D1–D3 |
| **Cutover verification** | `docs/specs/cutover-verification-20260807.md` | The single ordered production cutover checklist (migrations → code → flag last). Execute it through foundation-integrity F7–F8, never directly |
| **Foundation integrity** | `docs/specs/foundation-integrity.md` | Read after the stub-rollback plan above. Builds a real execution gate (integration tests against local Postgres) because the mocked-only DoD gate is why broken SQL, unreachable code and a non-functional schema gate all shipped green. Carries the six open defects (D1–D6) from the C1–C9 review and the production cutover |
| **Stub rollback and gate repair** | `docs/specs/stub-rollback-and-gate-repair.md` | Gate-repair record for G1–G7; G1–G5 are merged, while G6/G7 and the production checks remain tracked. Read before changing the execution gates. |
| **Parallel extraction, fenced commit** | `docs/specs/parallel-extraction-fenced-commit.md` | Before touching worker concurrency, `save_extracted_events`, or how extracted events are persisted. Extraction stays parallel; the commit is fenced on the candidate band it was computed against. Replaces review-queue-integrity R2 |
| **Calendar identity and cancellation** | `docs/specs/calendar-identity-and-cancellation.md` | Before touching iCalendar parsing, event identity/dedup, or cancellation. Replaces review-queue-integrity R3–R4 |
| **Review queue integrity** | `docs/specs/review-queue-integrity.md` | Normative requirements for web Review (§5), identity (§7), cancellation (§8) and the production repair (§9). Decisions 6–7 stand; **§6's fenced-lane mechanism is superseded** — see parallel-extraction-fenced-commit |
| **Event identity reach** | `docs/specs/event-identity-reach.md` | Before touching dedup, invite handling, or why an event the user already has appears as New. Measured from production: ~4% of events carry any identity hint and none carry an iCalendar UID, so matching falls back to a one-local-day window plus LLM text comparison. Carries the S1–S15 scenario matrix |
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
