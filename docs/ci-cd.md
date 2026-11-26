# CI/CD Pipeline

Selko ships as one image: `ghcr.io/tonimelisma/selko:<sha>`, built, checked and
cosign-signed by GitHub Actions on `main`. Production runs that image on a
server that pulls it and verifies the signature; deployment itself lives
outside this repository.

| Environment | State | How it runs |
|-------------|-------|-------------|
| **Development** | A local `SELKO_DATA_DIR` (or a fresh file per test) | `uv run uvicorn selko.api.app:app`, the dev server, or the image via `scripts/image-lane.sh` |
| **Production** | `/data` on the server (`selko.db` + `attachments/`) | The signed image, read-only root, `/data` its only volume |

There is no staging environment. The image lane runs the exact image under the
server's limits and holds it to the production health invariants; that is what
stands in for "the shape that actually runs".

CI is never a merge gate — the lanes are (`CLAUDE.md` → "The verification
process") — but it is never left red. The repo is public, so runner minutes
cost nothing.

## Workflows

| Workflow | Runs on | Jobs |
|----------|---------|------|
| `test.yml` | push to `main`, PRs (path-filtered: `backend/**`, `scripts/seed_screenshot_data.py`, `pyproject.toml`, `uv.lock`) | `unit-tests`: the whole backend suite, unit + integration (SQLite needs no service) |
| `frontend-tests.yml` | push to `main`, PRs touching `frontend/**` | `unit-tests` (Vitest), `build` (build + `svelte-check`) |
| `image.yml` | push to `main`, PRs, manual; not for a change only to `docs/**`, `**/*.md`, `legacy/**` or `.verify/**` | `image`: build → `scripts/image-lane.sh` → on `main` only, push `:<sha>` unsigned; `release`: cosign-sign the digest, move `:main` (production follows it) |

## image.yml

```
image (every push and PR)
    docker build -t ghcr.io/tonimelisma/selko:<sha> .
        |
    scripts/image-lane.sh <image>
        |-- loads backend/tests/fixtures/imported_from_postgres.sql (the
        |   database the one-time importer made from the Postgres fixture)
        |-- scripts/image-check.sh: read-only root, --cap-drop ALL,
        |   no-new-privileges, 400 MB, /data the only volume; /health, health
        |   invariants, web shell, non-root, no Postgres/Supabase client, the
        |   data-directory lock, sign-up/sign-in/refresh, review + /live,
        |   attachment download, memory, the imported database
        |
    main only: docker push :<sha> (unsigned)

release (main only, after image passes)
    cosign sign --yes <digest>, cosign verify <digest>
    crane tag <digest> main  (:main is the signed digest itself,
                              asserted, and cosign verify passes on :main)
```

The image that is checked is the image that is pushed: one build, loaded into
the runner's Docker, checked, then pushed by digest. Nothing is pushed unless
every check passed. A merge to `main` is a release: the production server
follows `:main` and accepts only a signed digest:

```bash
cosign verify ghcr.io/tonimelisma/selko:main \
  --certificate-identity "https://github.com/tonimelisma/selko/.github/workflows/image.yml@refs/heads/main" \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

No secret is involved: the workflow's `GITHUB_TOKEN` pushes and GitHub's OIDC
token signs.

## Migrations

Migrations live in `backend/selko/db/migrations/` and apply when the process
opens the database (`selko.db.runtime.open_database`), before it serves: a
hash-checked ledger (`schema_migrations`), a `VACUUM INTO` backup in
`<data>/backups/` before each, foreign keys checked before commit. Schema and
code therefore always ship together, in one image. `python -m selko.admin
migrate` applies them without starting the server.

## Checking CI

```bash
gh api "repos/tonimelisma/selko/actions/runs?branch=main&per_page=3" \
  --jq '.workflow_runs[] | [.id,.name,.event,.conclusion] | @tsv'
gh api repos/tonimelisma/selko/actions/runs/<id>/jobs --jq '.jobs[] | [.id,.name,.conclusion] | @tsv'
gh api repos/tonimelisma/selko/actions/jobs/<job id>/logs | tail -80
```

## Production health

```bash
./scripts/check-production-health.sh          # api.selkoapp.com
./scripts/check-production-health.sh <url>    # any deployment, e.g. a local container
```

The invariants are in `scripts/assert-health.sh` (table in `CLAUDE.md`). Until
production is cut over to the signed image it runs the previous hosted-Postgres
build; its own assertions are `git show 7207aac5:scripts/assert-health.sh`.

## Historical

Before the move to SQLite (`docs/specs/sqlite-single-process/`), CI also
deployed a staging environment and `ops.yml` ran production deploys to Render
with Supabase migrations. Both are gone; `docs/deploy-log/` keeps the record.
