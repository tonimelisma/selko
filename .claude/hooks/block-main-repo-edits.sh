#!/bin/bash
#
# Claude Code PreToolUse hook to block SOURCE CODE edits in the main repository.
# AI agents MUST use git worktrees for code changes.
# Config files, docs, and non-code files ARE allowed in main.
#
# Exit codes:
#   0 = allow the tool call
#   2 = block the tool call (shows stderr to Claude)

# Read hook input from stdin
input=$(cat)

# Extract the file path being edited
file_path=$(echo "$input" | jq -r '.tool_input.file_path // empty')

# The main repository path
MAIN_REPO_PATH="/Users/tonimelisma/Development/selko"

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
  ios/*.swift|ios/**/*.swift)
    is_source_code=true
    ;;
  android/*.kt|android/**/*.kt)
    is_source_code=true
    ;;
  cli/*.py|cli/**/*.py)
    is_source_code=true
    ;;
esac

# If it's source code, block it
if [[ "$is_source_code" == "true" ]]; then
  cat >&2 << EOF

================================================================================
BLOCKED: Cannot edit source code in the main repository.

You attempted to edit: $file_path

Source code files (backend/, frontend/src/, ios/, android/, cli/) require
a git worktree. Config files, docs, and .env files ARE allowed in main.

To fix this, create a worktree (see Pre-Work Checklist in CLAUDE.md):

    git fetch origin && git merge --ff-only origin/main
    git worktree add ../selko-<type>-<task> -b <type>/<task-name> main
    cd ../selko-<type>-<task>

Then edit source code files in that worktree instead.
================================================================================

EOF
  exit 2
fi

# Allow non-source-code files (docs, .env, CLAUDE.md, scripts, etc.)
exit 0
