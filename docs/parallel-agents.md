# Parallel Agent Workflow Guide

This guide covers running multiple AI coding agents simultaneously on the same repository using Git worktrees.

## Overview

| Component | Choice | Why |
|-----------|--------|-----|
| Isolation | Git Worktrees | Disk-efficient, shared .git |
| Branching | Feature branches | Required by worktrees, enables PRs |
| Merging | Squash merge, no CI gate | Local scoped tests are the gate; CI is a post-merge safety net |
| Alerts | Email notifications | Know if the post-merge CI safety net fails |

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
>
> **Note:** The repo has "Automatically delete head branches" enabled. Remote branches are deleted by GitHub when PRs merge.

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
#    ⚠️  NEVER use --force! Inspect uncommitted work first with git status.
git worktree remove ../selko-<type>-<old-task>
git branch -D <type>/<old-task>

# 4. Prune orphaned worktree refs
git worktree prune

# 5. Create new worktree for your task
#    (env files are copied automatically by the post-checkout hook
#     using .worktreeinclude — no manual cp needed)
git worktree add ../selko-<type>-<task> -b <type>/<task-name> main

# 6. Move to worktree
cd ../selko-<type>-<task>

# 7. Install dependencies (if needed)
uv sync                         # Python deps
cd frontend && npm ci && cd ..  # JS deps (if changing frontend)

# 8. Pre-warm simulators/emulators (if UI task on these platforms)
#    iOS:
xcrun simctl boot "iPhone 17 Pro" 2>/dev/null || true
#    Android (if no emulator running):
adb devices | grep -q emulator || (emulator -avd Pixel_8 -no-audio &)
```

> **CRITICAL: You are now in the worktree directory.**
>
> From this point forward, ALL work happens inside `~/Development/selko-<type>-<task>/`.
>
> - Run all commands from this directory (just `git status`, not `git -C /path status`)
> - Do NOT use path flags or absolute paths to target the worktree
> - Do NOT return to the main repo until cleanup after merge
>
> **If a command is rejected or blocked:** Check your working directory with `pwd`.
> If you're in `~/Development/selko/` instead of the worktree, that's the problem.
> Change to the worktree directory and retry.

## Working in a Worktree

### Making Changes

```bash
# IMPORTANT: You MUST be in ~/Development/selko-feat-add-login/
# Verify with: pwd
# If you're in ~/Development/selko/, STOP - change directory first

# Edit files, then run ONLY the tests for what you changed (see CLAUDE.md scope table)
uv run pytest backend/tests/ -v                                   # if you touched backend/
cd frontend && npm run test:unit -- --reporter=json --outputFile=test-results.json  # if you touched frontend/

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

# Merge (no CI gate) and fully clean up — branch, worktree, main
./scripts/merge-and-cleanup.sh <pr_number>
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

The DoD scales to what you changed — run only the scoped tests for the code you touched (see the scope table in `CLAUDE.md`). A backend-only change runs backend tests only: no web/iOS/Android tests or screenshots.

- [ ] Scoped tests pass locally — **this is the gate, not CI**
- [ ] Bug fixes include a regression test
- [ ] Screenshots only for the platform whose UI changed (skip for backend/docs/config)
- [ ] Committed (conventional format), pushed, PR created (`gh pr create`)
- [ ] `./scripts/merge-and-cleanup.sh <pr_number>` — merges (no CI gate) and cleans up branch + worktree + main
- [ ] If the change ships to a server (`backend`/`supabase`/`frontend`), end your final report asking whether to deploy to production

## After PR: Merge and Cleanup

### MANDATORY: AI agents MUST follow all steps

`merge-and-cleanup.sh` does the whole thing in one command — squash-merge (no CI gate), delete the remote + local branch, fast-forward main, remove the worktree, prune. Run it as your **final step**; the worktree no longer exists afterward, so report back to the user next.

```bash
./scripts/merge-and-cleanup.sh <pr_number>
```

If you ever clean up by hand — e.g. the script refused because the worktree had uncommitted work — do it manually and **NEVER with `--force`**:

```bash
cd ~/Development/selko

# ⚠️  NEVER --force! If remove refuses, go back to the worktree, run `git status`,
#    review any uncommitted files. --force DESTROYS uncommitted work with NO recovery.
git worktree remove ../selko-<type>-<task>
git branch -D <type>/<task-name>
git fetch origin && git merge --ff-only origin/main
```

> **CRITICAL FOR AI AGENTS:** You MUST complete cleanup. Failure to clean up leaves stale worktrees that block other agents.
>
> **NEVER force-remove a worktree.** If `git worktree remove` refuses due to uncommitted/untracked files, go back to the worktree, run `git status`, and manually inspect what's there before deciding whether to discard it. `--force` is equivalent to `rm -rf` on uncommitted work.
>
> **Note:** Remote branches are auto-deleted by GitHub when PRs merge. Only local worktree and branch cleanup is needed.

## Task Assignment Guidelines

To minimize conflicts, assign agents to **non-overlapping areas**:

| Agent | Scope | Example Directories |
|-------|-------|---------------------|
| Agent 1 | Backend API | `backend/selko/api/` |
| Agent 2 | Frontend UI | `frontend/src/routes/` |
| Agent 3 | Tests/Docs | `backend/tests/`, `docs/` |

**High-conflict files** to avoid parallel edits:
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

### Post-merge CI safety net failed
Merges don't gate on CI, so a failure shows up *after* the merge on main. Fix forward:
```bash
# View failed workflow logs:
gh run view --log-failed
# Fix the issue on a new branch and open a follow-up PR (do NOT leave main broken):
./scripts/merge-and-cleanup.sh <follow_up_pr_number>
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
| Remove worktree | `git worktree remove ../selko-<type>-<task>` (NEVER `--force` — inspect first) |
| Delete branch | `git branch -D <type>/<task>` |
| Prune refs | `git worktree prune` |
| Create PR | `gh pr create` |
| Merge + clean up (no CI gate) | `./scripts/merge-and-cleanup.sh <pr_number>` |
| Verify CI before prod (optional) | `./scripts/poll-and-merge.sh <pr_number>` |
| Rebase | `git fetch origin main && git rebase origin/main` |
| Force push | `git push --force-with-lease` |
