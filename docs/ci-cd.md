# CI/CD Pipeline

The CI/CD pipeline ensures code quality and manages deployments across three environments.

## Overview

| Environment | Database | Deployment | Purpose |
|-------------|----------|------------|---------|
| **Development (local)** | Local Docker (`supabase start`, in the cloud VM or on the Mac) | — | Fast iteration with isolated database |
| **Staging** | Hosted Supabase (**paused**, owner decision) | `deploy-staging` on main push while the project runs; `staging-tier2` operation on request | Pre-production validation with real services |
| **Production** | Hosted Supabase | `deploy-production` operation, after the owner's explicit yes | Live environment |

Two workflows run on GitHub-hosted runners (the repo is public, so minutes
cost nothing): `test.yml` and `frontend-tests.yml` on pushes and PRs, and
`ops.yml` for every operation that needs a credential or a network path a
cloud session lacks (Postgres over TCP, the production database password,
Render deploy hooks, KVM). CI is never a merge gate — the lanes are
(`CLAUDE.md` → "The verification process") — but it is never left red.

## Pipeline Flow

### On Pull Request

```
PR opened/updated
    |
    +-- Unit Tests (backend, path-filtered)
    +-- Android Unit Tests (Gradle, path-filtered)
    +-- Frontend Unit Tests + build + svelte-check (frontend-tests.yml)
    |
No deployment
```

### On Push to Main

```
Merged with merge-and-cleanup.sh (squash, REST; never waits on CI)
    |
    +-- Same unit/Android/frontend jobs
    +-- deploy-staging (backend/supabase changes):
          staging paused  -> warning "Tier 2 NOT run", nothing verified, job green
          staging running -> migrations, deploy hook, served revision, staging suite
          status unknown  -> red (missing token / API down is not "paused")
```

### To Production (ops.yml, after the owner's yes)

```
./scripts/ops.py dispatch schema-compat            # the prod-gate lane: db push --dry-run
    |
Owner says yes for <sha> (main's tip)
    |
./scripts/ops.py dispatch deploy-production sha=<sha> confirm="deploy <sha>"
    |-- refuses unless <sha> is main's tip (Render's hook builds the branch tip)
    |-- supabase db push --dry-run, supabase db push
    |-- assert-schema-code-compat.sh --linked (R5)
    |-- Render deploy hooks (App, Web)
    |-- waits until api.selkoapp.com/health serves <sha>
    |-- check-production-health.sh (T+0)
```

## Critical Deployment Principle: Atomic Updates

**Database and application MUST deploy together.**

**Why:** Breaking changes require synchronized deployment:
- New code expecting new schema -> 500 errors if schema not updated
- New schema with old code -> potential issues if not backward compatible

**Implementation:** `deploy-production` runs migrations first, then deploys the
application. If any migration step fails, the deploy hooks never fire.

## GitHub Actions Jobs

### test.yml / frontend-tests.yml (push, PR)

| Job | Runs On | Path Filter | Purpose |
|-----|---------|-------------|---------|
| `unit-tests` | Every push/PR | `backend/**`, `cli/**`, `pyproject.toml`, `uv.lock` | Backend unit tests, no external services |
| `android-unit-tests` | Every push/PR | `android/**` | Android unit tests via Gradle |
| `unit-tests` / `build` (frontend-tests.yml) | Every push/PR | `frontend/**` | Frontend unit + build + svelte-check |
| `deploy-staging` | Main push only | `backend/**` or `supabase/**` | Deploy + verify staging while it runs; reports "paused" otherwise |

### ops.yml (repository_dispatch, typed by `scripts/ops.py`)

| Operation | What it does | Writes |
|-----------|--------------|--------|
| `schema-compat` | `target=production\|staging`, `when=pre-deploy` (`db push --dry-run`) or `post-deploy` (R5) | nothing |
| `deploy-production` | The production deploy above | production DB + services |
| `rehearse-cutover` | `rehearse_cutover.py --production-url … [--faithful]` on the runner's local Supabase | nothing in production |
| `repair-review-queue` | `repair_review_queue_integrity.py` dry run; `apply=true` needs `confirm_user` and `confirm="apply <uuid>"` plus the owner's yes | production only with apply |
| `staging-tier2` | `verify-staging.sh` with the worker drill (`require_workers`) | staging |
| `android-emulator` | `connectedDebugAndroidTest` + `capture-all-screenshots.sh android` on a KVM emulator; screenshots as an artifact | nothing |

The `request` job validates the payload (`scripts/ops.py validate`) before any
job that holds a secret starts; production jobs share the `production`
concurrency group and are never cancelled mid-run. Every operation is also
startable from the Actions tab (`workflow_dispatch`, same JSON payload).

**Logs are public.** Steps that read production print counts, versions and
migration names, and pipe through `scripts/ops.py redact`.

## Required GitHub Secrets

Configure at: Repository -> Settings -> Secrets and variables -> Actions. The
full list, including the ones the ops operations added, is "Owner setup" in
`CLAUDE.md`. Each job checks the secrets it needs and names the missing one.

**Note on naming:** GitHub secrets use `STAGING_*`/`PRODUCTION_*` prefixes; the
workflows map them to the unprefixed variables the code expects
(`TEST_USER_EMAIL`, `SUPABASE_DB_URL`, …).

## Session vs Actions

### Cloud session (the default) or the Mac
- `.env` for the local stack only (`scripts/cloud-setup.sh` writes it in a
  cloud VM); no hosted credential
- Tier 1 (`./scripts/verify.sh backend`) and every VM lane run here
- Hosted-environment work is dispatched: `./scripts/ops.py dispatch <operation>`

### GitHub Actions
- Hosted credentials live only here, as Actions secrets
- `ops.yml` operations and the push/PR test jobs

## Deployment Commands

```bash
# 0. The prod-gate lane (also run by ./scripts/verify-lanes.py --gate prod):
#    production accepts this tree's migrations. A non-zero exit BLOCKS the
#    deploy -- never proceed past it, never make it pass without verifying.
./scripts/ops.py dispatch schema-compat

# 1. After the owner's explicit yes for <sha> (main's tip):
./scripts/ops.py dispatch deploy-production sha=<sha> confirm="deploy <sha>"

# 2. Observe (deploy-log T+15m, T+24h):
./scripts/check-production-health.sh
uv run python scripts/smoke-ingestion.py --base-url https://api.selkoapp.com
```

Render does **not** deploy on push or tag: production changes only through the
deploy hooks in `deploy-production`.

### Production still requires explicit approval

An AI agent must **ask** before any prod deploy, with the `--gate prod` lane
table attached, and only proceed on an explicit yes for that SHA. Once the
owner says yes, a disclosed staging failure does not create another approval
gate.

## Merge Workflow

### CI is never a gate — the lanes are

Verification is Tier 1 (`./scripts/verify.sh backend`, in the session) before
merge and Tier 2 (`./scripts/ops.py dispatch staging-tier2`) after — paused
with staging today. Merges use `merge-and-cleanup.sh` and never wait on CI. If
CI on the merge commit fails, fix forward.

### Default: merge-and-cleanup.sh

```bash
# Step 1: Create the PR (REST; `gh pr create` needs GraphQL, refused in cloud sessions)
gh api repos/tonimelisma/selko/pulls -f head=<branch> -f base=main -f title="..." -f body="..." --jq .number

# Step 2: Merge (no CI gate) and clean up
./scripts/merge-and-cleanup.sh <pr_number>
```

The script:
1. **Squash-merges** the PR over REST (GitHub deletes the remote branch: "Automatically delete head branches" is on)
2. Cloud session: **moves the clone** onto the merged `main` and deletes the local branch
3. Mac: **fast-forwards** `main`, **removes the worktree** (never `--force`), deletes the local branch, prunes

Required PR checks (informational): `unit-tests`, `android-unit-tests`, `frontend-unit-tests`.

### Troubleshooting

```bash
# Runs on main, then the jobs of one run, then a failed job's log
gh api "repos/tonimelisma/selko/actions/runs?branch=main&per_page=3" --jq '.workflow_runs[] | [.id,.name,.conclusion] | @tsv'
gh api repos/tonimelisma/selko/actions/runs/<run_id>/jobs --jq '.jobs[] | [.id,.name,.conclusion] | @tsv'
gh api repos/tonimelisma/selko/actions/jobs/<job_id>/logs | tail -80

# After fixing, push and re-run the lane (or the operation)
git push
```

Common issues:
- **Merge conflicts:** `git fetch origin main && git merge origin/main`, resolve, push, re-run `merge-and-cleanup.sh`
- **A missing Actions secret:** the job names it; add it (Owner setup in `CLAUDE.md`)
- **Expired Google OAuth tokens** (`RefreshError: invalid_grant`): `uv run python -m cli.cli_seed_tokens --sync --provider gmail` (dev ↔ staging; only if both are stale, re-auth one side then re-run `--sync`)

### Email Notifications

GitHub sends automatic email notifications when:
- CI workflow fails on your branch
- A PR you authored has a failed check

Ensure notifications are enabled in your personal GitHub settings:
Settings → Notifications → Actions → "Send notifications for failed workflows only"

### Ingestion health and alerting

Point the Render health check at **`GET /health/ingestion`** (not `/health`). The
base `/health` returns `ok` unconditionally, so it stays green while every
ingestion loop is dead. `/health/ingestion` reports live per-task state plus
due/lease/pending/dead-letter counts and open email-sync incidents; its
`status` field is:

- `ok` — every managed task alive, no dead letters, no open incidents, oldest
  pending poll inside the warning SLO;
- `degraded` — DB queries failed, OR any dead letters / open incidents, OR the
  oldest pending poll is past `EMAIL_HEALTH_WARNING_SECONDS`;
- `down` — any managed task is not alive (the watchdog respawned it within one
  tick, but an outage continued past that would surface here).

`/health/ingestion` is currently the **only alerting surface** for ingestion.
`OPERATIONAL_NOTIFICATION_*` (Resend) is unset and no Resend account is
provisioned, so `operational_incidents` rows are recorded but never emailed.
Two paths to alert a human:

1. Provision Resend and set `OPERATIONAL_NOTIFICATION_*` (the
   `ResendOperationalNotifier` is already wired);
2. Configure Sentry (`SENTRY_DSN`) so the watchdog's `capture_exception` on an
   unexpectedly-exited task reaches an operator and `/health/ingestion` stays
   the SLO probe.

The structured `ingestion_sync_run` log line (`run_kind`, `provider`,
`duration_ms`, `provider_ids_seen`, `items_inserted`, `items_existing`,
`error_code`) is emitted once per completed sync run, so Render log search can
answer "is ingestion moving" without a metrics backend. Never logs subjects,
addresses, message ids or tokens.

### Parallel Agent Workflow

When multiple agents work simultaneously, they use git worktrees for isolation. See `docs/parallel-agents.md` for the complete guide covering:
- Creating worktrees with feature branches
- PR workflow (REST in cloud sessions)
- Rebasing after other agents merge
- Conflict resolution strategies

## Related Documentation

- [PRD_ARCH.md](../PRD_ARCH.md) Part 3 - Render deployment configuration
- [PRD_ARCH.md](../PRD_ARCH.md) Part 4 - Testing strategy details
- [parallel-agents.md](parallel-agents.md) - Multi-agent workflow guide
