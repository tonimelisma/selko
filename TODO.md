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

- [ ] `STAGING_SUPABASE_URL` = `https://lxmysergoeaegxlyfzwk.supabase.co`
- [ ] `STAGING_SUPABASE_PUBLISHABLE_KEY` = (from Supabase dashboard > Settings > API > Publishable key)
- [ ] `STAGING_SUPABASE_SERVICE_ROLE_KEY` = (from Supabase dashboard)
- [ ] `STAGING_TEST_USER_EMAIL` = (burner email)
- [ ] `STAGING_TEST_USER_PASSWORD` = (burner password)
- [ ] `GOOGLE_CLIENT_ID` = (from Google Cloud Console)
- [ ] `GOOGLE_CLIENT_SECRET` = (from Google Cloud Console)

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

## Fly.io Deployment Setup

### Prerequisites
- [ ] Install Fly CLI: `brew install flyctl` (macOS) or see [Fly.io docs](https://fly.io/docs/hands-on/install-flyctl/)
- [ ] Authenticate: `fly auth login`

### 1. Create Dockerfile
Create `Dockerfile` in repository root:

```dockerfile
# Multi-stage build for smaller image
FROM python:3.12-slim AS builder

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

WORKDIR /app

# Copy dependency files
COPY pyproject.toml uv.lock ./
COPY backend/pyproject.toml backend/
COPY cli/pyproject.toml cli/

# Install dependencies
RUN uv sync --frozen --no-dev

# Production image
FROM python:3.12-slim

WORKDIR /app

# Copy virtual environment from builder
COPY --from=builder /app/.venv /app/.venv

# Copy application code
COPY backend/ backend/
COPY cli/ cli/

# Set environment
ENV PATH="/app/.venv/bin:$PATH"
ENV PYTHONPATH="/app/backend"

EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"

# Run the API
CMD ["python", "-m", "uvicorn", "selko.api.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
```

- [ ] Create `Dockerfile` with above content

### 2. Create fly.toml
Create `fly.toml` in repository root:

```toml
app = 'selko-api-staging'
primary_region = 'sjc'

[build]

[http_service]
  internal_port = 8000
  force_https = true
  auto_stop_machines = 'stop'
  auto_start_machines = true
  min_machines_running = 0
  processes = ['app']

[[vm]]
  memory = '256mb'
  cpu_kind = 'shared'
  cpus = 1
```

- [ ] Create `fly.toml` with above content

### 3. Create .dockerignore
Create `.dockerignore` in repository root:

```
.git
.github
.venv
__pycache__
*.pyc
.env*
.pytest_cache
.coverage
*.egg-info
supabase
docs
*.md
!README.md
```

- [ ] Create `.dockerignore` with above content

### 4. Deploy Staging to Fly.io
- [ ] Run: `fly launch --name selko-api-staging --no-deploy`
- [ ] Set secrets:
```bash
fly secrets set ENVIRONMENT=staging
fly secrets set SUPABASE_URL=https://lxmysergoeaegxlyfzwk.supabase.co
fly secrets set SUPABASE_PUBLISHABLE_KEY=<staging-anon-key>
fly secrets set SUPABASE_SERVICE_ROLE_KEY=<staging-service-role-key>
fly secrets set SUPABASE_JWT_SECRET=<staging-jwt-secret>
```
- [ ] Deploy: `fly deploy`
- [ ] Verify: `curl https://selko-api-staging.fly.dev/health`

### 5. Deploy Production to Fly.io
- [ ] Create production app: `fly launch --name selko-api --no-deploy`
- [ ] Update `fly.toml`: change `app = 'selko-api'`
- [ ] Set secrets with production values (same pattern as staging)
- [ ] Deploy: `fly deploy`
- [ ] Verify: `curl https://selko-api.fly.dev/health`

### 6. GitHub Actions Deployment (Optional)
- [ ] Generate deploy token: `fly tokens create deploy -x 999999h`
- [ ] Add `FLY_API_TOKEN` secret to GitHub repository
- [ ] Add deploy job to `.github/workflows/test.yml`:

```yaml
  deploy-staging:
    name: Deploy to Staging
    needs: [test-staging]
    runs-on: ubuntu-latest
    if: github.ref == 'refs/heads/main'
    steps:
      - uses: actions/checkout@v4
      - uses: superfly/flyctl-actions/setup-flyctl@master
      - run: flyctl deploy --remote-only
        env:
          FLY_API_TOKEN: ${{ secrets.FLY_API_TOKEN }}
```

### 7. Update CORS Origins (When Adding Frontend)
When you have a frontend, add CORS configuration:
- [ ] Add `ALLOWED_ORIGINS` environment variable support in `app.py`
- [ ] Set `ALLOWED_ORIGINS` in Fly.io: `fly secrets set ALLOWED_ORIGINS=https://your-frontend.com`

---

## CI/CD Pipeline Status

| Job | Trigger | Status |
|-----|---------|--------|
| Unit Tests | Every push | ✅ Configured |
| Integration (Dev) | Every push | ✅ Configured |
| Integration (Staging) | Main only | ⬜ Needs GitHub secrets (step 8 above) |
| Deploy (Staging) | Main only | ⬜ Needs Fly.io setup |
| Deploy (Production) | Manual/tag | ⬜ Needs Fly.io setup |

### How CI/CD Works

| Job | Trigger | What it does |
|-----|---------|--------------|
| **Unit Tests** | Every push/PR | Fast tests, no external deps |
| **Integration (Dev)** | Every push/PR | Spins up local Supabase in Docker |
| **Integration (Staging)** | Main branch only | Uses cloud Supabase + real Gmail |

### Important Notes

1. **OAuth tokens are in the database** - GitHub Actions doesn't need token files, just Supabase access
2. **Staging tests only on main** - Prevents burning through Gmail API quota on every PR
3. **Development tests spin up Supabase** - Uses `supabase start` in the workflow
4. **OAuth tokens auto-refresh** - After initial setup and OAuth app publication, no manual intervention needed

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
