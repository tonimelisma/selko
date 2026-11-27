#!/usr/bin/env bash
# SessionStart setup for Claude Code cloud sessions (claude.ai/code VMs).
#
# Runs only when CLAUDE_CODE_REMOTE=true; on any other machine it exits at once,
# so the hook costs nothing on Toni's Mac. It installs what the backend, web and
# image lanes need on Ubuntu 24.04 and writes the local-only .env files they
# read. The backend needs no database service: every test makes its own SQLite
# file. Docker is started for the image lane only. .env never holds a hosted
# credential: a random local signing key, a local data directory, placeholders.
#
# Budget: Claude Code cancels a SessionStart hook after 600 s. Every step is
# idempotent; re-run this script at any time to finish.
#
# Usage:
#   scripts/cloud-setup.sh            # full setup (the SessionStart hook)
#   scripts/cloud-setup.sh --status   # report what is ready
set -uo pipefail

if [[ "${CLAUDE_CODE_REMOTE:-}" != "true" && "${SELKO_CLOUD_SETUP_FORCE:-}" != "1" ]]; then
	exit 0
fi

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT" || exit 1
mkdir -p .verify
LOG=".verify/cloud-setup.log"
BUDGET_SECONDS="${SELKO_CLOUD_SETUP_BUDGET:-480}"
START=$SECONDS

# Strictest "engines.node" in frontend/package-lock.json, and the build installed
# when the VM's Node is older.
NODE_MIN_VERSION="22.12.0"
NODE_PIN_VERSION="22.12.0"

# The LLM keys come from Azure Key Vault, read by selko itself at startup
# (backend/selko/keyvault.py) with the client secret in the shared cloud
# environment's only variable, MELISMA_SECRETS_CLIENT_SECRET. Nothing here
# fetches them, exports them or writes them anywhere, and no `az` is needed.

SUDO=""
if [[ $EUID -ne 0 ]] && command -v sudo >/dev/null 2>&1; then
	SUDO="sudo -n"
fi

export PATH="$HOME/.local/node/bin:$HOME/.local/bin:/usr/local/bin:$PATH"

# The cloud image sets UV_NATIVE_TLS (trust the proxy's CA), which current uv
# deprecates with a warning on every command. UV_SYSTEM_CERTS is the same
# setting under its new name.
if [[ -n "${UV_NATIVE_TLS:-}" ]]; then
	export UV_SYSTEM_CERTS="$UV_NATIVE_TLS"
	unset UV_NATIVE_TLS
fi

say() { printf '%s\n' "$*" | tee -a "$LOG"; }
step() { printf '[%3ss] %s\n' "$((SECONDS - START))" "$*" | tee -a "$LOG"; }
remaining() { echo $((BUDGET_SECONDS - (SECONDS - START))); }

persist_path() {
	# Later Bash tool calls start a fresh shell; CLAUDE_ENV_FILE is how a
	# SessionStart hook hands environment to them.
	if [[ -n "${CLAUDE_ENV_FILE:-}" ]]; then
		echo "export PATH=\"$HOME/.local/node/bin:$HOME/.local/bin:/usr/local/bin:\$PATH\"" >>"$CLAUDE_ENV_FILE"
		if [[ -n "${UV_SYSTEM_CERTS:-}" ]]; then
			echo "export UV_SYSTEM_CERTS=\"$UV_SYSTEM_CERTS\"; unset UV_NATIVE_TLS" >>"$CLAUDE_ENV_FILE"
		fi
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
	# uv fetches the interpreter pinned in .python-version from GitHub. Verified
	# on an unrestricted cloud network only; the Limited policy is untested.
	uv sync --frozen >>"$LOG" 2>&1
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

write_env_files() {
	# Local-only values. Existing files are kept, so an operator's hand-edited
	# .env is never overwritten.
	if [[ ! -f .env ]]; then
		{
			echo "# Generated by scripts/cloud-setup.sh for this cloud VM."
			echo "# Local values only; no hosted credential belongs in this file."
			echo "SELKO_DATA_DIR=data"
			echo "SELKO_JWT_SECRET=$(openssl rand -hex 32)"
			echo "ALLOWED_ORIGINS=${CLOUD_ALLOWED_ORIGINS}"
			# Non-functional placeholders, not credentials. Routes build the LLM
			# gateway and the OAuth sign-in URL before deciding anything, so
			# without a value they answer 500. Nothing reaches a provider with
			# these: real-LLM tests need --run-llm, and a real call would be
			# refused as unauthorized. A set value wins over Key Vault, so the
			# Anthropic placeholder is written only when the session cannot read
			# the vault. The OAuth clients live in a vault this session's app
			# cannot read, so they always get one.
			[[ -n "${MELISMA_SECRETS_CLIENT_SECRET:-}" ]] || echo "ANTHROPIC_API_KEY=placeholder-cloud-session-not-a-key"
			echo "GOOGLE_CLIENT_ID=placeholder-cloud-session.apps.googleusercontent.com"
			echo "GOOGLE_CLIENT_SECRET=placeholder-cloud-session-not-a-secret"
			echo "MICROSOFT_CLIENT_ID=00000000-0000-0000-0000-000000000000"
			echo "MICROSOFT_CLIENT_SECRET=placeholder-cloud-session-not-a-secret"
		} >.env
		say "wrote .env (local values)"
	fi
	drop_shadowed_llm_placeholders
	upgrade_allowed_origins
	write_frontend_env
}

# The dev defaults (selko.config) plus the API port, which serves the built web
# app locally. The CORS integration tests send Origin localhost:3000 and
# 127.0.0.1:3000; leaving those out made the backend lane red in every session.
CLOUD_ALLOWED_ORIGINS="http://localhost:3000,http://localhost:5173,http://127.0.0.1:3000,http://127.0.0.1:5173,http://localhost:8000"
OLD_CLOUD_ALLOWED_ORIGINS="http://localhost:5173,http://localhost:8000"

upgrade_allowed_origins() {
	# Replace only the exact value earlier versions of this script wrote; a
	# hand-edited ALLOWED_ORIGINS is left alone.
	[[ -f .env ]] || return 0
	if grep -qxF "ALLOWED_ORIGINS=${OLD_CLOUD_ALLOWED_ORIGINS}" .env; then
		sed -i "s|^ALLOWED_ORIGINS=${OLD_CLOUD_ALLOWED_ORIGINS}\$|ALLOWED_ORIGINS=${CLOUD_ALLOWED_ORIGINS}|" .env
		echo "updated ALLOWED_ORIGINS in .env to include the dev defaults"
	fi
}

drop_shadowed_llm_placeholders() {
	# An .env written by an earlier version (or before the vault was
	# reachable) holds an Anthropic placeholder, which would win over the vault
	# key. Remove only that placeholder line; a hand-written value stays.
	[[ -f .env && -n "${MELISMA_SECRETS_CLIENT_SECRET:-}" ]] || return 0
	if grep -q "^ANTHROPIC_API_KEY=placeholder-" .env; then
		sed -i "/^ANTHROPIC_API_KEY=placeholder-/d" .env
		echo "dropped the ANTHROPIC_API_KEY placeholder from .env: selko reads the key from Key Vault"
	fi
}

write_frontend_env() {
	if [[ ! -f frontend/.env ]]; then
		{
			echo "# Generated by scripts/cloud-setup.sh: the dev server talks to the local API."
			echo "VITE_API_URL=http://localhost:8000"
		} >frontend/.env
		echo "wrote frontend/.env (local API)"
	fi
}

report_status() {
	local ok=1
	command -v uv >/dev/null 2>&1 && [[ -d .venv ]] && say "  ready: uv + .venv ($(.venv/bin/python --version 2>&1))" || { say "  MISSING: uv/.venv"; ok=0; }
	[[ -d frontend/node_modules ]] && say "  ready: frontend/node_modules" || { say "  MISSING: frontend/node_modules"; ok=0; }
	docker info >/dev/null 2>&1 && say "  ready: docker (the image lane)" || say "  note: docker is not running; only the image lane needs it"
	[[ -f .env ]] && say "  ready: .env" || { say "  MISSING: .env"; ok=0; }
	if [[ -z "${MELISMA_SECRETS_CLIENT_SECRET:-}" ]]; then
		say "  note: no MELISMA_SECRETS_CLIENT_SECRET; run_eval and --run-llm have no LLM keys (CLAUDE.md, Owner setup)"
	elif [[ -x .venv/bin/python ]]; then
		# selko's own loader, the way the app runs it; prints a count only.
		local readable
		readable="$(.venv/bin/python -c '
import os
from selko import keyvault
names = [n for n, (v, _) in keyvault.SECRETS.items() if v == keyvault.DEV_VAULT]
print(len(keyvault.fetch_missing(names, os.environ.get)), "of", len(names))' 2>/dev/null)"
		say "  vault: ${readable:-none} LLM keys readable from Key Vault"
	fi
	((ok == 1))
}

case "${1:-}" in
--status)
	# A query, not a setup step: print only. Appending here would add a second
	# set of "ready:" lines to the hook's log every time someone checks.
	LOG=/dev/null
	report_status
	exit $?
	;;
"") ;;
*)
	echo "Usage: $0 [--status]" >&2
	exit 2
	;;
esac

: >"$LOG"
step "Selko cloud setup (CLAUDE_CODE_REMOTE=true)"
failed=()
persist_path
# On the Mac core.hooksPath lives in .git/config, which a fresh clone does not
# have, so without this the pre-commit test gate silently never runs here.
git config core.hooksPath .githooks
apt_install jq lsof curl openssl || failed+=("apt")
ensure_docker || failed+=("docker")
ensure_uv || failed+=("uv-sync")
ensure_frontend || failed+=("frontend")
write_env_files || failed+=("env")

step "done"
report_status
if ((${#failed[@]} > 0)); then
	say "FAILED steps: ${failed[*]} (details in $LOG). Re-run scripts/cloud-setup.sh after fixing."
fi
say "Cloud session notes: see 'Cloud sessions' in CLAUDE.md."
# Never fail the hook: a failed setup is reported above and in --status, and
# blocking session start would hide that report.
exit 0
