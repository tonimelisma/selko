# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Selko** is an AI-powered assistant that automates personal organization by analyzing digital inputs (emails, photos) to manage schedules, to-do lists, and digital filing systems. The system acts as a "Human-in-the-loop" filter, ensuring accuracy before committing changes to permanent records.

See `PRD_ARCH.md` for complete product requirements, technical architecture, and implementation details.

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

### Naming Conventions

| Type | Branch | Worktree |
|------|--------|----------|
| Feature | `feat/add-login` | `selko-feat-add-login` |
| Bugfix | `fix/api-timeout` | `selko-fix-api-timeout` |

Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`

### Pre-Work Checklist

```bash
cd ~/Development/selko

# 1. Sync main
git fetch origin && git merge --ff-only origin/main

# 2. Clean up merged worktrees
git worktree list
git worktree remove ../selko-<type>-<old-task>  # for merged ones
git branch -D <type>/<old-task>
git worktree prune

# 3. Create new worktree
git worktree add ../selko-<type>-<task> -b <type>/<task-name> main

# 4. Copy environment files
cp .env ../selko-<type>-<task>/
cp .env.test ../selko-<type>-<task>/
cp .env.production ../selko-<type>-<task>/
cp frontend/.env ../selko-<type>-<task>/frontend/ 2>/dev/null || true

# 5. Move to worktree and install deps
cd ../selko-<type>-<task>
uv sync
cd frontend && npm ci && cd ..  # if changing frontend
```

> **CRITICAL: After step 5, your working directory MUST be the worktree.**
>
> All subsequent commands run from inside the worktree directory:
> ```
> ~/Development/selko-<type>-<task>/    ← CORRECT
> ~/Development/selko/                  ← WRONG
> ```
>
> Do NOT use `git -C /path`, `cd /path && command`, or absolute paths to the worktree.
> Just run commands normally - you're already in the right place.
>
> **If a Bash command is rejected:** You're probably in the wrong directory.
> Verify with `pwd` and change to the worktree if needed.

**Full details:** `docs/parallel-agents.md`

### Enforcement

A Claude Code hook **blocks source code edits** in the main repo. You'll see:
```
BLOCKED: Cannot edit source code in the main repository.
```

---

## Definition of Done

**Before declaring work complete, ALL must pass:**

- [ ] Working in a git worktree (NOT main repo)
- [ ] On a feature branch (NOT main)
- [ ] Tests pass for changed modules
- [ ] Visual verification with `/verify-web`, `/verify-ios`, or `/verify-android` (if UI was changed). Save screenshots to `docs/screenshots/` and include in commit.
- [ ] CHANGELOG.md updated
- [ ] Git commit with conventional message
- [ ] Git push to feature branch
- [ ] PR created with `gh pr create`
- [ ] Poll CI and merge (see code block below)

### After PR: Wait, Merge, and Cleanup

**AI agents MUST complete ALL steps:**

```bash
# 1. Poll CI status and merge when ready
# NOTE: Don't use "status" as variable name - it's read-only in zsh
while true; do
  gh pr checks
  ec=$?
  if [ $ec -eq 0 ]; then
    gh pr merge --squash
    break
  elif [ $ec -ne 8 ]; then
    echo "CI checks failed"
    exit 1
  fi
  sleep 10
done

# 2. Return to main repo and cleanup
cd ~/Development/selko
git worktree remove ../selko-<type>-<task>
git branch -D <type>/<task-name>
git fetch origin && git merge --ff-only origin/main
```

> **Note:** Remote branches are auto-deleted by GitHub when PRs merge. Only local cleanup is needed.

### Pre-Commit Hook

Blocks commits unless tests pass. Setup: `cp scripts/pre-commit.hook .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit`

**Full details:** `docs/testing-guide.md` and `docs/ci-cd.md`

---

## Essential Commands

| Command | Purpose |
|---------|---------|
| `supabase start` | Start local Supabase (Docker) |
| `supabase db reset` | Reset local database |
| `uv run pytest backend/tests/ -v` | Run backend tests |
| `cd frontend && npm run test:unit -- --reporter=json --outputFile=test-results.json` | Run frontend tests |
| `uv run python -m selko.api` | Start FastAPI server |
| `cd frontend && npm run test:e2e -- --project=chromium` | Run Playwright E2E tests |
| `cd android && ./gradlew testDebugUnitTest` | Run Android unit tests |
| `cd android && ./gradlew connectedAndroidTest` | Run Android Compose UI tests (needs emulator) |
| `xcodebuild -project ios/iOS.xcodeproj -scheme iOS -destination 'generic/platform=iOS Simulator' build` | Build iOS |
| `xcodebuild test -project ios/iOS.xcodeproj -scheme iOS -destination 'platform=iOS Simulator,name=iPhone 17 Pro' -resultBundlePath ios/TestResults.xcresult` | Run iOS tests |
| `gh pr create` | Create PR |
| `while true; do gh pr checks; s=$?; [ $s -eq 0 ] && gh pr merge --squash && break; [ $s -ne 8 ] && exit 1; sleep 10; done` | Poll CI, merge on success, exit on failure |

> **iOS gotcha:** Project is `iOS.xcodeproj` and scheme is `iOS` (not "Selko"). Remove old `ios/TestResults.xcresult` before re-running tests.

### CLI Tools

| Command | Purpose |
|---------|---------|
| `uv run python -m cli.cli_user create --email X --password Y` | Create user |
| `uv run python -m cli.cli_auth_gmail` | Gmail OAuth flow |
| `uv run python -m cli.cli_auth_gcal` | Google Calendar OAuth flow |
| `uv run python -m cli.cli_fetch_emails --max 10` | Fetch emails |
| `uv run python -m cli.cli_process_emails --recent 5` | Process emails into events |
| `uv run python -m cli.cli_events new` | List pending events |
| `uv run python -m cli.cli_events approve <id>` | Approve event |
| `uv run python -m cli.cli_events sync <id>` | Sync event to Google Calendar |
| `uv run python -m cli.cli_seed_tokens --from staging --to development --provider gmail` | Seed tokens |

**Full walkthrough:** `docs/manual-email-to-calendar-walkthrough.md`
**Full test guide:** `docs/testing-guide.md`

---

## Blocked Commands

These commands are blocked by hooks because they don't work with Claude Code:

| Command | Why Blocked | Alternative |
|---------|-------------|-------------|
| `gh pr checks --watch` | Interactive output, unparsable | See "After PR" section for polling loop |

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

Three MCP servers are configured in `.mcp.json` for visual verification:
- **Playwright MCP** — browser automation, screenshots, accessibility tree
- **XcodeBuildMCP** — iOS build + simulator control
- **mobile-mcp** — iOS Simulator + Android Emulator interaction

**Slash commands:** `/verify-web`, `/verify-ios`, `/verify-android` — use these after implementing UI changes.

### Playwright MCP (Web)
1. Start dev server first: `cd frontend && npm run dev`
2. Use `browser_navigate` to open pages (e.g., `http://localhost:5173/login`)
3. Use `browser_snapshot` for accessibility tree, `browser_take_screenshot` for visual checks
4. Test at desktop (1280x800) and mobile (390x844) viewports

### XcodeBuildMCP (iOS)
1. Call `session-show-defaults` first to see current config
2. Use `discover_projs` to find projects, `list_schemes` for schemes
3. `build_sim` to build, `test_sim` for tests, `screenshot` for visual verification
4. `list_sims` to find available simulators

### mobile-mcp (iOS Simulator / Android Emulator)
1. `mobile_take_screenshot` for visual captures
2. `mobile_list_elements_on_screen` for UI hierarchy
3. `mobile_click_on_screen_at_coordinates` for interaction
4. Works with both iOS Simulator and Android Emulator

**Full details:** `docs/ui-testing-guide.md`

---

## Architecture Principles

- **Direct Supabase Access:** Frontends query Supabase directly. Python API only for operations requiring secrets (OAuth, Gmail sync, LLM processing).
- **End-to-End First:** Complete full journeys before expanding scope. First journey: Email → Calendar Event.
- **LLM-Centric AI:** All intelligence uses Gemini multimodal LLM (no separate OCR service).
- **YAGNI:** Add complexity only when measured need exists.

**Details:** `PRD_ARCH.md`

---

## MANDATORY: Self-Maintenance Rule

**This CLAUDE.md is the single source of truth for all AI agents working on Selko.** After every major change, update this file to reflect the current state.

**Trigger updates when any of these change:**

- New or renamed Supabase tables/columns/migrations → update Database schema link or add inline summary
- New backend modules, services, or API endpoints → update Essential Commands or Reference Index
- New frontend pages, components, or routes → update Reference Index
- New CLI commands → update CLI Tools table
- New or renamed test files/directories → update Essential Commands
- New environment variables or config files → update Environment & Config
- New docs created → add to Reference Index
- Architectural shifts (new services, changed data flow, new integrations) → update Architecture Principles
- New CI/CD workflows or deployment changes → update Reference Index or Essential Commands
- New dependencies or tooling changes → update relevant sections

**Rules:**
1. Keep CLAUDE.md concise — link to detailed docs rather than duplicating content
2. Every linked doc in Reference Index must actually exist; remove stale links
3. If a new doc is created, it MUST be added to Reference Index with a clear "When to Read" description
4. CLI tool table must match actual available commands in the `cli/` directory

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
| **Gemini integration** | `docs/gemini-integration.md` | When working with LLM features |
| **Architecture** | `PRD_ARCH.md` | For product requirements and architecture |
| **UI user journeys** | `docs/ui/01-user-journeys.md` | When planning frontend work or understanding user flows |
| **Screen specifications** | `docs/ui/02-screen-specs.md` | When implementing any web screen |
| **UI patterns & components** | `docs/ui/03-patterns-and-components.md` | Before building any UI component, to follow conventions |
| **Brand guide** | `docs/brand-guide.md` | When implementing any UI, choosing colors, fonts, or terminology |
| **UI testing** | `docs/ui-testing-guide.md` | When writing E2E tests or using MCP visual verification |

---

## License

This is **proprietary, commercially copyrighted software** - NOT open source. Copyright (c) 2026 Toni Melisma. See LICENSE file.
