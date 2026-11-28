GOVERNS: .github/workflows/** Dockerfile .dockerignore scripts/build-image.sh scripts/image-lane.sh scripts/image-check.sh scripts/check-production-health.sh scripts/assert-health.sh

# CI, image and release

Selko ships as one image, `ghcr.io/tonimelisma/selko:<sha>`, built and checked by GitHub
Actions and cosign-signed on `main`. Production runs that image on a server that follows the
signed `:main` tag; deployment itself lives outside this repository. Production answers at
`https://api.selkoapp.com`. Decision: [ADR 0014](../adr/0014-merge-to-main-releases-a-signed-image.md).

| Environment | State | How it runs |
|-------------|-------|-------------|
| **Development** | A local `SELKO_DATA_DIR` (or a fresh file per test) | `uv run uvicorn selko.api.app:app`, the dev server, or the image via `scripts/image-lane.sh` |
| **Production** | `/data` on the server (`selko.db` + `attachments/`) | The signed image, read-only root, `/data` its only volume |

There is no staging environment. The image lane runs the exact image under the server's
limits and holds it to the production health invariants; that is what stands in for "the
shape that actually runs".

## Workflow `CI` (`.github/workflows/ci.yml`)

Runs on pull requests (including `edited`, so a fixed description re-runs the checks), on
pushes to `main`, on a weekly schedule and on dispatch.

| Job | What it does |
|-----|--------------|
| `changes` | Path filters decide which jobs have work; a scheduled or dispatched run runs everything |
| `backend` | The whole backend suite with pytest over SQLite (no database service) |
| `frontend-unit` | Web unit tests with coverage |
| `frontend-build` | The production build and `svelte-check` |
| `image` | Builds the image (with production's Key Vault settings from repository variables) and runs `scripts/image-lane.sh` on it, then checks inside the image that the `gce` credential and both vaults resolve; on a push to `main` whose diff touches the image's inputs, pushes `ghcr.io/tonimelisma/selko:<sha>` (unsigned) |
| `process` | `script/process-check` (requirements, `Validates:` tags, doc links) and `script/pr-check` (the PR description) |
| `CI gate` | Needs every other job and always reports; the one required check |

## Workflow `Image` (`.github/workflows/image.yml`)

Runs on `workflow_run` when `CI` completes successfully for a push to `main`.

```
release
    cosign sign --yes <digest of :<sha>>   (keyless, GitHub OIDC)
    move :main to that signed digest
        |
    the server follows :main within minutes and accepts only signed digests
        |
health
    poll https://api.selkoapp.com/health for up to 15 minutes until it answers
    with this commit, then run scripts/check-production-health.sh
    on failure: open an issue labelled deploy-failure
```

The signing identity is `.github/workflows/image.yml@refs/heads/main`, and the server
verifies exactly that:

```bash
cosign verify ghcr.io/tonimelisma/selko:main \
  --certificate-identity "https://github.com/tonimelisma/selko/.github/workflows/image.yml@refs/heads/main" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

Never rename `image.yml` or move the signing job: the server would refuse every new image.
No secret is involved: the workflow's `GITHUB_TOKEN` pushes and GitHub's OIDC token signs.
The image that is checked is the image that is pushed: one build, checked, then pushed by
digest; nothing is pushed unless every check passed. A merge that changes nothing the image
is built from pushes no image and releases nothing.

A `deploy-failure` issue is fixed first, like red CI. Nobody writes deploy-log entries any
more; `docs/deploy-log/` is the history from before the health job existed.

## Image settings

Until the server's env file provides them, the production image carries the four non-secret
Key Vault settings (`AZURE_TENANT_ID`, `AZURE_CLIENT_ID`, `SELKO_KEYVAULT_URL`,
`SELKO_KEYVAULT_HOSTS_URL`) from build arguments, set as repository Actions variables. A
variable already set in the environment always wins.

## Migrations

Migrations live in `backend/selko/db/migrations/` and apply when the process opens the
database (`selko.db.runtime.open_database`), before it serves: a hash-checked ledger
(`schema_migrations`), a `VACUUM INTO` backup in `<data>/backups/` before each, foreign keys
checked before commit. Schema and code therefore always ship together, in one image.
`python -m selko.admin migrate` applies them without starting the server.

## Checking CI

```bash
gh api "repos/tonimelisma/selko/actions/runs?branch=main&per_page=3" \
  --jq '.workflow_runs[] | [.id,.name,.event,.conclusion] | @tsv'
gh api repos/tonimelisma/selko/actions/runs/<id>/jobs --jq '.jobs[] | [.id,.name,.conclusion] | @tsv'
gh api repos/tonimelisma/selko/actions/jobs/<job id>/logs | tail -80
```

## Production health

```bash
./scripts/check-production-health.sh          # https://api.selkoapp.com
./scripts/check-production-health.sh <url>    # any deployment, e.g. a local container
```

The invariants are in `scripts/assert-health.sh`:

| Surface | Must hold |
|---|---|
| `work-state` | `items_dead_letter`, `attachments_dead_letter`, `stale_processing_emails`, `unclaimable_pending` are all zero, whatever the worker posture. `failed_emails` is not asserted: terminal failures are permanent history, and requiring them to be zero would make the check unsatisfiable after the first one |
| `ingestion` | status ok, background processing on, every task alive, the in-process work listener bound (`listener.kind == "in_process"`, `bound`) |
| `root` | publishes a 40-character build SHA (which build answered), and `requests.server_errors_per_hour` is zero: a deployment answering 5xx is not healthy, whatever its queues look like |
| `egress` | worker transport is `sqlite` |

The image lane runs the same script against the container it starts, so the image is held to
production's rules before it ships.
