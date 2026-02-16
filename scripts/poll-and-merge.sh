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
#   2 = timed out waiting for checks

set -euo pipefail

if [ $# -eq 0 ]; then
    echo "Usage: $0 <pr_number> [pr_number ...]"
    exit 1
fi

POLL_INTERVAL=10
MAX_DURATION=${MAX_DURATION:-1800}  # 30 minutes default
MAX_API_RETRIES=5                   # consecutive API errors before giving up
START_TIME=$(date +%s)
FAILED_PRS=()
MERGED_PRS=()
TIMED_OUT_PRS=()

is_transient_error() {
    local stderr_output="$1"
    # Match known transient GitHub API / network errors
    if echo "$stderr_output" | grep -qiE "i/o timeout|connection reset|connection refused|temporary failure|server error|502|503|504|ETIMEDOUT|ECONNRESET"; then
        return 0
    fi
    return 1
}

for pr in "$@"; do
    echo "Polling CI for PR #${pr}..."
    api_errors=0

    while true; do
        # Check overall timeout
        elapsed=$(( $(date +%s) - START_TIME ))
        if [ "$elapsed" -ge "$MAX_DURATION" ]; then
            echo "Timed out after ${elapsed}s waiting for PR #${pr}."
            TIMED_OUT_PRS+=("$pr")
            break
        fi

        # Capture both stdout and stderr separately
        stderr_file=$(mktemp)
        ec=0
        gh pr checks "$pr" 2>"$stderr_file" || ec=$?
        stderr_output=$(cat "$stderr_file")
        rm -f "$stderr_file"

        if [ $ec -eq 0 ]; then
            # All checks passed — merge
            echo "CI passed for PR #${pr}, merging..."
            if gh pr merge "$pr" --squash --delete-branch; then
                echo "PR #${pr} merged."
                MERGED_PRS+=("$pr")
            else
                # Merge might fail if already merged
                if gh pr view "$pr" --json state -q '.state' 2>/dev/null | grep -qi "MERGED"; then
                    echo "PR #${pr} was already merged."
                    MERGED_PRS+=("$pr")
                else
                    echo "Failed to merge PR #${pr}."
                    FAILED_PRS+=("$pr")
                fi
            fi
            break
        elif [ $ec -eq 8 ]; then
            # Checks still pending — reset API error counter and retry
            api_errors=0
            sleep "$POLL_INTERVAL"
        elif is_transient_error "$stderr_output"; then
            # Transient API/network error — retry with backoff
            api_errors=$((api_errors + 1))
            if [ "$api_errors" -ge "$MAX_API_RETRIES" ]; then
                echo "Too many consecutive API errors ($api_errors) for PR #${pr}."
                echo "Last error: $stderr_output"
                FAILED_PRS+=("$pr")
                break
            fi
            backoff=$((POLL_INTERVAL * api_errors))
            echo "Transient API error for PR #${pr} (attempt $api_errors/$MAX_API_RETRIES), retrying in ${backoff}s..."
            sleep "$backoff"
        else
            # Actual CI failure
            echo "CI failed for PR #${pr}."
            if [ -n "$stderr_output" ]; then
                echo "  stderr: $stderr_output"
            fi
            FAILED_PRS+=("$pr")
            break
        fi
    done
done

echo ""
echo "Results:"
[ ${#MERGED_PRS[@]} -gt 0 ] && echo "  Merged: ${MERGED_PRS[*]}"
[ ${#FAILED_PRS[@]} -gt 0 ] && echo "  Failed: ${FAILED_PRS[*]}"
[ ${#TIMED_OUT_PRS[@]} -gt 0 ] && echo "  Timed out: ${TIMED_OUT_PRS[*]}"

if [ ${#TIMED_OUT_PRS[@]} -gt 0 ]; then
    exit 2
fi
if [ ${#FAILED_PRS[@]} -gt 0 ]; then
    exit 1
fi
