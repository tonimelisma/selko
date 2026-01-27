# Parallel Agent Workflow Guide

This guide covers running multiple AI coding agents (or developers) simultaneously on the same repository.

## Overview

| Component | Choice | Why |
|-----------|--------|-----|
| Isolation | Git Worktrees | Disk-efficient, shared .git |
| Branching | Feature branches | Required by worktrees, enables PRs |
| Merging | Auto-merge PRs | Hands-off after CI passes |
| Alerts | Email notifications | Know immediately if CI fails |

## Initial Setup

### 1. Configure GitHub (One-Time)

**Auto-Merge** (already enabled via `gh repo edit --enable-auto-merge`):
- Allows PRs to auto-merge after CI passes
- MUST always use `gh pr merge --auto` to ensure CI passes first

**Notifications** (Personal Settings → Notifications):
- ✅ Actions: Send notifications for failed workflows only

**Note:** Branch protection (blocking manual merge) requires GitHub Pro for private repos. Without it, agents must use `--auto` flag to ensure CI passes before merge.

### 2. Create Worktrees

```bash
# From your main repository
cd ~/Development/selko

# Create worktree for each parallel agent
git worktree add ../selko-agent1 -b agent1/feature-name main
git worktree add ../selko-agent2 -b agent2/feature-name main
git worktree add ../selko-agent3 -b agent3/feature-name main

# Verify
git worktree list
```

### 3. Install Dependencies (Each Worktree)

```bash
cd ../selko-agent1
uv sync
cd frontend && npm ci
cd ..

# Repeat for each worktree
```

## Daily Workflow

### Starting Work

```bash
# Navigate to your worktree
cd ~/Development/selko-agent1

# Ensure you're on your feature branch
git branch  # Should show agent1/feature-name

# Pull latest main and rebase
git fetch origin main
git rebase origin/main
```

### Making Changes

```bash
# Work normally - edit files, run tests
uv run pytest backend/tests/ -v
cd frontend && npm run test:unit

# Commit with conventional commit format
git add specific-files.py
git commit -m "feat: add new capability"

# Push to remote
git push -u origin agent1/feature-name
```

### Creating PR with Auto-Merge

```bash
# Create PR that auto-merges after CI passes
gh pr create \
  --title "feat: add new capability" \
  --body "Description of changes" \
  --auto

# Or if PR already exists, enable auto-merge
gh pr merge --auto --squash
```

### After PR Merges

```bash
# Your worktree branch was merged - create new branch for next task
git fetch origin main
git checkout -b agent1/next-task origin/main

# Or delete worktree and create fresh one
cd ~/Development/selko
git worktree remove ../selko-agent1
git worktree add ../selko-agent1 -b agent1/next-task main
```

### When Another Agent's PR Merges

```bash
# Rebase your work on updated main
git fetch origin main
git rebase origin/main

# If conflicts occur:
# 1. Resolve conflicts in files
# 2. git add resolved-files
# 3. git rebase --continue

# Push updated branch (force push needed after rebase)
git push --force-with-lease
```

## Task Assignment Guidelines

To minimize conflicts, assign agents to **non-overlapping areas**:

| Agent | Scope | Example Directories |
|-------|-------|---------------------|
| Agent 1 | Backend API | `backend/selko/api/` |
| Agent 2 | Frontend UI | `frontend/src/routes/` |
| Agent 3 | Tests/Docs | `backend/tests/`, `docs/` |

**High-conflict files** to avoid parallel edits:
- `CLAUDE.md`
- `CHANGELOG.md`
- `pyproject.toml` / `package.json`
- Migration files

## Troubleshooting

### "Branch already checked out"
```bash
# Can't checkout same branch in two worktrees
# Solution: Use different branch names per agent
git worktree add ../selko-agent2 -b agent2/different-name main
```

### CI Fails, PR Won't Merge
```bash
# Check CI status
gh pr checks

# View logs
gh run view --log-failed

# Fix issues, push again
git push
# Auto-merge will retry automatically
```

### Merge Conflicts on Rebase
```bash
# See which files conflict
git status

# After resolving each file
git add resolved-file.py
git rebase --continue

# If too messy, abort and try merge instead
git rebase --abort
git merge origin/main
```

### Stale Worktree References
```bash
# Clean up deleted worktree references
git worktree prune

# List all worktrees
git worktree list
```

## Quick Reference

| Task | Command |
|------|---------|
| Create worktree | `git worktree add ../path -b branch main` |
| List worktrees | `git worktree list` |
| Remove worktree | `git worktree remove ../path` |
| Create PR + auto-merge | `gh pr create --auto` |
| Check PR status | `gh pr checks` |
| Rebase on main | `git fetch origin main && git rebase origin/main` |
| Force push after rebase | `git push --force-with-lease` |
