# Manual Setup Tasks

This file contains remaining setup tasks. Development, staging, and Render services are deployed.

---

## Render Services (Deployed)

| Service | Type | URL |
|---------|------|-----|
| `selko-app-staging` | Python API | https://selko.onrender.com |
| `selko-app-production` | Python API | https://selko-production.onrender.com |
| `selko-web-staging` | Frontend | https://selko-web-staging.onrender.com |
| `selko-web-production` | Frontend | https://selko-web.onrender.com |

---

## CI/CD Deploy Hooks Setup

- [x] All 4 Render services have auto-deploy OFF
- [x] `RENDER_DEPLOY_HOOK_APP_STAGING` added to GitHub secrets
- [x] `RENDER_DEPLOY_HOOK_WEB_STAGING` added to GitHub secrets
- [x] `RENDER_DEPLOY_HOOK_APP_PRODUCTION` added to GitHub secrets
- [x] `RENDER_DEPLOY_HOOK_WEB_PRODUCTION` added to GitHub secrets

---

## Google OAuth Web Application Client

For web-based Gmail OAuth flow (users connecting Gmail through the UI):
- [ ] Create "Web application" OAuth client in Google Cloud Console
- [ ] Add authorized redirect URIs:
  - `http://localhost:8000/oauth/callback` (local dev)
  - `https://selko.onrender.com/oauth/callback` (staging)
  - `https://selko-production.onrender.com/oauth/callback` (production)
- [ ] Update `GOOGLE_CLIENT_ID` and `GOOGLE_CLIENT_SECRET` in Render env vars

---

## Production Environment Setup

### 1. Database Migrations
- [x] All 24 migrations applied to production

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

## CORS Configuration

- [x] `ALLOWED_ORIGINS` already implemented in `app.py` and `config.py`
- [x] Set on `selko-app-staging`: `https://selko-web-staging.onrender.com`
- [x] Set on `selko-app-production`: `https://selko-web.onrender.com`

---

## CI/CD Pipeline Status

| Job | Trigger | Status |
|-----|---------|--------|
| Unit Tests | Every push/PR | ✅ Configured |
| Integration (Dev) | Every push/PR | ✅ Configured |
| Deploy Staging (DB + Render) | Main only | ✅ Configured |
| Integration (Staging) | Main only (after deploy) | ✅ Configured |
| Deploy Production (DB + Render) | Manual/tag | ✅ Configured |

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
