#!/usr/bin/env bash
# The image lane: ./scripts/image-lane.sh [IMAGE IMPORTER_IMAGE]
#
# Without arguments it builds both (scripts/build-image.sh: selko:lane and,
# with --target importer, selko-import:lane). Then it starts a throwaway
# Postgres container, loads the frozen pre-move schema and synthetic rows from
# selko_import/fixture, imports them with the importer image, and runs
# scripts/image-check.sh on IMAGE with that database.
# CI (.github/workflows/image.yml) runs the same script on the image it then
# pushes and signs. Everything it starts is removed on exit, pass or fail.
set -euo pipefail
cd "$(dirname "$0")/.."

IMAGE="${1:-}"
IMPORTER="${2:-}"
if [[ -z "$IMAGE" ]]; then
  IMAGE="selko:lane"
  ./scripts/build-image.sh "$IMAGE"
fi
if [[ -z "$IMPORTER" ]]; then
  IMPORTER="selko-import:lane"
  ./scripts/build-image.sh "$IMPORTER" importer
fi
POSTGRES_IMAGE="${SELKO_FIXTURE_POSTGRES_IMAGE:-public.ecr.aws/docker/library/postgres:17}"
PG="selko-fixture-pg-$$"
NET="selko-fixture-net-$$"
WORK="$(mktemp -d)"
cleanup() {
  docker rm -f "$PG" >/dev/null 2>&1 || true
  docker network rm "$NET" >/dev/null 2>&1 || true
  rm -rf "$WORK"
}
trap cleanup EXIT

docker network create "$NET" >/dev/null
docker run -d --name "$PG" --network "$NET" -e POSTGRES_PASSWORD=fixture "$POSTGRES_IMAGE" >/dev/null
for _ in $(seq 1 60); do
  docker exec "$PG" pg_isready -U postgres -h 127.0.0.1 >/dev/null 2>&1 && break
  sleep 1
done
docker exec "$PG" pg_isready -U postgres -h 127.0.0.1 >/dev/null || { echo "FAIL  the fixture Postgres did not start" >&2; exit 1; }
docker exec "$PG" psql -U postgres -v ON_ERROR_STOP=1 -q -c "CREATE DATABASE fixture"
cat selko_import/fixture/schema.sql selko_import/fixture/data.sql \
  | docker exec -i "$PG" psql -U postgres -d fixture -v ON_ERROR_STOP=1 -q

# The importer image, as the server runs it: non-root, read-only root, the
# source URL from a mounted file, writing only to the directory it is given.
mkdir "$WORK/secrets" "$WORK/import"
echo "postgresql://postgres:fixture@${PG}:5432/fixture" > "$WORK/secrets/source.url"
chmod 0755 "$WORK" "$WORK/secrets"
chmod 0644 "$WORK/secrets/source.url"
chmod 0777 "$WORK/import"   # the importer's uid 10001 writes here
docker run --rm --network "$NET" --read-only --tmpfs /tmp --cap-drop ALL --security-opt no-new-privileges \
  -v "$WORK/secrets:/secrets:ro" -v "$WORK/import:/out" "$IMPORTER" \
  database --source-url-file /secrets/source.url --target /out/selko.db
# selko.db is owned by the importer's uid 10001, the uid image-check copies it as.

./scripts/image-check.sh "$IMAGE" "$WORK/import/selko.db" fixture@example.test fixture-password
