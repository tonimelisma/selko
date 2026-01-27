# Parallel Agent Workflow Guide

This guide covers running multiple AI coding agents simultaneously on the same repository using Git worktrees.

## Overview

| Component | Choice | Why |
|-----------|--------|-----|
| Isolation | Git Worktrees | Disk-efficient, shared .git |
| Branching | Feature branches | Required by worktrees, enables PRs |
| Merging | Manual after CI | Wait for CI to pass, then squash merge |
| Alerts | Email notifications | Know immediately if CI fails |

## Naming Conventions

| Type | Format | Example |
|------|--------|---------|
| **Branch** | `<type>/<task-name>` | `feat/add-login`, `fix/api-timeout` |
| **Worktree** | `selko-<type>-<task>` | `selko-feat-add-login`, `selko-fix-api-timeout` |

**Types:** `feat`, `fix`, `refactor`, `test`, `docs`, `chore`

## GitHub Setup (One-Time)

**Notifications** (Personal Settings → Notifications):
- ✅ Actions: Send notifications for failed workflows only

> **Note:** Auto-merge requires GitHub Pro for private repos. This project uses manual merge after CI passes instead.

## Pre-Work Checklist

**Run these commands from the main repo BEFORE starting any task:**

```bash
cd ~/Development/selko

# 1. Sync main with GitHub
git fetch origin && git merge --ff-only origin/main

# 2. List existing worktrees
git worktree list

# 3. Clean up stale worktrees (whose branches have been merged)
#    For each finished worktree:
git worktree remove ../selko-<type>-<old-task>
git branch -D <type>/<old-task>

# 4. Prune orphaned worktree refs
git worktree prune

# 5. Create new worktree for your task
git worktree add ../selko-<type>-<task> -b <type>/<task-name> main

# 6. Copy environment files to worktree
cp .env ../selko-<type>-<task>/
cp .env.test ../selko-<type>-<task>/
cp .env.production ../selko-<type>-<task>/
cp frontend/.env ../selko-<type>-<task>/frontend/ 2>/dev/null || true

# 7. Move to worktree
cd ../selko-<type>-<task>

# 8. Install dependencies (if needed)
uv sync                         # Python deps
cd frontend && npm ci && cd ..  # JS deps (if changing frontend)
```

## Working in a Worktree

### Making Changes

```bash
# You're in ~/Development/selko-feat-add-login/

# Edit files, run tests
uv run pytest backend/tests/ -v
cd frontend && npm run test:unit -- --reporter=json --outputFile=test-results.json

# Commit with conventional commit format
git add specific-files.py
git commit -m "feat: add new capability"

# Push to remote
git push -u origin feat/add-login
```

### Creating PR and Merging

```bash
# Create the PR
gh pr create \
  --title "feat: add new capability" \
  --body "Description of changes"

# Wait for CI to pass, then merge
gh pr checks --watch && gh pr merge --squash
```

### When Another Agent's PR Merges

If your worktree is based on an older main, rebase:

```bash
git fetch origin main
git rebase origin/main

# If conflicts:
# 1. Resolve conflicts in files
# 2. git add resolved-files
# 3. git rebase --continue

# Push updated branch
git push --force-with-lease
```

## Definition of Done (DOD)

After your task is complete:

- [ ] Tests pass for changed modules
- [ ] CHANGELOG.md updated
- [ ] Committed with conventional commit format
- [ ] Pushed to feature branch
- [ ] PR created with `gh pr create`
- [ ] Wait for CI and merge with `gh pr checks --watch && gh pr merge --squash`

## After PR: Wait for CI, Merge, and Cleanup

### MANDATORY: AI agents MUST follow all steps

```bash
# 1. Wait for CI checks to pass
echo "Waiting for CI checks..."
gh pr checks --watch

# 2. Merge the PR (manual since auto-merge requires GitHub Pro)
gh pr merge --squash

# 3. Return to main repo
cd ~/Development/selko

# 4. Remove worktree and branch
git worktree remove ../selko-<type>-<task>
git branch -D <type>/<task-name>

# 5. Sync main
git fetch origin && git merge --ff-only origin/main
```

> **CRITICAL FOR AI AGENTS:** You MUST complete ALL steps including cleanup. Failure to clean up leaves stale branches and worktrees that block other agents.

## Task Assignment Guidelines

To minimize conflicts, assign agents to **non-overlapping areas**:

| Agent | Scope | Example Directories |
|-------|-------|---------------------|
| Agent 1 | Backend API | `backend/selko/api/` |
| Agent 2 | Frontend UI | `frontend/src/routes/` |
| Agent 3 | Tests/Docs | `backend/tests/`, `docs/` |

**High-conflict files** to avoid parallel edits:
- `CHANGELOG.md`
- `pyproject.toml` / `package.json`
- Migration files

## What's Allowed in Main Repo

The Claude Code hook **blocks source code** but **allows config/docs**:

| Blocked | Allowed |
|---------|---------|
| `backend/` | `docs/` |
| `frontend/src/` | `.env*` |
| `ios/*.swift` | `CLAUDE.md` |
| `android/*.kt` | `.claude/*` |
| `cli/` | `scripts/`, `supabase/` |

## Troubleshooting

### "Branch already checked out"
```bash
# Can't checkout same branch in two worktrees
# Solution: Use different branch names
git worktree add ../selko-feat-other -b feat/other-task main
```

### CI Fails, PR Won't Merge
```bash
gh pr checks        # Check CI status
gh run view --log-failed  # View logs
git push            # Push fix, auto-merge retries
```

### Merge Conflicts on Rebase
```bash
git status                    # See conflicting files
# ... resolve conflicts ...
git add resolved-file.py
git rebase --continue

# If too messy:
git rebase --abort
git merge origin/main
```

## Quick Reference

| Task | Command |
|------|---------|
| Sync main | `git fetch origin && git merge --ff-only origin/main` |
| Create worktree | `git worktree add ../selko-<type>-<task> -b <type>/<task> main` |
| List worktrees | `git worktree list` |
| Remove worktree | `git worktree remove ../selko-<type>-<task>` |
| Delete branch | `git branch -D <type>/<task>` |
| Prune refs | `git worktree prune` |
| Create PR | `gh pr create` |
| Wait for CI + merge | `gh pr checks --watch && gh pr merge --squash` |
| Check CI status | `gh pr checks` |
| Rebase | `git fetch origin main && git rebase origin/main` |
| Force push | `git push --force-with-lease` |
