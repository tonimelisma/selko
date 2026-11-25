#!/bin/bash
#
# Claude Code PreToolUse hook to block SOURCE CODE edits in the main repository.
# AI agents MUST use git worktrees for code changes.
# Config files, docs, and non-code files ARE allowed in main.
#
# In a Claude Code cloud session (CLAUDE_CODE_REMOTE=true) the checkout is a
# throwaway clone that belongs to this one session, so there is nothing to
# isolate it from and worktrees under ~/Development do not exist. What still
# protects there is the branch: source code must never be edited while the
# clone has `main` checked out, because that is the edit that ends up pushed
# without a PR. So the cloud rule is "source edits need a feature branch".
#
# Exit codes:
#   0 = allow the tool call
#   2 = block the tool call (shows stderr to Claude)

# Read hook input from stdin
input=$(cat)

# Extract the file path being edited
# jq is not guaranteed on a fresh cloud VM, and an empty path here would
# silently allow every edit, so fall back to python3 rather than fail open.
if command -v jq >/dev/null 2>&1; then
  file_path=$(echo "$input" | jq -r '.tool_input.file_path // empty')
else
  file_path=$(echo "$input" | python3 -c 'import json,sys; print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))')
fi

if [[ "${CLAUDE_CODE_REMOTE:-}" == "true" ]]; then
  MAIN_REPO_PATH="${CLAUDE_PROJECT_DIR:-$(pwd)}"
else
  # The main repository path on Toni's Mac
  MAIN_REPO_PATH="$HOME/Development/selko"
fi

# If file is not in main repo, allow it (worktrees, etc.)
if [[ "$file_path" != "$MAIN_REPO_PATH/"* && "$file_path" != "$MAIN_REPO_PATH" ]]; then
  exit 0
fi

# Get the path relative to repo root
relative_path="${file_path#$MAIN_REPO_PATH/}"

# SOURCE CODE DIRECTORIES - these are BLOCKED in main repo
# Agents must use worktrees for code changes
is_source_code=false

case "$relative_path" in
  backend/*)
    is_source_code=true
    ;;
  frontend/src/*)
    is_source_code=true
    ;;
  cli/*.py|cli/**/*.py)
    is_source_code=true
    ;;
esac

[[ "$is_source_code" == "true" ]] || exit 0

if [[ "${CLAUDE_CODE_REMOTE:-}" == "true" ]]; then
  branch=$(git -C "$MAIN_REPO_PATH" branch --show-current 2>/dev/null)
  if [[ -n "$branch" && "$branch" != "main" && "$branch" != "master" ]]; then
    exit 0
  fi
  cat >&2 << EOF

================================================================================
BLOCKED: Cannot edit source code while this cloud clone is on '${branch:-a detached HEAD}'.

You attempted to edit: $file_path

Source code (backend/, frontend/src/, cli/) is changed on a
feature branch and shipped by PR. In a cloud session the clone is already
isolated, so no worktree is needed -- just create the branch here:

    git switch -c <type>/<task-name>

Config files, docs, and scripts may be edited on main.
================================================================================

EOF
  exit 2
fi

cat >&2 << EOF

================================================================================
BLOCKED: Cannot edit source code in the main repository.

You attempted to edit: $file_path

Source code files (backend/, frontend/src/, cli/) require
a git worktree. Config files, docs, and .env files ARE allowed in main.

To fix this, create a worktree (see Pre-Work Checklist in CLAUDE.md):

    git fetch origin && git merge --ff-only origin/main
    git worktree add ../selko-<type>-<task> -b <type>/<task-name> main
    cd ../selko-<type>-<task>

Then edit source code files in that worktree instead.
================================================================================

EOF
exit 2
