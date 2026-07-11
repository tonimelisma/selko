#!/bin/bash
# Block interactive commands that Claude Code cannot handle
#
# Exit codes:
#   0 = allow the tool call
#   2 = block the tool call (shows stderr to Claude)

# Read tool input from stdin
INPUT=$(cat)
COMMAND=$(echo "$INPUT" | jq -r '.tool_input.command // empty')

# Skip commands containing git commit (they may mention blocked commands in messages)
if echo "$COMMAND" | grep -qE 'git commit'; then
  exit 0
fi

# Block gh pr checks --watch
if echo "$COMMAND" | grep -qE 'gh pr checks.*--watch'; then
  cat >&2 << 'EOF'

================================================================================
BLOCKED: 'gh pr checks --watch' is interactive and cannot be used.

The --watch flag creates streaming output that Claude Code cannot parse.

Merges do not gate on CI. To merge and clean up, use:
    ./scripts/merge-and-cleanup.sh <pr_number>

To verify CI (optional, e.g. before a prod deploy), use:
    ./scripts/poll-and-merge.sh <pr_number> [pr_number ...]
================================================================================

EOF
  exit 2
fi

exit 0
