#!/usr/bin/env bash
# The image lane: ./scripts/image-lane.sh [IMAGE]
#
# Without IMAGE it builds one (scripts/build-image.sh, tagged selko:lane).
# Then it starts a throwaway Postgres container, loads the frozen pre-move
# schema and synthetic rows from selko_import/fixture, imports them with
# selko_import, and runs scripts/image-check.sh on IMAGE with that database.
# CI (.github/workflows/image.yml) runs the same script on the image it then
# pushes and signs. Everything it starts is removed on exit, pass or fail.
set -euo pipefail
cd "$(dirname "$0")/.."

IMAGE="${1:-}"
if [[ -z "$IMAGE" ]]; then
  IMAGE="selko:lane"
  ./scripts/build-image.sh "$IMAGE"
fi
POSTGRES_IMAGE="${SELKO_FIXTURE_POSTGRES_IMAGE:-public.ecr.aws/docker/library/postgres:17}"
PG="selko-fixture-pg-$$"
WORK="$(mktemp -d)"
cleanup() { docker rm -f "$PG" >/dev/null 2>&1 || true; rm -rf "$WORK"; }
trap cleanup EXIT

port="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])')"
docker run -d --name "$PG" -e POSTGRES_PASSWORD=fixture -p "127.0.0.1:${port}:5432" "$POSTGRES_IMAGE" >/dev/null
for _ in $(seq 1 60); do
  docker exec "$PG" pg_isready -U postgres -h 127.0.0.1 >/dev/null 2>&1 && break
  sleep 1
done
docker exec "$PG" pg_isready -U postgres -h 127.0.0.1 >/dev/null || { echo "FAIL  the fixture Postgres did not start" >&2; exit 1; }
docker exec "$PG" psql -U postgres -v ON_ERROR_STOP=1 -q -c "CREATE DATABASE fixture"
cat selko_import/fixture/schema.sql selko_import/fixture/data.sql \
  | docker exec -i "$PG" psql -U postgres -d fixture -v ON_ERROR_STOP=1 -q

(umask 077; echo "postgresql://postgres:fixture@127.0.0.1:${port}/fixture" > "$WORK/source.url")
mkdir "$WORK/import"
uv run python -m selko_import --source-url-file "$WORK/source.url" --target "$WORK/import/selko.db"
# The image's user (uid 10001) copies the file into its volume.
chmod 0755 "$WORK" "$WORK/import"
chmod 0644 "$WORK/import/selko.db"

./scripts/image-check.sh "$IMAGE" "$WORK/import/selko.db" fixture@example.test fixture-password
