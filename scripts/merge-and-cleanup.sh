#!/bin/bash
# Merge a PR and fully clean up — WITHOUT gating on CI.
#
# The DoD trusts local, change-scoped tests as the gate. CI (unit tests,
# staging deploy, integration tests) still runs on the merge commit as a
# safety net, but it does NOT block the merge. If CI fails, fix forward.
#
# What it does:
#   1. Squash-merges the PR (the repo auto-deletes the remote branch on merge)
#   2. Fast-forwards local main to origin/main
#   3. Removes the feature worktree (never --force) and deletes the local branch
#   4. Prunes stale worktree refs
#
# Run this as the FINAL step of your task — afterward the worktree no longer
# exists, so make it your last command before reporting back to the user.
#
# Usage:
#   ./scripts/merge-and-cleanup.sh <pr_number>
#
# Exit codes:
#   0 = merged and cleaned up
#   1 = a step failed (e.g. worktree had uncommitted work — inspect, don't --force)

set -euo pipefail

if [ $# -ne 1 ]; then
    echo "Usage: $0 <pr_number>"
    exit 1
fi

PR="$1"

# Resolve the main working tree (listed first by `git worktree list`).
MAIN_REPO=$(git worktree list --porcelain | awk '/^worktree /{print $2; exit}')

# Capture the PR's branch BEFORE merging — the remote branch is deleted on merge.
PR_BRANCH=$(gh pr view "$PR" --json headRefName -q '.headRefName')
echo "Merging PR #${PR} (branch: ${PR_BRANCH})..."

# 1. Squash-merge. Do NOT wait for CI. Do NOT pass --delete-branch: gh would
#    also try to delete the LOCAL branch as part of this command, which fails
#    (silently, without aborting) because it's checked out in the feature
#    worktree below — that partial failure is what left the worktree/branch
#    cleanup in an inconsistent state. The remote branch doesn't need it
#    either: this repo has "Automatically delete head branches" enabled, so
#    GitHub deletes the remote branch itself once the merge lands.
gh pr merge "$PR" --squash

# Cloud sessions (CLAUDE_CODE_REMOTE=true) work in a single throwaway clone with
# the PR branch checked out in it and no worktrees, so "fast-forward main and
# remove the worktree" means: move this clone onto the merged main and drop the
# local branch. Uncommitted work makes the switch refuse, as remove does below.
if [[ "${CLAUDE_CODE_REMOTE:-}" == "true" ]]; then
    git -C "$MAIN_REPO" fetch origin
    if [[ -n "$(git -C "$MAIN_REPO" status --porcelain)" ]]; then
        echo "Refusing to switch branches: the clone has uncommitted work. Inspect it (git status)." >&2
        exit 1
    fi
    git -C "$MAIN_REPO" switch -C main origin/main
    if git -C "$MAIN_REPO" show-ref --verify --quiet "refs/heads/${PR_BRANCH}"; then
        git -C "$MAIN_REPO" branch -D "$PR_BRANCH"
    fi
    echo ""
    echo "Done. PR #${PR} merged; this cloud clone is on the merged main; local branch deleted."
    echo "CI runs on the merge as a safety net (not a gate)."
    exit 0
fi

# 2. Fast-forward local main.
git -C "$MAIN_REPO" fetch origin
git -C "$MAIN_REPO" merge --ff-only origin/main

# 3. Remove the feature worktree (if one exists for this branch), then the branch.
#    Resolved relative to $MAIN_REPO (not the invoking shell's cwd) so this
#    works the same whether this script is run from the main repo or,
#    mistakenly, from inside a feature worktree.
WORKTREE=$(git -C "$MAIN_REPO" worktree list --porcelain | awk -v b="refs/heads/${PR_BRANCH}" '
    /^worktree /{p=$2}
    $0 == "branch " b {print p; exit}')

if [ -n "${WORKTREE:-}" ]; then
    echo "Removing worktree ${WORKTREE}..."
    # NEVER --force. If this refuses, there is uncommitted work — inspect it
    # manually (git status in the worktree) before deciding to discard.
    git -C "$MAIN_REPO" worktree remove "$WORKTREE"
fi

# Delete the local branch if it still exists (squash merge leaves it "unmerged",
# so -D is required).
if git -C "$MAIN_REPO" show-ref --verify --quiet "refs/heads/${PR_BRANCH}"; then
    git -C "$MAIN_REPO" branch -D "$PR_BRANCH"
fi

git -C "$MAIN_REPO" worktree prune

echo ""
echo "Done. PR #${PR} merged; branch + worktree cleaned up; main fast-forwarded."
echo "CI runs on the merge as a safety net (not a gate)."
echo "REMINDER: if this change ships to a server, ask the user before deploying to production."
