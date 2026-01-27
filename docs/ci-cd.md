# CI/CD Pipeline

The CI/CD pipeline ensures code quality and manages deployments across three environments.

## Overview

| Environment | Database | Deployment | Purpose |
|-------------|----------|------------|---------|
| **Development** | Local Docker | Manual (local only) | Fast iteration with isolated database |
| **Staging** | Cloud Supabase | **Automatic on main push** | Pre-production validation with real services |
| **Production** | Cloud Supabase | Manual trigger only | Live environment (manual safety gate) |

## Pipeline Flow

### On Pull Request

```
PR opened/updated
    |
    +-- Unit Tests (no external dependencies)
    +-- Integration Tests (local Supabase via Docker)
    +-- Android Unit Tests (Gradle)
    |
All tests pass -> PR ready for review (no deployment)
```

### On Push to Main

```
Code merged to main
    |
    +-- Unit Tests (backend)
    +-- Integration Tests (local Supabase)
    +-- Android Unit Tests
    |
All tests pass
    |
Deploy to Staging (ATOMIC)
    |-- 1. Deploy database migrations (supabase db push)
    |-- 2. Deploy FastAPI to Render (auto-deploys via GitHub integration)
    |-- 3. Deploy frontend to Render (auto-deploys via GitHub integration)
    |
    +-- Integration Tests (Staging backend) - real Gmail API + real LLM
    +-- Frontend E2E Tests (Staging) - tests deployed frontend
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

| Job | Runs On | Dependencies | Purpose |
|-----|---------|--------------|---------|
| `unit-tests` | Every push/PR | None | Fast backend validation, no external services |
| `integration-tests-development` | Every push/PR | None | Spins up local Supabase in Docker |
| `android-unit-tests` | Every push/PR | None | Android unit tests via Gradle |
| `deploy-staging` | Main push only | unit-tests, integration-tests-development, android-unit-tests | Deploy DB + API + frontend to staging |
| `integration-tests-staging` | Main push only | deploy-staging | Validate deployed staging backend with real LLM |
| `frontend-e2e-staging` | Main push only | deploy-staging | E2E tests against deployed staging frontend |
| `deploy-production` | Manual/tag only | None | Deploy DB + API to production |

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

### GitHub Actions
- Uses GitHub Secrets mapped to environment variables
- Automatic deployment on main push (staging only)
- Ephemeral Supabase instances for dev tests

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

```bash
# Option 1: Manual workflow dispatch
gh workflow run test.yml

# Option 2: Create and push a tag
git tag -a v1.0.0 -m "Release 1.0.0"
git push origin v1.0.0
```

## Auto-Merge & CI Checks

### How Auto-Merge Works

PRs created with `--auto` flag wait for CI before merging:
```bash
gh pr create --title "..." --body "..." --auto
```

The PR will automatically merge once all status checks pass:
- `unit-tests`
- `integration-tests-development`
- `android-unit-tests`

**Important:** Without GitHub Pro, there's no branch protection. Manual merge is still possible before CI completes. Always use `--auto` to ensure CI passes first.

### Email Notifications

GitHub sends automatic email notifications when:
- CI workflow fails on your branch
- A PR you authored has a failed check

Ensure notifications are enabled in your personal GitHub settings:
Settings → Notifications → Actions → "Send notifications for failed workflows only"

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
