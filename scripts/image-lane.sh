#!/usr/bin/env bash
# The image lane: ./scripts/image-lane.sh [IMAGE]
#
# Without an argument it builds the image (scripts/build-image.sh selko:lane).
# Then it runs scripts/image-check.sh on IMAGE, against a fresh volume and
# against a database imported from Postgres: backend/tests/fixtures/
# imported_from_postgres.sql is the selko.db the one-time importer wrote from
# the frozen pre-move Postgres fixture (the importer itself was removed after
# the cutover). CI (.github/workflows/image.yml) runs the same script on the
# image it then pushes and signs. Everything it creates is removed on exit.
set -euo pipefail
cd "$(dirname "$0")/.."

IMAGE="${1:-}"
if [[ -z "$IMAGE" ]]; then
  IMAGE="selko:lane"
  ./scripts/build-image.sh "$IMAGE"
fi
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

mkdir "$WORK/import"
python3 - backend/tests/fixtures/imported_from_postgres.sql "$WORK/import/selko.db" <<'EOF'
import sqlite3, sys
with open(sys.argv[1], encoding="utf-8") as dump:
    sqlite3.connect(sys.argv[2]).executescript(dump.read())
EOF
chmod 0755 "$WORK" "$WORK/import"
chmod 0644 "$WORK/import/selko.db"   # image-check copies it into the volume as uid 10001

./scripts/image-check.sh "$IMAGE" "$WORK/import/selko.db" fixture@example.test fixture-password
