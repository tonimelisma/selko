# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## MANDATORY: Bash Command Rules

- **Always `cd` to the worktree/project directory first** in a separate Bash call, then run commands with relative paths. Do NOT use absolute paths to files/directories.
- **Never use `cd` as part of a command** (e.g., `cd foo && make`). Change directory in a separate Bash call first.
- **Never chain unrelated commands with `&&`.** Run each command as a separate Bash tool call.
- All three rules are required — violating them breaks Claude Code's permission system.

---

## Project Overview

**Selko** is an AI-powered assistant that automates personal organization by analyzing digital inputs (emails, photos) to manage schedules, to-do lists, and digital filing systems. See `PRD_ARCH.md` for complete product requirements and architecture.

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

### 1. Scope your change

| You changed | Required before merge |
|-------------|-----------------------|
| `backend/**`, `cli/**` | Backend unit tests (`uv run pytest backend/tests/ -m "not integration"`) |
| `supabase/**` (schema/migrations) | Backend unit tests (also deploys to staging on merge) |
| `frontend/src/**` | Frontend unit tests + `npm run check` + **web** screenshots |
| `ios/**` | iOS tests + **iOS** screenshots |
| `android/**` | Android tests + **Android** screenshots |
| `docs/`, `*.md`, `.env*`, `scripts/`, `.claude/`, config only | Nothing to test — commit & push |

- **Only the platform you edited counts.** Editing `backend/` requires no web/iOS/Android tests or screenshots. Editing one frontend requires nothing from the others.
- **Bug fixes MUST include a regression test** in the module you fixed.
- **Screenshots** only for the platform whose UI you changed (see "Screenshot Updates"). Skip for backend/docs/config.

### 2. Ship it

- [ ] Source code → feature branch in a worktree. Config/docs → edit `main` directly (`git push origin main`).
- [ ] The scoped tests above pass locally — **local tests are the gate, not CI**
- [ ] Commit (conventional format), push, `gh pr create`
- [ ] `./scripts/merge-and-cleanup.sh <pr_number>` — squash-merges and does full cleanup: deletes remote + local branch, fast-forwards `main`, removes the worktree, prunes. **Does not wait on CI.**
- [ ] If your change ships to a server (`backend`/`supabase`/`frontend`), **the last sentence of your final report MUST be: "Should I deploy this to production?"** Never deploy to prod without an explicit yes. (Prod deploy = `gh workflow run test.yml`; see `docs/ci-cd.md`.)

See `docs/parallel-agents.md` for the full workflow. See `docs/ci-cd.md` for CI architecture details.

### CI Ownership — safety net, not a gate

Local, change-scoped tests are the gate. **Never block a merge waiting for CI** — Actions minutes are limited and CI may not run at all. CI (unit tests, staging deploy, integration tests) runs on the merge commit as a safety net; if it fails, fix forward:

1. **Diagnose** — `gh run view <id> --log-failed`
2. **Google OAuth expired** (`RefreshError: invalid_grant`): ask the user to run `ENVIRONMENT=staging uv run python -m cli.cli_auth_gmail`, then re-trigger.
3. **Code issue** — follow-up PR.

To verify CI before a prod deploy, `./scripts/poll-and-merge.sh <pr_number>` still polls PR + post-merge CI, but it is optional and not part of the normal DoD.

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
- SF Pro is the system font — do NOT bundle or override it
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
- **End-to-End First:** Complete full journeys before expanding scope. First journey: Email → Calendar Event.
- **LLM-Centric AI:** All intelligence uses multimodal LLMs (6 providers supported, Claude Sonnet 5 default).
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
