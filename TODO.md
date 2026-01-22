# Manual Setup Tasks

Tasks that require human action to complete the integration test setup.

## Staging Environment Setup

### 1. Create Burner Gmail Account
- [ ] Create a new Gmail account for staging tests (e.g., `selko-staging-test@gmail.com`)
- [ ] Use a strong password and store it securely
- [ ] Enable 2FA for security (optional but recommended)

### 2. Google Cloud Console Configuration
- [ ] Go to [Google Cloud Console](https://console.cloud.google.com/)
- [ ] Select or create the Selko project
- [ ] Enable the Gmail API (APIs & Services → Enable APIs → Gmail API)
- [ ] Go to OAuth consent screen
- [ ] Add the burner Gmail account email to "Test users"

### 3. Publish OAuth App (Required for Automation)
This step prevents refresh tokens from expiring after 7 days.

- [ ] Go to Google Cloud Console → OAuth consent screen
- [ ] Click "Publish App" to change from "Testing" to "In Production"
- [ ] Choose "Internal" (if using Google Workspace) or "External" with limited scopes
- [ ] Complete any required verification steps

### 4. Initial OAuth Authorization (One-Time)
Run this once to store OAuth tokens in the staging database:

```bash
ENVIRONMENT=staging uv run python -m cli.cli_auth_gmail
```

- [ ] Complete the OAuth flow in browser when prompted
- [ ] Verify tokens are stored: check `integrations` table in staging Supabase

### 5. Configure Staging Environment Variables
Ensure `.env.test` has these values set:

- [ ] `SUPABASE_URL` - Staging Supabase URL
- [ ] `SUPABASE_ANON_KEY` - Staging anon/publishable key
- [ ] `SUPABASE_SERVICE_ROLE_KEY` - Staging service role key
- [ ] `TEST_USER_EMAIL` - Email of test user in staging
- [ ] `TEST_USER_PASSWORD` - Password of test user in staging
- [ ] `GOOGLE_CLIENT_ID` - From Google Cloud Console
- [ ] `GOOGLE_CLIENT_SECRET` - From Google Cloud Console

### 6. Prepare Test Emails (Optional)
For more comprehensive tests, send a few emails to the burner account:

- [ ] Send a plain text email
- [ ] Send an email with attachments
- [ ] Star an email (to test `is_starred` flag)
- [ ] Mark an email as important (to test `is_important` flag)

---

## Verification

After completing the above, verify the setup works:

```bash
# Run staging integration tests
uv run pytest backend/tests/integration/ -m "staging" -v
```

Expected: All staging tests should pass.

---

## CI/CD Setup (Future)

If setting up GitHub Actions:

- [ ] Add repository secrets:
  - `STAGING_SUPABASE_URL`
  - `STAGING_SUPABASE_ANON_KEY`
  - `STAGING_SUPABASE_SERVICE_ROLE_KEY`
  - `STAGING_TEST_USER_EMAIL`
  - `STAGING_TEST_USER_PASSWORD`

---

## Notes

- **OAuth tokens auto-refresh**: After initial setup and OAuth app publication, no manual intervention is needed
- **Local development**: No manual setup required - uses local Supabase + mocked Gmail
- **Production tests**: Read-only smoke tests, no special setup needed
