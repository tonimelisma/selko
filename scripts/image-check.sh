#!/usr/bin/env bash
# The image's acceptance check: ./scripts/image-check.sh IMAGE [IMPORTED_DB [FIXTURE_EMAIL FIXTURE_PASSWORD]]
#
# Runs IMAGE the way the server runs it -- read-only root, no capabilities,
# no new privileges, a 400 MB memory limit, /data as the only volume, settings
# from an env file -- and checks, against the running container:
#   /health answers ok; the web shell is served; the process is not root and
#   cannot write outside /data; sign-up and sign-in work (refresh cookie
#   included); a demo event can be reviewed; the accept reaches a live stream;
#   the event's attachment downloads byte for byte; memory stays under the limit.
# With IMPORTED_DB (a selko.db made by selko_import), it starts a second
# container on a volume holding that file and checks it migrates, serves, and
# that the fixture account signs in with its carried password and sees its
# events.
#
# Every container and volume it creates is removed on exit, pass or fail.
set -euo pipefail

IMAGE="${1:?usage: image-check.sh IMAGE [IMPORTED_DB [FIXTURE_EMAIL FIXTURE_PASSWORD]]}"
IMPORTED_DB="${2:-}"
FIXTURE_EMAIL="${3:-}"
FIXTURE_PASSWORD="${4:-}"
RUN_ID="selko-check-$$"
WORK="$(mktemp -d)"
CONTAINERS=()
VOLUMES=()

cleanup() {
  for c in "${CONTAINERS[@]:-}"; do [[ -n "$c" ]] && docker rm -f "$c" >/dev/null 2>&1 || true; done
  for v in "${VOLUMES[@]:-}"; do [[ -n "$v" ]] && docker volume rm -f "$v" >/dev/null 2>&1 || true; done
  rm -rf "$WORK"
}
trap cleanup EXIT

pass() { printf 'PASS  %s\n' "$*"; }
fail() { printf 'FAIL  %s\n' "$*" >&2; [[ -n "${CURRENT:-}" ]] && docker logs --tail 40 "$CURRENT" >&2 || true; exit 1; }

free_port() { python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1",0)); print(s.getsockname()[1])'; }

# start NAME VOLUME -> sets CURRENT, BASE
start() {
  local name="$1" volume="$2" port
  port="$(free_port)"
  BASE="http://127.0.0.1:${port}"
  cat >"$WORK/$name.env" <<EOF
ENVIRONMENT=production
SELKO_JWT_SECRET=$(python3 -c 'import secrets; print(secrets.token_hex(32))')
ALLOWED_ORIGINS=${BASE}
ENABLE_BACKGROUND_PROCESSING=true
SELKO_ALLOW_DEMO_SEED=1
LLM_FALLBACK_PROVIDER=none
API_PUBLIC_URL=${BASE}
EOF
  docker run -d --name "$name" \
    --read-only --tmpfs /tmp:size=64m,mode=1777 \
    --cap-drop ALL --security-opt no-new-privileges \
    --memory 400m --memory-swap 400m --pids-limit 200 \
    -v "$volume:/data" --env-file "$WORK/$name.env" \
    -p "127.0.0.1:${port}:8000" "$IMAGE" >/dev/null
  CONTAINERS+=("$name")
  CURRENT="$name"
  for _ in $(seq 1 90); do
    if curl -fsS -o /dev/null "$BASE/health" 2>/dev/null; then return 0; fi
    [[ "$(docker inspect -f '{{.State.Running}}' "$name")" == "true" ]] || fail "$name exited during startup"
    sleep 1
  done
  fail "$name did not answer /health within 90 s"
}

json() { python3 -c "import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1], {}, {'d': d}))" "$1"; }

sign_in() { # sign_in EMAIL PASSWORD -> prints the access token, keeps the cookie in $WORK/cookies
  curl -fsS -c "$WORK/cookies" -b "$WORK/cookies" -H "Origin: $BASE" -H 'Content-Type: application/json' \
    -d "{\"grant_type\":\"password\",\"email\":\"$1\",\"password\":\"$2\"}" "$BASE/auth/token" | json 'd["access_token"]'
}

# --- 1. a fresh database ------------------------------------------------------

docker volume create "$RUN_ID-fresh" >/dev/null; VOLUMES+=("$RUN_ID-fresh")
start "$RUN_ID-fresh" "$RUN_ID-fresh"

health="$(curl -fsS "$BASE/health")"
[[ "$(json 'd["status"]' <<<"$health")" == "ok" ]] || fail "/health is not ok: $health"
[[ "$(json 'd.get("build_sha") or ""' <<<"$health")" =~ ^[0-9a-f]{40}$ ]] || fail "/health publishes no 40-character build SHA"
pass "/health ok on a fresh database (migrated at startup), build $(json 'd["build_sha"][:12]' <<<"$health")"

# The standard health invariants production is held to (CLAUDE.md), against
# this container: work state, ingestion tasks and listener, the SQLite transport.
./scripts/check-production-health.sh "$BASE" >"$WORK/invariants" 2>&1 || { cat "$WORK/invariants" >&2; fail "health invariants"; }
pass "health invariants (work state, ingestion, transport)"

curl -fsS "$BASE/" | grep -qi "<html" || fail "the web app shell is not served at /"
curl -fsS "$BASE/app/events/x" | grep -qi "<html" || fail "SPA routes do not get the app shell"
pass "web app served by the same process"

[[ "$(docker exec "$CURRENT" id -u)" != "0" ]] || fail "the process runs as root"
docker exec "$CURRENT" sh -c 'touch /app/x' 2>/dev/null && fail "the root filesystem is writable"
docker exec "$CURRENT" sh -c 'touch /data/.probe && rm /data/.probe' || fail "/data is not writable"
pass "non-root, read-only root, /data writable"

EMAIL="check-$$@example.test"
code="$(curl -sS -o /dev/null -w '%{http_code}' -H "Origin: $BASE" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$EMAIL\",\"password\":\"check-password\"}" "$BASE/auth/signup")"
[[ "$code" == "201" ]] || fail "sign-up answered $code"
TOKEN="$(sign_in "$EMAIL" check-password)" || fail "sign-in failed"
grep -q selko_refresh "$WORK/cookies" || fail "sign-in set no refresh cookie"
[[ "$(curl -fsS -H "Authorization: Bearer $TOKEN" "$BASE/auth/user" | json 'd["email"]')" == "$EMAIL" ]] || fail "/auth/user"
REFRESHED="$(curl -fsS -c "$WORK/cookies" -b "$WORK/cookies" -H "Origin: $BASE" -H 'Content-Type: application/json' \
  -d '{"grant_type":"refresh_token"}' "$BASE/auth/token" | json 'd["access_token"]')" || fail "refresh failed"
[[ -n "$REFRESHED" ]] || fail "refresh returned no token"
pass "sign-up, sign-in, refresh"

seeded="$(docker exec "$CURRENT" python -m selko.admin seed-demo "$EMAIL")" || fail "seed-demo"
EVENT="$(json 'd["event_id"]' <<<"$seeded")"; ATTACHMENT="$(json 'd["attachment_id"]' <<<"$seeded")"
curl -fsS -H "Authorization: Bearer $TOKEN" "$BASE/events/review" | grep -q "$EVENT" || fail "the event is not in the review queue"

curl -sN -H "Authorization: Bearer $TOKEN" "$BASE/live" >"$WORK/live" 2>/dev/null &
LIVE_PID=$!
for _ in $(seq 1 50); do grep -q "event: ready" "$WORK/live" && break; sleep 0.1; done
grep -q "event: ready" "$WORK/live" || fail "/live sent no ready frame"
[[ "$(curl -fsS -X POST -H "Authorization: Bearer $TOKEN" "$BASE/events/$EVENT/accept" | json 'd["review_status"]')" == "active" ]] \
  || fail "accept did not make the event active"
for _ in $(seq 1 50); do grep -q '"resource":"events"' "$WORK/live" && break; sleep 0.1; done
kill "$LIVE_PID" 2>/dev/null || true
grep -q '"resource":"events"' "$WORK/live" || fail "the accept did not reach the live stream"
pass "review: event accepted, live update delivered"

curl -fsS -H "Authorization: Bearer $TOKEN" "$BASE/attachments/$ATTACHMENT/content" -o "$WORK/ticket.pdf" || fail "attachment download"
head -c 8 "$WORK/ticket.pdf" | grep -q '%PDF' || fail "the downloaded attachment is not the stored file"
OTHER="other-$$@example.test"
curl -fsS -o /dev/null -H "Origin: $BASE" -H 'Content-Type: application/json' \
  -d "{\"email\":\"$OTHER\",\"password\":\"check-password\"}" "$BASE/auth/signup"
OTHER_TOKEN="$(sign_in "$OTHER" check-password)"
code="$(curl -sS -o /dev/null -w '%{http_code}' -H "Authorization: Bearer $OTHER_TOKEN" "$BASE/attachments/$ATTACHMENT/content")"
[[ "$code" == "404" ]] || fail "another user's download answered $code"
pass "attachment download (owner only)"

usage="$(docker stats --no-stream --format '{{.MemUsage}}' "$CURRENT")"
pass "memory $usage (limit 400 MiB)"

# --- 2. a database imported from Postgres -------------------------------------

if [[ -n "$IMPORTED_DB" ]]; then
  [[ -f "$IMPORTED_DB" ]] || fail "no imported database at $IMPORTED_DB"
  docker volume create "$RUN_ID-imported" >/dev/null; VOLUMES+=("$RUN_ID-imported")
  docker run --rm -v "$RUN_ID-imported:/data" -v "$(cd "$(dirname "$IMPORTED_DB")" && pwd):/src:ro" \
    --entrypoint sh "$IMAGE" -c "cp /src/$(basename "$IMPORTED_DB") /data/selko.db" \
    || fail "could not place the imported database"
  start "$RUN_ID-imported" "$RUN_ID-imported"
  [[ "$(curl -fsS "$BASE/health" | json 'd["status"]')" == "ok" ]] || fail "/health on the imported database"
  pass "imported database migrated and serves"
  if [[ -n "$FIXTURE_EMAIL" ]]; then
    TOKEN="$(sign_in "$FIXTURE_EMAIL" "$FIXTURE_PASSWORD")" || fail "the fixture account cannot sign in with its carried password"
    count="$(curl -fsS -H "Authorization: Bearer $TOKEN" "$BASE/events/activity?limit=500" | json 'd["total"]')"
    review="$(curl -fsS -H "Authorization: Bearer $TOKEN" "$BASE/events/review" | json 'len(d)')"
    (( review >= 1 )) || fail "the fixture's pending event is not in the review queue"
    (( count >= 1 )) || fail "the fixture's approved event is not in activity"
    pass "carried password signs in; $review to review, $count in activity"
  fi
fi

echo "ALL IMAGE CHECKS PASSED: $IMAGE"
