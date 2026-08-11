#!/usr/bin/env bash
# Reject a newly-added migration whose version is not newer than every
# migration already on the base branch.
set -euo pipefail

BASE_REF="${1:-main}"

if ! git rev-parse --verify "$BASE_REF^{commit}" >/dev/null 2>&1; then
  echo "ERROR: base ref '$BASE_REF' does not resolve to a commit" >&2
  exit 1
fi

version_from_path() {
  basename "$1" | sed -nE 's/^([0-9]{14})_.+\.sql$/\1/p'
}

base_max=$(
  git ls-tree -r --name-only "$BASE_REF" -- supabase/migrations \
    | while IFS= read -r path; do version_from_path "$path"; done \
    | sort -n | tail -1
)

if [[ -z "$base_max" ]]; then
  echo "✅ No migrations exist on $BASE_REF; migration ordering is valid"
  exit 0
fi

violations=()
while IFS=$'\t' read -r change path _; do
  [[ "$change" == A* ]] || continue
  version=$(version_from_path "$path")
  [[ -n "$version" ]] || continue
  if ((10#$version <= 10#$base_max)); then
    violations+=("$path ($version <= base maximum $base_max)")
  fi
done < <(git diff --name-status "$BASE_REF...HEAD" -- supabase/migrations)

if ((${#violations[@]} > 0)); then
  echo "❌ FAIL: new migrations must be newer than every migration on $BASE_REF:" >&2
  printf '   %s\n' "${violations[@]}" >&2
  exit 1
fi

echo "✅ New migrations are ordered after $BASE_REF maximum ($base_max)"
