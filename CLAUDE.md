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

- [ ] Working in a git worktree on a feature branch
- [ ] Tests pass for changed modules
- [ ] **Bug fixes MUST include a regression test**
- [ ] Update screenshots for changed platforms only (see "Screenshot Updates" section below). Review the captured screenshots to verify UI looks correct.
- [ ] Commit, push, `gh pr create`
- [ ] Run `./scripts/poll-and-merge.sh <pr_number>` — this polls PR CI, merges, AND verifies the post-merge push workflow on main (including staging deploy + integration tests). This is the **one and only** way to track CI.
- [ ] If the script reports post-merge failure, diagnose and fix immediately (see CI Ownership below)
- [ ] Cleanup worktree (see cleanup rules below)

**Config/docs edits on main** (no worktree needed): commit and `git push origin main`.

See `docs/parallel-agents.md` for the full workflow. See `docs/ci-cd.md` for CI architecture details.

### MANDATORY: CI Ownership

**You are responsible for all CI passing — PR checks AND the post-merge push workflow (staging deploy + integration tests).** The `poll-and-merge.sh` script handles both automatically. If the post-merge workflow fails:

1. **Diagnose the failure** — read `gh run view <id> --log-failed`
2. **If Google OAuth tokens expired** (`RefreshError: invalid_grant`): ask the user to run `ENVIRONMENT=staging uv run python -m cli.cli_auth_gmail` to refresh tokens, then re-run CI to verify
3. **If it's a code issue**: fix it immediately with a follow-up PR
4. **Never leave CI broken** — a red main branch blocks all other work

**NEVER use `gh pr checks`, `gh run list`, `gh run watch`, or manual polling loops.** Always use `./scripts/poll-and-merge.sh`.

### MANDATORY: Worktree Cleanup Rules

**NEVER force-remove a worktree (`--force`) without first inspecting uncommitted work.**

Before removing any worktree:
1. `cd` to the worktree and run `git status`
2. If there are uncommitted/untracked files, **review them manually** — they may contain important work, test results, or artifacts
3. Only use `git worktree remove` (without `--force`). If it refuses, that's a safety mechanism — inspect and resolve first
4. **`git worktree remove --force` destroys uncommitted work with no recovery** — treat it like `rm -rf`

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
- **LLM-Centric AI:** All intelligence uses multimodal LLMs (6 providers supported, Gemini default).
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

---

## License

This is **proprietary, commercially copyrighted software** - NOT open source. Copyright (c) 2026 Toni Melisma. See LICENSE file.
