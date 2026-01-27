# Manual Setup Tasks

This file contains remaining setup tasks. Development, staging, and frontend deployments are complete.

---

## Production Environment Setup

### 1. Apply Database Migrations
Production is 13 migrations behind staging. Run:
- [ ] `supabase link --project-ref khahcozfbnpykspvatrg`
- [ ] `supabase db push`
- [ ] Verify: `supabase migration list`

### 2. Create Production User
- [ ] Run: `ENVIRONMENT=production uv run python -m cli.cli_user create --email <your-email> --password <password>`
- [ ] Update `.env.production` with real credentials (currently has placeholders)

### 3. OAuth Authorization (Production)
- [ ] Run: `ENVIRONMENT=production uv run python -m cli.cli_auth_gmail`
- [ ] Complete OAuth flow with your **real Gmail account**
- [ ] Verify tokens stored in production Supabase

### 4. Verification
- [ ] Test email fetch: `ENVIRONMENT=production uv run python -m cli.cli_fetch_emails --max 5`
- [ ] Check emails in Supabase dashboard

---

## Render Backend API Deployment

Frontend is deployed (`selko-web-staging`, `selko-web`), but backend API services are missing.

### 1. Create Staging API Service
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

### 2. Create Production API Service
- [ ] Create another Web Service with same settings but:
  - **Name:** `selko-api`
  - **Auto-Deploy:** Off (manual deploys only for production safety)
- [ ] Set environment variables with production values
- [ ] Deploy and verify: `curl https://selko-api.onrender.com/health`

### 3. Update CORS Origins
Once backend is deployed:
- [ ] Add `ALLOWED_ORIGINS` environment variable support in `app.py`
- [ ] Set `ALLOWED_ORIGINS` in Render backend environment:
  - Staging: `https://selko-web-staging.onrender.com`
  - Production: `https://selko-web.onrender.com`

---

## CI/CD Pipeline Status

| Job | Trigger | Status |
|-----|---------|--------|
| Unit Tests | Every push/PR | ✅ Configured |
| Integration (Dev) | Every push/PR | ✅ Configured |
| Deploy Staging (DB) | Main only | ✅ Configured |
| Deploy Staging (API) | Main only | ⬜ Needs Render service created |
| Integration (Staging) | Main only (after deploy) | ✅ Configured |
| Deploy Production (DB) | Manual/tag | ✅ Configured |
| Deploy Production (API) | Manual/tag | ⬜ Needs Render service created |

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
