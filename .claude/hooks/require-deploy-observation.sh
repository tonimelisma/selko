#!/usr/bin/env bash
# Stop hook: refuse to end a turn while a recent production deploy is unobserved.
#
# CLAUDE.md requires the T+0 and T+15m rows of docs/deploy-log/<date>-<sha>.md
# to be filled, and the log committed, before a deploy is reported done. That
# rule was written down and still broken repeatedly: agents ended the turn
# with "waiting for T+15m" and nothing ever came back to fill the row
# (2026-08-30 x2, 2026-11-01 66a8b867). A rule an agent can forget is not a
# gate; this hook is.
#
# Scope: only logs dated today or yesterday (UTC), so old history never blocks.
# A row is filled when any cell after the window name has text. "missed — ..."
# is an honest value when the window has passed unobserved.
set -euo pipefail

cd "${CLAUDE_PROJECT_DIR:-.}"

today=$(date -u +%Y-%m-%d)
yesterday=$(date -u -v-1d +%Y-%m-%d 2>/dev/null || date -u -d yesterday +%Y-%m-%d)

problems=()
for log in docs/deploy-log/"$today"-*.md docs/deploy-log/"$yesterday"-*.md; do
	[[ -f "$log" ]] || continue
	for window in 'T+0' 'T+15m'; do
		# First cell names the window, optionally annotated: "T+0 (05:03 UTC)".
		# 0 = row present and some later cell has text; 1 = missing or blank.
		# The 15-minute window counts when observed at any T+<n>m with n >= 10
		# ("T+14m", "T+22m"): what matters is that someone looked.
		filled=$(awk -F'|' -v w="$window" '
			{ label = $2; gsub(/^ +| +$/, "", label) }
			function minutes(l) { if (match(l, /^T\+[0-9]+m/)) return substr(l, 3, RLENGTH - 3) + 0; return -1 }
			label == w || index(label, w " ") == 1 || index(label, w "(") == 1 || (w == "T+15m" && minutes(label) >= 10) {
				found = 1
				for (i = 3; i < NF; i++) { cell = $i; gsub(/ /, "", cell); if (cell != "") { print 0; exit } }
			}
			END { if (!found || NR) print 1 }' "$log" | head -n1)
		if [[ "$filled" != 0 ]]; then
			problems+=("$log: the $window row is empty")
		fi
	done
	if [[ -n "$(git status --porcelain -- "$log")" ]]; then
		problems+=("$log: not committed")
	fi
done

if ((${#problems[@]} == 0)); then
	exit 0
fi

{
	echo "A production deploy is not finished; do not end the turn."
	printf '  - %s\n' "${problems[@]}"
	echo "Run ./scripts/check-production-health.sh when the window is due (wait inside this turn with Monitor, not a background sleep), fill the row, then commit and push the log."
	echo "If a window already passed unobserved, write 'missed' plus the first later observation; never leave it blank."
} >&2
exit 2
