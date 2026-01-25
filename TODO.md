# Manual Setup Tasks

This file contains step-by-step checklists for setting up each environment and deploying to production.

---

## Development Environment Setup

### 1. Prerequisites
- [ ] Install Python 3.10+
- [ ] Install [uv](https://github.com/astral-sh/uv) package manager
- [ ] Install [Supabase CLI](https://supabase.com/docs/guides/cli)
- [ ] Install Docker Desktop
- [ ] Clone repository: `git clone https://github.com/tonimelisma/selko.git`

### 2. Local Supabase Setup
- [ ] Run `supabase start` (starts Docker containers)
- [ ] Wait for startup to complete
- [ ] Verify Supabase Studio at http://127.0.0.1:54323
- [ ] Copy the output values (URL, anon key, service role key)

### 3. Environment Configuration
- [ ] Copy `.env.example` to `.env`
- [ ] Fill in local Supabase values from step 2:
  - [ ] `SUPABASE_URL` (e.g., `http://127.0.0.1:54321`)
  - [ ] `SUPABASE_PUBLISHABLE_KEY`
  - [ ] `SUPABASE_SERVICE_ROLE_KEY`
  - [ ] `SUPABASE_JWT_SECRET`

### 4. Create Test User
- [ ] Run: `uv run python -m cli.cli_user create --email test@selko.local --password testpass123`
- [ ] Add to `.env`:
  - [ ] `TEST_USER_EMAIL=test@selko.local`
  - [ ] `TEST_USER_PASSWORD=testpass123`

### 5. Google OAuth Setup (Local)
- [ ] Go to [Google Cloud Console](https://console.cloud.google.com/)
- [ ] Create a new project (or use existing)
- [ ] Enable the Gmail API (APIs & Services → Enable APIs → Gmail API)
- [ ] Configure OAuth consent screen (External or Internal)
- [ ] Create OAuth 2.0 credentials:
  - [ ] Application type: **Desktop app**
  - [ ] Download `credentials.json`
- [ ] Move `credentials.json` to `cli/` folder
- [ ] Add to `.env`:
  - [ ] `GOOGLE_CLIENT_ID`
  - [ ] `GOOGLE_CLIENT_SECRET`

### 6. Gmail Authentication
- [ ] Run: `uv run python -m cli.cli_auth_gmail`
- [ ] Complete OAuth flow in browser (log in with your Gmail account)
- [ ] Verify token stored: check `integrations` table in Supabase Studio

### 7. Verification
- [ ] Run unit tests: `uv run pytest backend/tests/ -m "not integration" -v`
- [ ] Run integration tests: `uv run pytest backend/tests/ -v`
- [ ] Fetch emails: `uv run python -m cli.cli_fetch_emails --max 5`
- [ ] Check emails in Supabase Studio (Table Editor → emails)

---

## Staging Environment Setup

### 1. Supabase Staging Project
- [ ] Project exists: `lxmysergoeaegxlyfzwk`
- [ ] URL: `https://lxmysergoeaegxlyfzwk.supabase.co`
- [ ] Note the anon key (Dashboard → Settings → API → Project API keys → anon public)
- [ ] Note the service role key (Dashboard → Settings → API → Project API keys → service_role)
- [ ] Note the JWT secret (Dashboard → Settings → API → JWT Settings → JWT Secret)

### 2. Create Burner Gmail Account
- [ ] Create a new Gmail account for staging tests (e.g., `selko-staging-test@gmail.com`)
- [ ] Use a strong password and store it securely
- [ ] Enable 2FA for security (optional but recommended)

### 3. Google Cloud Console Configuration
- [ ] Go to [Google Cloud Console](https://console.cloud.google.com/) → OAuth consent screen
- [ ] Add the burner Gmail account email to "Test users"
- [ ] **OR** Click "Publish App" to move to "In Production" (prevents 7-day token expiry)

### 4. Environment Configuration
- [ ] Create `.env.test` file
- [ ] Configure:
  - [ ] `SUPABASE_URL=https://lxmysergoeaegxlyfzwk.supabase.co`
  - [ ] `SUPABASE_PUBLISHABLE_KEY=<from step 1>`
  - [ ] `SUPABASE_SERVICE_ROLE_KEY=<from step 1>`
  - [ ] `SUPABASE_JWT_SECRET=<from step 1>`
  - [ ] `GOOGLE_CLIENT_ID=<from local setup>`
  - [ ] `GOOGLE_CLIENT_SECRET=<from local setup>`

### 5. Create Staging Test User
- [ ] Run: `ENVIRONMENT=staging uv run python -m cli.cli_user create --email <burner-email> --password <password>`
- [ ] Add to `.env.test`:
  - [ ] `TEST_USER_EMAIL=<burner-email>`
  - [ ] `TEST_USER_PASSWORD=<password>`

### 6. Initial OAuth Authorization
- [ ] Run: `ENVIRONMENT=staging uv run python -m cli.cli_auth_gmail`
- [ ] Complete OAuth flow with the **burner Gmail account**
- [ ] Verify tokens stored in staging Supabase (`integrations` table)

### 7. Prepare Test Emails (Optional)
For comprehensive tests, send a few emails to the burner account:
- [ ] Send a plain text email
- [ ] Send an email with attachments
- [ ] Star an email (to test `is_starred` flag)
- [ ] Mark an email as important (to test `is_important` flag)

### 8. GitHub Actions Secrets
Go to: Repository → Settings → Secrets and variables → Actions → New repository secret

**For Deployment (Required):**
- [ ] `SUPABASE_ACCESS_TOKEN` = Generate at https://supabase.com/dashboard/account/tokens (used for `supabase link` and `supabase db push`)

**For Staging Tests:**
- [ ] `STAGING_SUPABASE_URL` = `https://lxmysergoeaegxlyfzwk.supabase.co`
- [ ] `STAGING_SUPABASE_ANON_KEY` = (from Supabase dashboard > Settings > API > Anon key)
- [ ] `STAGING_SUPABASE_SERVICE_ROLE_KEY` = (from Supabase dashboard > Settings > API > Service role key)
- [ ] `STAGING_TEST_USER_EMAIL` = (burner email)
- [ ] `STAGING_TEST_USER_PASSWORD` = (burner password)

**For OAuth Integration:**
- [ ] `GOOGLE_CLIENT_ID` = (from Google Cloud Console)
- [ ] `GOOGLE_CLIENT_SECRET` = (from Google Cloud Console)

**For Render Deployment:**
- Render auto-deploys via GitHub integration - no secrets needed in GitHub

### 9. Verification
- [ ] Run staging tests: `ENVIRONMENT=staging uv run pytest backend/tests/integration/ -m "staging" -v`

---

## Production Environment Setup

### 1. Supabase Production Project
- [ ] Project exists: `khahcozfbnpykspvatrg`
- [ ] URL: `https://khahcozfbnpykspvatrg.supabase.co`
- [ ] Note the anon key (Dashboard → Settings → API)
- [ ] Note the service role key (Dashboard → Settings → API)
- [ ] Note the JWT secret (Dashboard → Settings → API → JWT Settings)

### 2. Apply Database Migrations
- [ ] Run: `supabase link --project-ref khahcozfbnpykspvatrg`
- [ ] Run: `supabase db push`
- [ ] Verify: `supabase migration list`

### 3. Environment Configuration
- [ ] Create `.env.production` file
- [ ] Configure:
  - [ ] `SUPABASE_URL=https://khahcozfbnpykspvatrg.supabase.co`
  - [ ] `SUPABASE_PUBLISHABLE_KEY=<from step 1>`
  - [ ] `SUPABASE_SERVICE_ROLE_KEY=<from step 1>`
  - [ ] `SUPABASE_JWT_SECRET=<from step 1>`
  - [ ] `GOOGLE_CLIENT_ID=<from Google Cloud Console>`
  - [ ] `GOOGLE_CLIENT_SECRET=<from Google Cloud Console>`

### 4. Create Production User
- [ ] Run: `ENVIRONMENT=production uv run python -m cli.cli_user create --email <your-email> --password <password>`
- [ ] Add to `.env.production`:
  - [ ] `TEST_USER_EMAIL=<your-email>`
  - [ ] `TEST_USER_PASSWORD=<password>`

### 5. OAuth Authorization (Production)
- [ ] Run: `ENVIRONMENT=production uv run python -m cli.cli_auth_gmail`
- [ ] Complete OAuth flow with your **real Gmail account**
- [ ] Verify tokens stored in production Supabase

### 6. Verification
- [ ] Test email fetch: `ENVIRONMENT=production uv run python -m cli.cli_fetch_emails --max 5`
- [ ] Check emails in Supabase dashboard

---

## Render Deployment Setup

See `RENDER_MIGRATION_PLAN.md` for the full migration plan.

### Prerequisites
- [ ] Create a Render account at https://render.com
- [ ] Connect your GitHub account to Render

### 1. Create Staging Web Service
- [ ] Go to Render Dashboard → New → Web Service
- [ ] Connect the `tonimelisma/selko` repository
- [ ] Configure:
  - **Name:** `selko-api-staging`
  - **Region:** Oregon (US West) or nearest to Supabase
  - **Branch:** `main`
  - **Root Directory:** (leave blank)
  - **Runtime:** Python 3
  - **Build Command:** `pip install uv && uv sync --no-dev`
  - **Start Command:** `uv run uvicorn selko.api.app:create_app --factory --host 0.0.0.0 --port $PORT`
  - **Plan:** Starter ($7/mo) or Free for testing
- [ ] Set environment variables:
  - `ENVIRONMENT=staging`
  - `SUPABASE_URL=https://lxmysergoeaegxlyfzwk.supabase.co`
  - `SUPABASE_PUBLISHABLE_KEY=<staging-anon-key>`
  - `SUPABASE_SERVICE_ROLE_KEY=<staging-service-role-key>`
  - `GOOGLE_CLIENT_ID=<from Google Cloud Console>`
  - `GOOGLE_CLIENT_SECRET=<from Google Cloud Console>`
- [ ] Deploy and verify: `curl https://selko-api-staging.onrender.com/health`

### 2. Create Production Web Service
- [ ] Create another Web Service with same settings but:
  - **Name:** `selko-api`
  - **Auto-Deploy:** Off (manual deploys only for production safety)
- [ ] Set environment variables with production values
- [ ] Deploy and verify: `curl https://selko-api.onrender.com/health`

### 3. GitHub Integration
Render auto-deploys from GitHub - no additional secrets or workflow steps needed.
- Staging: Auto-deploys on every push to `main`
- Production: Manual deploy from Render Dashboard (or configure auto-deploy on tags)

### 4. Update CORS Origins (When Adding Frontend)
When you have a frontend, add CORS configuration:
- [ ] Add `ALLOWED_ORIGINS` environment variable support in `app.py`
- [ ] Set `ALLOWED_ORIGINS` in Render environment variables

---

## CI/CD Pipeline Status

| Job | Trigger | Status |
|-----|---------|--------|
| Unit Tests | Every push/PR | ✅ Configured |
| Integration (Dev) | Every push/PR | ✅ Configured |
| Deploy Staging (DB) | Main only | ✅ Configured |
| Deploy Staging (API) | Main only | ✅ Auto-deploys via Render GitHub integration |
| Integration (Staging) | Main only (after deploy) | ✅ Configured |
| Deploy Production (DB) | Manual/tag | ✅ Configured |
| Deploy Production (API) | Manual/tag | ⬜ Manual deploy in Render Dashboard |

### How CI/CD Works

**Pull Requests:**
1. Unit Tests → Integration Tests (Dev with local Supabase)
2. No deployment on PRs

**Push to Main:**
1. Unit Tests → Integration Tests (Dev with local Supabase)
2. **Deploy to Staging** (DB migrations via GitHub Actions + API via Render auto-deploy)
3. Integration Tests (Staging) - validates deployed code
4. ✅ Staging environment now running latest code

**Manual Trigger or Git Tag:**
1. **Deploy to Production** (DB migrations via GitHub Actions)
2. Manually deploy API in Render Dashboard
3. Production smoke tests (read-only, optional)

### Deployment Details

| Job | Trigger | What it does |
|-----|---------|--------------|
| **Unit Tests** | Every push/PR | Fast tests, no external deps |
| **Integration (Dev)** | Every push/PR | Spins up local Supabase in Docker |
| **Deploy Staging** | Main branch only | 1. Deploy DB migrations (GitHub Actions)<br>2. API auto-deploys via Render |
| **Integration (Staging)** | Main branch only (after deploy) | Tests the deployed staging environment with real Gmail |
| **Deploy Production** | Manual workflow_dispatch or tag | 1. Deploy DB migrations (GitHub Actions)<br>2. Manually deploy API in Render |

### Important Notes

1. **OAuth tokens are in the database** - GitHub Actions doesn't need token files, just Supabase access
2. **Staging tests only on main** - Prevents burning through Gmail API quota on every PR
3. **Development tests spin up Supabase** - Uses `supabase start` in the workflow
4. **OAuth tokens auto-refresh** - After initial setup and OAuth app publication, no manual intervention needed
5. **Render auto-deploys staging** - No GitHub secrets needed for API deployment

---

## Quick Reference

### Environment Files
| File | Environment | Supabase |
|------|-------------|----------|
| `.env` | development | Local Docker |
| `.env.test` | staging | `lxmysergoeaegxlyfzwk.supabase.co` |
| `.env.production` | production | `khahcozfbnpykspvatrg.supabase.co` |

### Common Commands
```bash
# Switch environments using ENVIRONMENT variable (recommended)
ENVIRONMENT=development uv run python -m cli.cli_fetch_emails  # Local
ENVIRONMENT=staging uv run python -m cli.cli_fetch_emails      # Cloud staging
ENVIRONMENT=production uv run python -m cli.cli_fetch_emails   # Cloud production

# Alternative: Use --env flag
uv run python -m cli.cli_fetch_emails --env staging
```
