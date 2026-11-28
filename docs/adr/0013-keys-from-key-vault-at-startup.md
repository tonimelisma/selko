# 0013. API keys are read from Azure Key Vault by the app at startup

- Status: accepted
- Date: 2026-11-28

## Context and problem

LLM provider keys and OAuth client secrets used to be copied into `.env` files and pushed to
each environment, where they went stale and leaked into shells. Requirements:
[SEL-745..751](../requirements/privacy.md).

## Decision drivers

- Keys live and rotate in one place.
- Nothing pushes or renders secrets.
- A missing key fails loudly, never passes.

## Considered options

### Each process reads what it needs from Key Vault when it starts (chosen)

- Good: rotation is a restart; no secret in the repository, CI or env files.
- Bad: startup depends on the vault.
- Failure modes: an unreadable key is absent, so the feature that needs it fails visibly.

### Render keys into env files at deploy time

- Good: no runtime dependency.
- Bad: copies everywhere.
- Failure modes: stale keys after rotation.

## Decision

`load_config()` hands the in-scope names it does not already have to `backend/selko/keyvault.py`,
which reads them in parallel once per process with Microsoft's SDK and logs only names and counts.
A variable already set always wins. The credential comes from `AZURE_TENANT_ID`, `AZURE_CLIENT_ID`,
`AZURE_CLIENT_SECRET` (the legacy cloud-session name `MELISMA_SECRETS_CLIENT_SECRET` is still
accepted as the secret); `SELKO_KEYVAULT_URL` holds the LLM provider keys and
`SELKO_KEYVAULT_HOSTS_URL` the OAuth clients; `SELKO_KEYVAULT_AUTH=gce` uses the server's workload
identity and `SELKO_KEYVAULT_AUTH=off` disables the fetch (the test suite sets it unless `--run-llm`).
`SELKO_JWT_SECRET` and the non-secret settings stay in the process environment.

## Consequences

Until the server's env file provides them, the production image carries the four non-secret
values from build arguments. Specific vault names, tenants and app registrations live in the
maintainer's secrets and server repositories, not here.

## Confirmation

`backend/tests/test_keyvault.py` (SEL-745..749).

## Retirement proof

Another secret store adopted for all of the maintainer's services.

## Reversal plan

Set the keys in the environment; a set variable already wins, so no code change is needed.
