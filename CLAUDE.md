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
- [ ] CHANGELOG.md updated
- [ ] Git commit with conventional message
- [ ] Git push to feature branch
- [ ] PR created with `gh pr create`
- [ ] Auto-merge enabled with `gh pr merge --auto --squash`

### After PR Merges

Auto-merge happens automatically after CI passes. No manual merge action is required.

```bash
cd ~/Development/selko
git worktree remove ../selko-<type>-<task>
git branch -D <type>/<task-name>
git fetch origin && git merge --ff-only origin/main
```

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
| `gh pr create && gh pr merge --auto --squash` | Create PR and enable auto-merge |

### CLI Tools

| Command | Purpose |
|---------|---------|
| `uv run python -m cli.cli_user create --email X --password Y` | Create user |
| `uv run python -m cli.cli_auth_gmail` | Gmail OAuth flow |
| `uv run python -m cli.cli_fetch_emails --max 10` | Fetch emails |
| `uv run python -m cli.cli_seed_tokens --from staging --to development --provider gmail` | Seed tokens |

**Full test guide:** `docs/testing-guide.md`

---

## Architecture Principles

- **Direct Supabase Access:** Frontends query Supabase directly. Python API only for operations requiring secrets (OAuth, Gmail sync, LLM processing).
- **End-to-End First:** Complete full journeys before expanding scope. First journey: Email → Calendar Event.
- **LLM-Centric AI:** All intelligence uses Gemini multimodal LLM (no separate OCR service).
- **YAGNI:** Add complexity only when measured need exists.

**Details:** `PRD_ARCH.md`

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

---

## License

This is **proprietary, commercially copyrighted software** - NOT open source. Copyright (c) 2026 Toni Melisma. See LICENSE file.
