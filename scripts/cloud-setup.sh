#!/usr/bin/env bash
# SessionStart setup for Claude Code cloud sessions (claude.ai/code VMs).
#
# Runs only when CLAUDE_CODE_REMOTE=true; on any other machine it exits at once,
# so the hook costs nothing on Toni's Mac. It installs what the backend and web
# lanes need on Ubuntu 24.04, starts local Supabase in Docker, and writes the
# local-only .env files those lanes read. It never writes a credential for a
# hosted environment: .env holds the local Supabase demo keys and nothing else.
#
# Budget: Claude Code cancels a SessionStart hook after 600 s. Every step is
# idempotent and the slow one (supabase start: image pulls) runs detached, so
# a cancelled or timed-out hook leaves a stack that is still coming up rather
# than a half-installed machine. Re-run this script at any time to finish.
#
# Usage:
#   scripts/cloud-setup.sh            # full setup (the SessionStart hook)
#   scripts/cloud-setup.sh --db       # start local Supabase + write .env (foreground)
#   scripts/cloud-setup.sh --status   # report what is ready
set -uo pipefail

if [[ "${CLAUDE_CODE_REMOTE:-}" != "true" && "${SELKO_CLOUD_SETUP_FORCE:-}" != "1" ]]; then
	exit 0
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
mkdir -p .verify
LOG=".verify/cloud-setup.log"
DB_LOG=".verify/cloud-setup-db.log"
BUDGET_SECONDS="${SELKO_CLOUD_SETUP_BUDGET:-480}"
START=$SECONDS

# Pinned so a cloud session runs the same CLI the Mac does. Bump both together.
SUPABASE_CLI_VERSION="${SUPABASE_CLI_VERSION:-2.118.0}"
# Studio, its backend, log shipping and analytics: no lane uses them, and a
# failing health check on any of them tears down the whole stack (see
# docs/testing-guide.md and the local-supabase-start note).
SUPABASE_EXCLUDES="vector,logflare,studio,postgres-meta,imgproxy,edge-runtime,supavisor"

# Strictest "engines.node" in frontend/package-lock.json, and the build installed
# when the VM's Node is older.
NODE_MIN_VERSION="22.12.0"
NODE_PIN_VERSION="22.12.0"

SUDO=""
if [[ $EUID -ne 0 ]] && command -v sudo >/dev/null 2>&1; then
	SUDO="sudo -n"
fi

export PATH="$HOME/.local/node/bin:$HOME/.local/bin:/usr/local/bin:$PATH"

say() { printf '%s\n' "$*" | tee -a "$LOG"; }
step() { printf '[%3ss] %s\n' "$((SECONDS - START))" "$*" | tee -a "$LOG"; }
remaining() { echo $((BUDGET_SECONDS - (SECONDS - START))); }

persist_path() {
	# Later Bash tool calls start a fresh shell; CLAUDE_ENV_FILE is how a
	# SessionStart hook hands environment to them.
	if [[ -n "${CLAUDE_ENV_FILE:-}" ]]; then
		echo "export PATH=\"$HOME/.local/node/bin:$HOME/.local/bin:/usr/local/bin:\$PATH\"" >>"$CLAUDE_ENV_FILE"
	fi
}

apt_install() {
	local missing=()
	local pkg
	for pkg in "$@"; do
		command -v "$pkg" >/dev/null 2>&1 || missing+=("$pkg")
	done
	((${#missing[@]} == 0)) && return 0
	step "apt-get install ${missing[*]}"
	$SUDO apt-get update -qq >>"$LOG" 2>&1 || true
	DEBIAN_FRONTEND=noninteractive $SUDO apt-get install -y -qq "${missing[@]}" >>"$LOG" 2>&1
}

ensure_uv() {
	if ! command -v uv >/dev/null 2>&1; then
		step "installing uv from PyPI"
		python3 -m pip install --user --break-system-packages -q uv >>"$LOG" 2>&1 ||
			python3 -m pip install --user -q uv >>"$LOG" 2>&1
	fi
	step "uv sync (Python $(cat .python-version 2>/dev/null))"
	# uv fetches the interpreter pinned in .python-version from GitHub, which
	# the Limited network allows.
	uv sync --frozen >>"$LOG" 2>&1
}

ensure_supabase_cli() {
	if command -v supabase >/dev/null 2>&1 &&
		[[ "$(supabase --version 2>/dev/null | head -1)" == "$SUPABASE_CLI_VERSION" ]]; then
		return 0
	fi
	local arch
	case "$(uname -m)" in
	x86_64) arch=amd64 ;;
	aarch64 | arm64) arch=arm64 ;;
	*) say "unsupported architecture $(uname -m) for the Supabase CLI"; return 1 ;;
	esac
	step "installing Supabase CLI v${SUPABASE_CLI_VERSION} (${arch})"
	local tmp
	tmp="$(mktemp -d)"
	curl -fsSL -o "$tmp/supabase.tar.gz" \
		"https://github.com/supabase/cli/releases/download/v${SUPABASE_CLI_VERSION}/supabase_linux_${arch}.tar.gz" &&
		tar -xzf "$tmp/supabase.tar.gz" -C "$tmp" supabase &&
		mkdir -p "$HOME/.local/bin" &&
		install -m 0755 "$tmp/supabase" "$HOME/.local/bin/supabase"
	local status=$?
	rm -rf "$tmp"
	return $status
}

ensure_docker() {
	if docker info >/dev/null 2>&1; then
		return 0
	fi
	command -v dockerd >/dev/null 2>&1 || { say "dockerd not installed"; return 1; }
	step "starting dockerd"
	# Detached so it outlives this hook; it is the session's database host.
	$SUDO nohup setsid dockerd >/tmp/dockerd.log 2>&1 </dev/null &
	local _
	for _ in $(seq 1 30); do
		docker info >/dev/null 2>&1 && break
		$SUDO docker info >/dev/null 2>&1 && $SUDO chmod 666 /var/run/docker.sock 2>/dev/null && break
		sleep 1
	done
	docker info >/dev/null 2>&1
}

version_at_least() { # have want
	[[ "$(printf '%s\n%s\n' "$2" "$1" | sort -V | head -1)" == "$2" ]]
}

ensure_node() {
	# The frontend's native bindings (rolldown, lightningcss) declare
	# "node": "^20.19.0 || >=22.12.0", and npm *silently skips* an optional
	# package whose engine does not match, so `npm ci` on Node 22.11 succeeds
	# and the build then dies with "Cannot find module
	# '@rolldown/binding-linux-x64-gnu'". The cloud image ships "Node 20-22",
	# so check rather than assume.
	local have
	have="$(node -v 2>/dev/null | tr -d v)"
	if [[ -n "$have" ]] && version_at_least "$have" "$NODE_MIN_VERSION"; then
		return 0
	fi
	local arch
	case "$(uname -m)" in
	x86_64) arch=x64 ;;
	aarch64 | arm64) arch=arm64 ;;
	*) return 1 ;;
	esac
	step "Node ${have:-missing} is older than ${NODE_MIN_VERSION}; installing Node v${NODE_PIN_VERSION}"
	mkdir -p "$HOME/.local/node"
	curl -fsSL "https://nodejs.org/dist/v${NODE_PIN_VERSION}/node-v${NODE_PIN_VERSION}-linux-${arch}.tar.xz" |
		tar -xJ -C "$HOME/.local/node" --strip-components=1 || {
		say "could not download Node from nodejs.org (network policy?); the frontend lane needs Node >= ${NODE_MIN_VERSION}"
		return 1
	}
	export PATH="$HOME/.local/node/bin:$PATH"
	[[ -n "${CLAUDE_ENV_FILE:-}" ]] && echo "export PATH=\"$HOME/.local/node/bin:\$PATH\"" >>"$CLAUDE_ENV_FILE"
	version_at_least "$(node -v | tr -d v)" "$NODE_MIN_VERSION"
}

ensure_frontend() {
	ensure_node || return 1
	# Re-install when the lockfile changed or node_modules was built by another
	# Node: optional native packages chosen under the old one stay missing.
	if [[ ! -d frontend/node_modules ]] ||
		[[ frontend/package-lock.json -nt frontend/node_modules/.package-lock.json ]] ||
		[[ "$(cat frontend/node_modules/.selko-node-version 2>/dev/null)" != "$(node -v)" ]]; then
		step "npm ci (frontend, Node $(node -v))"
		npm --prefix frontend ci --no-audit --no-fund >>"$LOG" 2>&1 || return 1
		node -v >frontend/node_modules/.selko-node-version
	fi
	if [[ -n "${CHROME_PATH:-}" && -x "${CHROME_PATH}" ]]; then
		# playwright.config.ts launches $CHROME_PATH when it is set, so the
		# preinstalled Chrome for Testing is used and nothing is downloaded.
		return 0
	fi
	step "no \$CHROME_PATH; installing Playwright's own Chromium"
	(cd frontend && npx playwright install --with-deps chromium) >>"$LOG" 2>&1
}

supabase_healthy() {
	local db gw
	db="$(docker inspect -f '{{.State.Health.Status}}' supabase_db_selko 2>/dev/null)"
	gw="$(docker inspect -f '{{.State.Health.Status}}' supabase_kong_selko 2>/dev/null)"
	[[ "$db" == healthy && "$gw" == healthy ]]
}

start_supabase() {
	# Foreground. Pull failures on the default registry (public.ecr.aws) are
	# retried against Docker Hub and then GHCR, in case the session's network
	# policy allows only some of them.
	supabase_healthy && return 0
	local registry
	for registry in "" docker.io ghcr.io; do
		echo "supabase start (registry: ${registry:-default})"
		local registry_env=(env -u SUPABASE_INTERNAL_IMAGE_REGISTRY)
		[[ -n "$registry" ]] && registry_env=(env "SUPABASE_INTERNAL_IMAGE_REGISTRY=$registry")
		if "${registry_env[@]}" supabase start -x "$SUPABASE_EXCLUDES"; then
			return 0
		fi
		docker ps -aq --filter name=supabase_ | xargs -r docker rm -f >/dev/null 2>&1
	done
	return 1
}

write_env_files() {
	# Local-only values: the Supabase CLI's demo keys for the stack on this VM,
	# plus a throwaway test-user password. Never a hosted credential. Existing
	# files are kept, so an operator's hand-edited .env is never overwritten.
	local status_env
	status_env="$(supabase status -o env 2>/dev/null)" || return 1
	local api_url anon_key service_key db_url jwt_secret
	api_url="$(sed -n 's/^API_URL="\{0,1\}\([^"]*\)"\{0,1\}$/\1/p' <<<"$status_env")"
	anon_key="$(sed -n 's/^ANON_KEY="\{0,1\}\([^"]*\)"\{0,1\}$/\1/p' <<<"$status_env")"
	service_key="$(sed -n 's/^SERVICE_ROLE_KEY="\{0,1\}\([^"]*\)"\{0,1\}$/\1/p' <<<"$status_env")"
	db_url="$(sed -n 's/^DB_URL="\{0,1\}\([^"]*\)"\{0,1\}$/\1/p' <<<"$status_env")"
	jwt_secret="$(sed -n 's/^JWT_SECRET="\{0,1\}\([^"]*\)"\{0,1\}$/\1/p' <<<"$status_env")"
	[[ -n "$api_url" && -n "$anon_key" && -n "$service_key" && -n "$db_url" ]] || return 1

	if [[ ! -f .env ]]; then
		{
			echo "# Generated by scripts/cloud-setup.sh for this cloud VM's local Supabase."
			echo "# Local demo keys only; no hosted credential belongs in this file."
			grep -vE '^(SUPABASE_URL|SUPABASE_PUBLISHABLE_KEY|SUPABASE_SERVICE_ROLE_KEY|SUPABASE_DB_URL|SUPABASE_JWT_SECRET|SUPABASE_PROJECT_REF|SUPABASE_DB_PASSWORD|GOOGLE_CLIENT_ID|GOOGLE_CLIENT_SECRET|MICROSOFT_CLIENT_ID|MICROSOFT_CLIENT_SECRET|GEMINI_API_KEY|TEST_USER_EMAIL|TEST_USER_PASSWORD)=' .env.example
			echo "SUPABASE_URL=$api_url"
			echo "SUPABASE_PUBLISHABLE_KEY=$anon_key"
			echo "SUPABASE_SERVICE_ROLE_KEY=$service_key"
			echo "SUPABASE_DB_URL=$db_url"
			echo "SUPABASE_JWT_SECRET=$jwt_secret"
			echo "TEST_USER_EMAIL=test@selko.local"
			echo "TEST_USER_PASSWORD=$(openssl rand -hex 16)"
			# Non-functional placeholders, not credentials. Routes build the LLM
			# gateway and the OAuth sign-in URL before deciding anything, so
			# without a value they answer 500 and six integration tests fail for
			# a reason unrelated to the code. Nothing reaches a provider with
			# these: real-LLM tests need --run-llm and real-Gmail tests skip on
			# the missing token, and a real call would be refused as unauthorized.
			echo "ANTHROPIC_API_KEY=placeholder-cloud-session-not-a-key"
			echo "GOOGLE_CLIENT_ID=placeholder-cloud-session.apps.googleusercontent.com"
			echo "GOOGLE_CLIENT_SECRET=placeholder-cloud-session-not-a-secret"
			echo "MICROSOFT_CLIENT_ID=00000000-0000-0000-0000-000000000000"
			echo "MICROSOFT_CLIENT_SECRET=placeholder-cloud-session-not-a-secret"
		} >.env
		echo "wrote .env (local Supabase)"
	fi
	if [[ ! -f frontend/.env ]]; then
		{
			echo "# Generated by scripts/cloud-setup.sh for this cloud VM's local Supabase."
			echo "VITE_SUPABASE_URL=$api_url"
			echo "VITE_SUPABASE_ANON_KEY=$anon_key"
			echo "VITE_API_URL=http://localhost:8000"
		} >frontend/.env
		echo "wrote frontend/.env (local Supabase)"
	fi
}

report_status() {
	local ok=1
	command -v uv >/dev/null 2>&1 && [[ -d .venv ]] && say "  ready: uv + .venv ($(.venv/bin/python --version 2>&1))" || { say "  MISSING: uv/.venv"; ok=0; }
	command -v supabase >/dev/null 2>&1 && say "  ready: supabase CLI $(supabase --version 2>/dev/null | head -1)" || { say "  MISSING: supabase CLI"; ok=0; }
	[[ -d frontend/node_modules ]] && say "  ready: frontend/node_modules" || { say "  MISSING: frontend/node_modules"; ok=0; }
	if supabase_healthy; then
		say "  ready: local Supabase (db + gateway healthy)"
	else
		say "  NOT READY: local Supabase -- still starting (tail $DB_LOG) or failed; finish with: scripts/cloud-setup.sh --db"
		ok=0
	fi
	[[ -f .env ]] && say "  ready: .env" || { say "  MISSING: .env (written once Supabase is up)"; ok=0; }
	((ok == 1))
}

case "${1:-}" in
--db)
	ensure_docker || exit 1
	start_supabase || exit 1
	write_env_files
	exit $?
	;;
--status)
	report_status
	exit $?
	;;
"") ;;
*)
	echo "Usage: $0 [--db|--status]" >&2
	exit 2
	;;
esac

: >"$LOG"
step "Selko cloud setup (CLAUDE_CODE_REMOTE=true)"
persist_path
# On the Mac core.hooksPath lives in .git/config, which a fresh clone does not
# have, so without this the pre-commit test gate silently never runs here.
git config core.hooksPath .githooks
failed=()
apt_install jq lsof curl openssl || failed+=("apt")
ensure_docker || failed+=("docker")
ensure_supabase_cli || failed+=("supabase-cli")

# Start the database first: it is the slowest step (image pulls) and needs
# nothing else from this script, so it overlaps with uv and npm.
db_pid=""
if [[ ! " ${failed[*]} " =~ " docker " && ! " ${failed[*]} " =~ " supabase-cli " ]]; then
	step "starting local Supabase in the background (log: $DB_LOG)"
	nohup setsid "$0" --db >"$DB_LOG" 2>&1 </dev/null &
	db_pid=$!
fi

ensure_uv || failed+=("uv-sync")
ensure_frontend || failed+=("frontend")

if [[ -n "$db_pid" ]]; then
	while kill -0 "$db_pid" 2>/dev/null && (($(remaining) > 15)); do
		sleep 5
	done
	if kill -0 "$db_pid" 2>/dev/null; then
		step "Supabase is still starting; it keeps going after this hook (tail $DB_LOG)"
	elif ! wait "$db_pid"; then
		failed+=("supabase-start")
	fi
fi

step "done"
report_status
if ((${#failed[@]} > 0)); then
	say "FAILED steps: ${failed[*]} (details in $LOG / $DB_LOG). Re-run scripts/cloud-setup.sh after fixing."
fi
say "Cloud session notes: see 'Cloud sessions' in CLAUDE.md."
# Never fail the hook: a failed setup is reported above and in --status, and
# blocking session start would hide that report.
exit 0
