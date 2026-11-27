#!/usr/bin/env bash
# Fetch the LLM provider keys from Azure Key Vault for a cloud session.
#
# Cloud sessions run in one shared claude.ai environment whose only variable is
# MELISMA_SECRETS_CLIENT_SECRET: the client secret of the Entra app
# "cloud-sessions-reader", which may only read secrets in vault kv-melisma-dev
# (managed from the private repo tonimelisma/secrets). With that set, this
# gets a vault token (client credentials), reads each secret in SECRET_MAP and
# appends `export NAME='value'` to $CLAUDE_ENV_FILE, so every later Bash tool
# call has the keys. Without it, nothing happens and the session has no keys.
#
# No value and no token is ever printed or put on a command line (curl reads
# them from stdin and a mode-600 file). A failure names the secret and the
# HTTP status only.
#
# scripts/cloud-setup.sh sources this and calls fetch_cloud_secrets, which also
# exports the keys into its own shell. Run directly, it does the same for
# $CLAUDE_ENV_FILE (or only validates, when that is unset):
#   MELISMA_SECRETS_CLIENT_SECRET=… CLAUDE_ENV_FILE=/path scripts/fetch-cloud-secrets.sh

# Not secret: they name the app and the vault, the client secret grants access.
VAULT_TENANT_ID="00000000-0000-0000-0000-000000000000"
VAULT_CLIENT_ID="5154d2ee-bdf5-49cf-8643-8918b3e8c32c"
VAULT_URL="https://kv-melisma-dev.vault.azure.net"

# Environment variable = vault secret name. There is no xAI key.
SECRET_MAP=(
	SELKO_ANTHROPIC_API_KEY=selko-anthropic-api-key
	OPENAI_API_KEY=openai-api-key
	GEMINI_API_KEY=gemini-api-key
	ALIBABA_API_KEY=alibaba-api-key
	ZAI_API_KEY=zai-api-key
	META_MODEL_API_KEY=meta-model-api-key
	MOONSHOT_API_KEY=moonshot-api-key
	DEEPSEEK_API_KEY=deepseek-api-key
	MINIMAX_API_KEY=minimax-api-key
	TINKER_API_KEY=tinker-api-key
)

_vault_say() {
	if declare -F say >/dev/null; then say "$*"; else printf '%s\n' "$*" >&2; fi
}

# Runs in a subshell: writes `export` lines for the secrets it read to $1/exports.
_vault_fetch_into() {
	local dir="$1" status pair name secret failed=()
	umask 077
	set +x
	trap 'rm -f "$dir/body" "$dir/auth"' EXIT

	status=$(printf '%s' "$MELISMA_SECRETS_CLIENT_SECRET" | curl -sS --max-time 20 \
		-o "$dir/body" -w '%{http_code}' \
		--data-urlencode grant_type=client_credentials \
		--data-urlencode "client_id=$VAULT_CLIENT_ID" \
		--data-urlencode "client_secret@-" \
		--data-urlencode "scope=https://vault.azure.net/.default" \
		"https://login.microsoftonline.com/$VAULT_TENANT_ID/oauth2/v2.0/token" 2>/dev/null)
	if [[ "$status" != "200" ]] || ! python3 -I -c '
import json, sys
token = json.load(open(sys.argv[1])).get("access_token")
if not token:
    sys.exit(1)
open(sys.argv[2], "w").write("Authorization: Bearer " + token + "\n")
' "$dir/body" "$dir/auth" 2>/dev/null; then
		_vault_say "vault: token request failed (HTTP ${status:-000}); no LLM keys fetched"
		return 1
	fi

	for pair in "${SECRET_MAP[@]}"; do
		name="${pair%%=*}"
		secret="${pair#*=}"
		status=$(curl -sS --max-time 20 -o "$dir/body" -w '%{http_code}' -H "@$dir/auth" \
			"$VAULT_URL/secrets/$secret?api-version=7.4" 2>/dev/null)
		if [[ "$status" == "200" ]] && python3 -I -c '
import json, shlex, sys
value = json.load(open(sys.argv[1])).get("value")
if not value:
    sys.exit(1)
open(sys.argv[2], "a").write("export " + sys.argv[3] + "=" + shlex.quote(value) + "\n")
' "$dir/body" "$dir/exports" "$name" 2>/dev/null; then
			:
		else
			failed+=("$name ($secret): HTTP ${status:-000}")
		fi
	done
	if ((${#failed[@]} > 0)); then
		_vault_say "vault: could not fetch ${#failed[@]} of ${#SECRET_MAP[@]} keys:"
		local f
		for f in "${failed[@]}"; do _vault_say "  $f"; done
		return 1
	fi
	return 0
}

# Fetch the keys, export them here and append them to $CLAUDE_ENV_FILE.
# Returns 0 when MELISMA_SECRETS_CLIENT_SECRET is unset (nothing to do).
fetch_cloud_secrets() {
	[[ -n "${MELISMA_SECRETS_CLIENT_SECRET:-}" ]] || return 0
	local dir rc count=0
	dir="$(mktemp -d)" || return 1
	chmod 700 "$dir"
	(_vault_fetch_into "$dir")
	rc=$?
	if [[ -s "$dir/exports" ]]; then
		count=$(wc -l <"$dir/exports" | tr -d ' ')
		if [[ -n "${CLAUDE_ENV_FILE:-}" ]]; then
			cat "$dir/exports" >>"$CLAUDE_ENV_FILE"
		fi
		# shellcheck source=/dev/null
		. "$dir/exports"
	fi
	rm -rf "$dir"
	_vault_say "vault: fetched $count of ${#SECRET_MAP[@]} LLM keys from Azure Key Vault"
	return "$rc"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
	set -uo pipefail
	if [[ -z "${MELISMA_SECRETS_CLIENT_SECRET:-}" ]]; then
		echo "MELISMA_SECRETS_CLIENT_SECRET is not set; nothing to fetch" >&2
		exit 0
	fi
	fetch_cloud_secrets
fi
