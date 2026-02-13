#!/bin/bash
# Poll CI checks for one or more PRs and merge when green.
#
# Usage:
#   ./scripts/poll-and-merge.sh 71
#   ./scripts/poll-and-merge.sh 71 72 73
#
# Exit codes:
#   0 = all PRs merged successfully
#   1 = one or more PRs had CI failures

set -euo pipefail

if [ $# -eq 0 ]; then
    echo "Usage: $0 <pr_number> [pr_number ...]"
    exit 1
fi

POLL_INTERVAL=10
FAILED_PRS=()
MERGED_PRS=()

for pr in "$@"; do
    echo "Polling CI for PR #${pr}..."

    while true; do
        ec=0
        gh pr checks "$pr" || ec=$?

        if [ $ec -eq 0 ]; then
            echo "CI passed for PR #${pr}, merging..."
            gh pr merge "$pr" --squash
            echo "PR #${pr} merged."
            MERGED_PRS+=("$pr")
            break
        elif [ $ec -ne 8 ]; then
            echo "CI failed for PR #${pr}."
            FAILED_PRS+=("$pr")
            break
        fi

        # Exit code 8 = checks still pending
        sleep "$POLL_INTERVAL"
    done
done

echo ""
echo "Results:"
[ ${#MERGED_PRS[@]} -gt 0 ] && echo "  Merged: ${MERGED_PRS[*]}"
[ ${#FAILED_PRS[@]} -gt 0 ] && echo "  Failed: ${FAILED_PRS[*]}"

if [ ${#FAILED_PRS[@]} -gt 0 ]; then
    exit 1
fi
