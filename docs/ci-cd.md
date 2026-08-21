# CI/CD Pipeline

The CI/CD pipeline ensures code quality and manages deployments across three environments.

## Overview

| Environment | Database | Deployment | Purpose |
|-------------|----------|------------|---------|
| **Development (local)** | Local Docker (`supabase start`) | Manual | Fast iteration with isolated database |
| **Staging** | Cloud Supabase | **Automatic on main push** | Pre-production validation with real services |
| **Production** | Cloud Supabase | Manual trigger only | Live environment (manual safety gate) |

## Pipeline Flow

### On Pull Request

```
PR opened/updated
    |
    +-- Unit Tests (backend, path-filtered)
    +-- Android Unit Tests (Gradle, path-filtered)
    +-- Frontend Unit Tests (Vitest, path-filtered)
    |
All tests pass -> PR ready for review (no deployment)
```

### On Push to Main (Tier 2 is local; CI is a bonus)

```
Code merged to main (via merge-and-cleanup.sh — never waits on CI)
    |
    +-- Tier 1 already ran before merge: ./scripts/verify.sh backend
    |
    +-- Bonus if minutes exist: GitHub runs same tests + bonus deploy/integration (may never run)
    |
    +-- You verify staging locally after merge (never via CI):
        |-- ./scripts/verify.sh staging
```

### To Production (local migration, explicit Render workflow)

```
You explicitly approve a production deployment
    |
    +-- Gate: ./scripts/assert-schema-code-compat.sh --linked
    |-- 1. supabase link --project-ref khahcozfbnpykspvatrg && supabase db push  (--dry-run first, review 11)
    |-- 2. Render deploy: gh workflow run test.yml -f staging_action=none -f deploy_production=true
    |-- 3. Verify: GET /health/ingestion == ok, /health/egress, Sentry synthetic, dead-letter 0
The production deploy job has no dependencies. Once it triggers both secret Render hooks successfully,
do not wait for unrelated test jobs in the same workflow run.
```

## Critical Deployment Principle: Atomic Updates

**Database and application MUST deploy together.**

**Why:** Breaking changes require synchronized deployment:
- New code expecting new schema -> 500 errors if schema not updated
- New schema with old code -> potential issues if not backward compatible

**Implementation:** Each deployment job runs migrations first, then deploys the application. If migrations fail, application deployment is skipped.

## GitHub Actions Jobs

| Job | Runs On | Path Filter | Dependencies | Purpose |
|-----|---------|-------------|--------------|---------|
| `unit-tests` | Every push/PR | `backend/**`, `cli/**`, `pyproject.toml`, `uv.lock` | None | Fast backend validation, no external services |
| `android-unit-tests` | Every push/PR | `android/**` | None | Android unit tests via Gradle |
| `frontend-unit-tests` | Every push/PR (frontend-tests.yml) | `frontend/**` | None | Frontend unit + build + svelte-check via dedicated workflow |
| `deploy-staging` | Main push only | `backend/**` or `supabase/**` | unit-tests, android-unit-tests, frontend-unit-tests | Deploy DB + API + frontend to staging |
| `integration-tests-staging` | Main push only | — | deploy-staging | Validate deployed staging backend (parallelized with pytest-xdist) |
| `manual-staging-action` | Manual only | — | None | Apply pending staging migrations or deploy and verify staging explicitly |
| `deploy-production` | Manual/tag only | — | None | Deploy DB + API to production |

### Manual workflow dispatch

`workflow_dispatch` is safe by default. Choose one `staging_action` at a time:

1. `apply-migrations` reviews and applies pending staging migrations.
2. `deploy` requires the migration gate to pass, then deploys and verifies the
   staging services and integration suite.

Production is not selected by a generic manual run. The `deploy_production`
checkbox must be explicitly enabled, or a version tag must be pushed.

## Required GitHub Secrets

Configure at: Repository -> Settings -> Secrets and variables -> Actions

| Secret | Purpose | How to Generate |
|--------|---------|-----------------|
| `SUPABASE_ACCESS_TOKEN` | Authenticate Supabase CLI for migrations | https://supabase.com/dashboard/account/tokens |
| `STAGING_SUPABASE_DB_PASSWORD` | Password-authenticated staging migration queries and pushes | Supabase project database settings |
| `STAGING_SUPABASE_DB_URL` | Session-pooler URL used by staging workers and acceptance drills | Supabase dashboard -> Connect -> Session pooler |
| `STAGING_SUPABASE_URL` | Staging database connection | Supabase dashboard |
| `STAGING_SUPABASE_ANON_KEY` | Staging API access | Supabase dashboard -> Settings -> API |
| `STAGING_SUPABASE_SERVICE_ROLE_KEY` | Staging admin operations | Supabase dashboard -> Settings -> API |
| `STAGING_TEST_USER_EMAIL` | Test user for staging integration tests | Burner Gmail account |
| `STAGING_TEST_USER_PASSWORD` | Test user password | Set when creating user |
| `GOOGLE_CLIENT_ID` | OAuth for Gmail integration | Google Cloud Console |
| `GOOGLE_CLIENT_SECRET` | OAuth secret | Google Cloud Console |

**Note on naming:** GitHub secrets use `STAGING_*` prefix to distinguish environments, but the workflow maps these to unprefixed environment variables (`TEST_USER_EMAIL`, etc.) that the code expects.

## Local vs CI Differences

### Local Development
- Uses `.env` file with `TEST_USER_EMAIL=test@selko.local`
- Manual deployment and verification (`./scripts/verify.sh staging`)
- Local Supabase via `supabase start`
- Unit and local integration tests run via `./scripts/verify.sh backend` as the Tier 1 DoD gate

### GitHub Actions
- Uses GitHub Secrets mapped to environment variables
- May run mocked/unit checks, but Actions minutes are not funded and workflows may never run
- The `deploy-staging` and `integration-tests-staging` jobs are not the live path; Tier 2 runs locally

## Deployment Commands

### Deploys without CI (the real path — staging and prod)

We never top up GitHub minutes. `supabase db push` is done from your machine.
Always run the R5 gate first — migrations before code, or Render boots head-ahead of schema.

```bash
# 0. Gate: code and migrations are in the right order.
#    --linked is the ONLY supported invocation (C8). A local-only check
#    proves nothing, so the script exits 1 without it. A non-zero exit
#    BLOCKS the deploy — never proceed past this step on a failure, and
#    never run it with a trick that makes it pass without verifying.
./scripts/assert-schema-code-compat.sh --linked

# 1a. Staging
supabase link --project-ref lxmysergoeaegxlyfzwk
supabase db push --dry-run   # review 11, then
supabase db push

# 1b. Production (same, different project)
supabase link --project-ref khahcozfbnpykspvatrg
supabase db push --dry-run
supabase db push

# 2. Render deploys on push/tag (GitHub integration) — no workflow_dispatch needed
# Verify after: curl $API/health/ingestion, $API/health/egress, scripts/smoke-ingestion.py
```



### Production still requires explicit approval

An AI agent must **ask** before any prod deploy — the last sentence of its DoD report is "Should I deploy this to production?" — and only proceed on an explicit yes. Once you say yes, a disclosed staging failure does not create another approval gate.

```bash
# Apply and verify production migrations locally.
./scripts/assert-schema-code-compat.sh --linked
supabase link --project-ref khahcozfbnpykspvatrg && supabase db push
# Trigger the dependency-free job that owns the secret Render hooks.
gh workflow run test.yml -f staging_action=none -f deploy_production=true
```

## Merge Workflow

### CI is never a gate, never funded — local tiers are the gate

We will never buy GitHub minutes. Verification is two local tiers: Tier 1
(`./scripts/verify.sh backend`) before merge and Tier 2
(`./scripts/verify.sh staging`) immediately after merge. Merges use
`merge-and-cleanup.sh` and never wait on CI — CI may be out of minutes, queued
forever, or absent. CI on the merge commit is a bonus safety net; if it never
runs, that's expected. If it does run and fails, fix forward.

### Default: merge-and-cleanup.sh

```bash
# Step 1: Create the PR
gh pr create --title "..." --body "..."

# Step 2: Merge (no CI gate) and fully clean up
./scripts/merge-and-cleanup.sh <pr_number>
```

The script:
1. **Squash-merges** the PR and deletes the remote branch
2. **Fast-forwards** local main to `origin/main`
3. **Removes the worktree** (never `--force`) and deletes the local branch
4. **Prunes** stale worktree refs

It never blocks on CI. Run it as your final step — the worktree is gone afterward.

### Deprecated: poll-and-merge.sh

`scripts/poll-and-merge.sh` polls `workflow_dispatch` — it needs minutes we will never buy. Use local verification instead: `./scripts/assert-schema-code-compat.sh`, `supabase db push --dry-run`, `GET /health/ingestion`, `GET /health/egress`, `scripts/smoke-ingestion.py`. Polling CI is deprecated; if CI does happen to run, you may glance at it as a bonus.

> **Note:** Auto-merge via branch protection requires GitHub Pro for private repos, so these scripts drive the merge instead.

Required PR checks (when CI runs): `unit-tests`, `android-unit-tests`, `frontend-unit-tests`. These are bonus checks; the local tiers are authoritative.

### Troubleshooting

If the script reports a failure:

```bash
# View failed workflow logs
gh run view <run_id> --log-failed

# After fixing, push and re-run
git push
./scripts/poll-and-merge.sh <pr_number>
```

Common issues:
- **Merge conflicts:** Rebase your branch and force-push, then re-run `merge-and-cleanup.sh`
- **Expired Google OAuth tokens** (`RefreshError: invalid_grant`): Run `uv run python -m cli.cli_seed_tokens --sync --provider gmail` (checks both dev and staging and copies working → stale; only if both stale, re-auth one side then re-run `--sync`). No workflow re-run needed — proceed locally

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
- PR workflow with auto-merge
- Rebasing after other agents merge
- Conflict resolution strategies

## Related Documentation

- [PRD_ARCH.md](../PRD_ARCH.md) Part 3 - Render deployment configuration
- [PRD_ARCH.md](../PRD_ARCH.md) Part 4 - Testing strategy details
- [parallel-agents.md](parallel-agents.md) - Multi-agent workflow guide
