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

### On Push to Main

```
Code merged to main
    |
    +-- Unit Tests (backend)
    +-- Android Unit Tests
    +-- Frontend Unit Tests
    |
All tests pass
    |
Deploy to Staging (ATOMIC)
    |-- 1. Deploy database migrations (supabase db push)
    |-- 2. Deploy FastAPI to Render (auto-deploys via GitHub integration)
    |-- 3. Deploy frontend to Render (auto-deploys via GitHub integration)
    |
    +-- Integration Tests (Staging backend) — real Supabase/Gmail OAuth;
        no LLM tests selected (use `--run-llm` locally for real LLM coverage)
    |
Staging environment running latest code
```

### On Manual Trigger or Git Tag

```
workflow_dispatch or tag push
    |
Deploy to Production (ATOMIC)
    |-- 1. Deploy database migrations (supabase db push)
    |-- 2. Deploy FastAPI to Render (manual deploy or auto-deploy on tag)
    |
(Optional) Production smoke tests (read-only)
    |
Production environment updated
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
| `deploy-production` | Manual/tag only | — | None | Deploy DB + API to production |

## Required GitHub Secrets

Configure at: Repository -> Settings -> Secrets and variables -> Actions

| Secret | Purpose | How to Generate |
|--------|---------|-----------------|
| `SUPABASE_ACCESS_TOKEN` | Authenticate Supabase CLI for migrations | https://supabase.com/dashboard/account/tokens |
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
- Manual deployment (`supabase db push`, `fly deploy`)
- Local Supabase via `supabase start`
- Development-marked integration tests run locally as part of the DoD

### GitHub Actions
- Uses GitHub Secrets mapped to environment variables
- Automatic deployment on main push (staging only)
- Integration tests run against staging Supabase after deployment

## Deployment Commands

### Manual Staging Deployment

```bash
# Link to staging
supabase link --project-ref lxmysergoeaegxlyfzwk

# Deploy migrations
supabase db push

# FastAPI auto-deploys to Render via GitHub integration
# See PRD_ARCH.md Part 3 for deployment details
```

### Manual Production Deployment

```bash
# Link to production
supabase link --project-ref khahcozfbnpykspvatrg

# Deploy migrations
supabase db push

# FastAPI deploys to Render (manual or auto on tag)
# See PRD_ARCH.md Part 3 for deployment details
```

### Trigger Production Deployment via GitHub

**Production deploys require explicit human approval.** Staging updates automatically on every merge to main; production never does. An AI agent must **ask the user** before triggering a prod deploy — the last sentence of its DoD report is "Should I deploy this to production?" — and only run the following on an explicit yes.

```bash
# Option 1: Manual workflow dispatch
gh workflow run test.yml

# Option 2: Create and push a tag
git tag -a v1.0.0 -m "Release 1.0.0"
git push origin v1.0.0
```

## Merge Workflow

### CI is a safety net, not a gate

Local, change-scoped tests are the gate (see the DoD scope table in `CLAUDE.md`). Merges do **not** wait on GitHub Actions — Actions minutes are limited and CI may not run at all. CI runs on the merge commit as a safety net; if it fails, fix forward with a follow-up PR.

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

### Optional: poll-and-merge.sh (verify CI before prod)

When you *do* want to confirm CI is green — e.g. before a production deploy — `scripts/poll-and-merge.sh <pr_number>` polls PR checks, merges, and watches the post-merge workflow (staging deploy + integration tests). It is optional and not part of the normal DoD.

> **Note:** Auto-merge via branch protection requires GitHub Pro for private repos, so these scripts drive the merge instead.

Required PR checks (when CI runs): `unit-tests`, `android-unit-tests`, `frontend-unit-tests`

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
- **Merge conflicts:** Rebase your branch and force-push, then re-run the script
- **Expired Google OAuth tokens** (`RefreshError: invalid_grant`): Ask user to run `ENVIRONMENT=staging uv run python -m cli.cli_auth_gmail`, then re-run the post-merge workflow

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
