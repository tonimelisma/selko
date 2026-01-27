#!/bin/bash
#
# Claude Code PreToolUse hook to block file edits in the main repository.
# AI agents MUST use git worktrees for all changes.
#
# Exit codes:
#   0 = allow the tool call
#   2 = block the tool call (shows stderr to Claude)

# Read hook input from stdin
input=$(cat)

# Extract the file path being edited
file_path=$(echo "$input" | jq -r '.tool_input.file_path // empty')

# The main repository path - edits here are BLOCKED
MAIN_REPO_PATH="/Users/tonimelisma/Development/selko"

# Check if the file being edited is in the main repo
# Block if file path starts with the main repo path
# But allow if it's in a worktree (../selko-* paths won't match)
if [[ "$file_path" == "$MAIN_REPO_PATH/"* || "$file_path" == "$MAIN_REPO_PATH" ]]; then
  cat >&2 << EOF

================================================================================
BLOCKED: Cannot edit files in the main repository.

You attempted to edit: $file_path

This file is in the MAIN repository. All AI agents MUST use git worktrees.

To fix this, create a worktree:

    git worktree add ../selko-<task-name> -b <branch-name> main
    cd ../selko-<task-name>
    uv sync && cd frontend && npm ci && cd ..

Then edit files in that worktree instead.

See CLAUDE.md and docs/parallel-agents.md for details.
================================================================================

EOF
  exit 2
fi

# Allow the tool call (file is outside the main repo)
exit 0
