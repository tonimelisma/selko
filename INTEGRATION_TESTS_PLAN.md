# Integration Tests Plan

This document outlines the strategy for implementing integration tests across all environments.

## Overview

Integration tests will validate end-to-end functionality with real services (Supabase, Gmail API) rather than mocked dependencies. The tests are organized by environment to ensure proper isolation and safety.

## Environment Strategy

| Environment | Database | Gmail API | Purpose | Safety Level |
|-------------|----------|-----------|---------|--------------|
| **Development** | Local Supabase (Docker) | Mocked | Fast iteration, CI/CD | Safe (isolated) |
| **Staging** | Cloud Supabase (staging) | Real (burner account) | Pre-production validation | Safe (test data only) |
| **Production** | Cloud Supabase (prod) | Real (read-only) | Smoke tests only | Restricted (read-only) |

### Development Environment Tests
- **Database**: Local Supabase via Docker (`supabase start`)
- **Gmail**: Mocked responses using `responses` library or `unittest.mock`
- **Credentials**: Test fixtures with fake tokens
- **Purpose**: Fast, repeatable tests for CI/CD pipeline
- **Cleanup**: `supabase db reset` between test runs

### Staging Environment Tests
- **Database**: Cloud Supabase staging instance (`lxmysergoeaegxlyfzwk`)
- **Gmail**: Real Gmail API with dedicated burner account
- **Credentials**: Real OAuth tokens stored in staging DB
- **Purpose**: Validate real-world integrations before production
- **Cleanup**: Delete test data after each test run

### Production Environment Tests
- **Database**: Cloud Supabase production instance (`khahcozfbnpykspvatrg`)
- **Gmail**: Read-only operations only (no sending, no modifications)
- **Purpose**: Smoke tests to verify production health
- **Restrictions**: No data creation, no destructive operations

---

## Test Categories

### 1. Authentication Tests (`test_integration_auth.py`)

Tests the user authentication flow with real Supabase Auth.

| Test | Development | Staging | Production |
|------|-------------|---------|------------|
| Sign in with valid credentials | ✓ | ✓ | ✓ (read-only) |
| Sign in with invalid credentials (error handling) | ✓ | ✓ | ✗ |
| Get current user ID from session | ✓ | ✓ | ✓ |
| Session token refresh | ✓ | ✓ | ✗ |
| Sign out and invalidate session | ✓ | ✓ | ✗ |

**Test Data Requirements:**
- Test user with known email/password per environment
- Use `TEST_USER_EMAIL` and `TEST_USER_PASSWORD` from env config

**Example Test:**
```python
@pytest.mark.integration
@pytest.mark.parametrize("env", ["development", "staging"])
def test_sign_in_valid_credentials(env):
    """User can sign in and obtain session token."""
    config = load_config(env_override=env)
    client = create_supabase_client(config.supabase_url, config.supabase_key)

    result = sign_in(client, config.test_user_email, config.test_user_password)

    assert result.user is not None
    assert result.user.email == config.test_user_email
    assert result.session is not None
    assert result.session.access_token is not None
```

---

### 2. User Management Tests (`test_integration_users.py`)

Tests admin operations using service role key.

| Test | Development | Staging | Production |
|------|-------------|---------|------------|
| Create user with auto-confirm | ✓ | ✗ | ✗ |
| Create user with email verification | ✗ | ✓ | ✗ |
| List all users | ✓ | ✓ | ✗ |
| Delete user (cascades integrations/emails) | ✓ | ✓ | ✗ |
| User profile auto-created on auth signup | ✓ | ✓ | ✗ |

**Test Data Requirements:**
- Service role key for admin operations
- Unique test email per test run (e.g., `test-{uuid}@selko.local`)

**Cleanup Strategy:**
```python
@pytest.fixture
def temp_user(admin_client):
    """Create a temporary user for testing, delete after test."""
    user_id = create_user(admin_client, f"test-{uuid4()}@selko.local", "testpass123")
    yield user_id
    delete_user(admin_client, user_id)  # Cleanup
```

---

### 3. OAuth Integration Tests (`test_integration_oauth.py`)

Tests storing and retrieving OAuth credentials from the database.

| Test | Development | Staging | Production |
|------|-------------|---------|------------|
| Save Gmail OAuth credentials | ✓ | ✓ | ✗ |
| Retrieve and reconstruct Credentials object | ✓ | ✓ | ✓ |
| Update existing credentials (upsert) | ✓ | ✓ | ✗ |
| Handle expired token status | ✓ | ✓ | ✗ |
| Unique constraint (user_id, provider) | ✓ | ✓ | ✗ |
| Scopes array storage | ✓ | ✓ | ✓ |

**Test Data Requirements:**
- Authenticated test user
- Mock or real OAuth tokens (depending on environment)

**Example Test:**
```python
@pytest.mark.integration
def test_save_and_retrieve_oauth_credentials(authenticated_client, test_user_id):
    """OAuth credentials can be saved and retrieved correctly."""
    creds = Credentials(
        token="test_access_token",
        refresh_token="test_refresh_token",
        token_uri="https://oauth2.googleapis.com/token",
        client_id="test_client_id",
        client_secret="test_client_secret",
        scopes=["https://www.googleapis.com/auth/gmail.readonly"]
    )

    save_oauth_credentials(authenticated_client, test_user_id, "gmail", creds)

    retrieved = get_oauth_credentials(authenticated_client, test_user_id, "gmail", config)

    assert retrieved.token == creds.token
    assert retrieved.refresh_token == creds.refresh_token
    assert retrieved.scopes == creds.scopes
```

---

### 4. Gmail API Tests (`test_integration_gmail.py`)

Tests Gmail API interactions. **Requires burner Gmail account for staging.**

| Test | Development | Staging | Production |
|------|-------------|---------|------------|
| OAuth flow (interactive) | Manual | Manual | ✗ |
| Build Gmail service from credentials | ✓ (mocked) | ✓ (real) | ✗ |
| Get user profile (email address) | ✓ (mocked) | ✓ (real) | ✗ |
| Fetch messages (list) | ✓ (mocked) | ✓ (real) | ✗ |
| Fetch message details | ✓ (mocked) | ✓ (real) | ✗ |
| Handle 429 rate limiting | ✓ (mocked) | ✗ | ✗ |
| Token refresh on expiry | ✓ (mocked) | ✓ (real) | ✗ |

**Burner Gmail Account Setup:**
1. Create dedicated Gmail account for staging tests (e.g., `selko-staging-test@gmail.com`)
2. Enable Gmail API in Google Cloud Console
3. Add burner account as test user in OAuth consent screen
4. Run `cli_auth_gmail --env staging` once to store OAuth tokens
5. Tokens persist in staging DB for automated tests

**Rate Limiting Tests (Development Only):**
```python
@pytest.mark.integration
@responses.activate
def test_rate_limiting_retry():
    """Gmail API 429 errors trigger exponential backoff."""
    responses.add(
        responses.GET,
        "https://gmail.googleapis.com/gmail/v1/users/me/messages",
        json={"error": {"code": 429, "message": "Rate limit exceeded"}},
        status=429
    )
    responses.add(
        responses.GET,
        "https://gmail.googleapis.com/gmail/v1/users/me/messages",
        json={"messages": []},
        status=200
    )

    # Should retry and succeed
    messages = fetch_messages(service, max_results=10)
    assert len(responses.calls) == 2  # One failure, one success
```

---

### 5. Email Pipeline Tests (`test_integration_emails.py`)

Tests the complete email fetch → parse → store pipeline.

| Test | Development | Staging | Production |
|------|-------------|---------|------------|
| Parse Gmail message structure | ✓ | ✓ | ✗ |
| Store email in database | ✓ | ✓ | ✗ |
| Upsert on duplicate gmail_id | ✓ | ✓ | ✗ |
| Trigger parses labels into flags | ✓ | ✓ | ✗ |
| Content hash deduplication | ✓ | ✓ | ✗ |
| RLS: user sees only own emails | ✓ | ✓ | ✗ |

**Database Trigger Validation:**
```python
@pytest.mark.integration
def test_gmail_labels_trigger_sets_flags(authenticated_client, test_user_id):
    """Database trigger parses gmail_label_ids into boolean flags."""
    email_data = {
        "user_id": test_user_id,
        "gmail_id": "test_msg_123",
        "thread_id": "test_thread_123",
        "gmail_label_ids": ["SPAM", "UNREAD"],
        "subject": "Test spam email",
        "from_email": "spammer@example.com",
        "date_sent": "2024-01-15T10:00:00Z"
    }

    result = authenticated_client.table("emails").insert(email_data).execute()

    saved_email = result.data[0]
    assert saved_email["is_spam"] is True
    assert saved_email["is_unread"] is True
    assert saved_email["is_primary"] is False
```

---

### 6. End-to-End Pipeline Tests (`test_integration_e2e.py`)

Tests complete user journeys across multiple services.

| Test | Development | Staging | Production |
|------|-------------|---------|------------|
| New user: create → auth → gmail → fetch | ✓ | ✓ | ✗ |
| Existing user: sign in → fetch new emails | ✓ | ✓ | ✗ |
| Delete user cascades all data | ✓ | ✓ | ✗ |

**Staging E2E Test (Real Gmail):**
```python
@pytest.mark.integration
@pytest.mark.staging
def test_full_email_sync_pipeline():
    """
    Complete pipeline: authenticate → fetch Gmail → store in DB.
    Requires burner Gmail account with pre-authorized OAuth.
    """
    config = load_config(env_override="staging")

    # 1. Authenticate user
    client = get_authenticated_client(config)
    user_id = get_current_user_id(client)

    # 2. Get Gmail credentials from DB
    creds = get_credentials(client, user_id, config)
    assert creds is not None

    # 3. Build Gmail service
    service = build_service(creds)
    profile = get_user_profile(service)
    assert "@gmail.com" in profile["emailAddress"]

    # 4. Fetch messages
    messages = fetch_messages(service, max_results=5)
    assert len(messages) <= 5

    # 5. Parse and store
    if messages:
        for msg_id in [m["id"] for m in messages]:
            msg_detail = get_message_detail(service, msg_id)
            parsed = parse_gmail_message(msg_detail)
            save_emails(client, user_id, [parsed])

        # 6. Verify stored in DB
        result = client.table("emails").select("*").eq("user_id", user_id).execute()
        assert len(result.data) > 0
```

---

### 7. CLI Integration Tests (`test_integration_cli.py`)

Tests CLI tools as subprocess to validate argument parsing and output.

| Test | Development | Staging | Production |
|------|-------------|---------|------------|
| cli_user create/list/delete | ✓ | ✓ | ✗ |
| cli_fetch_emails --max N | ✓ | ✓ | ✗ |
| --env flag overrides environment | ✓ | ✓ | ✗ |
| -v verbose logging | ✓ | ✓ | ✗ |
| -q quiet mode | ✓ | ✓ | ✗ |

**Example CLI Test:**
```python
@pytest.mark.integration
def test_cli_user_list():
    """CLI user list command returns users."""
    result = subprocess.run(
        ["uv", "run", "python", "-m", "cli.cli_user", "list", "--env", "development"],
        capture_output=True,
        text=True
    )

    assert result.returncode == 0
    assert "email" in result.stdout.lower()
```

---

## Test Infrastructure

### Directory Structure

```
backend/
└── tests/
    ├── conftest.py              # Shared fixtures
    ├── test_config.py           # Unit tests (existing)
    ├── test_emails.py           # Unit tests (existing)
    ├── test_integrations.py     # Unit tests (existing)
    └── integration/             # NEW: Integration tests
        ├── __init__.py
        ├── conftest.py          # Integration-specific fixtures
        ├── test_integration_auth.py
        ├── test_integration_users.py
        ├── test_integration_oauth.py
        ├── test_integration_gmail.py
        ├── test_integration_emails.py
        ├── test_integration_e2e.py
        └── test_integration_cli.py
```

### Pytest Markers

```python
# backend/pyproject.toml
[tool.pytest.ini_options]
markers = [
    "integration: marks tests as integration tests (deselect with '-m \"not integration\"')",
    "development: tests that run against local Supabase",
    "staging: tests that run against staging Supabase + real Gmail",
    "production: read-only smoke tests for production",
    "slow: tests that take >10 seconds",
]
```

### Running Tests

```bash
# Unit tests only (fast, no external dependencies)
uv run pytest backend/tests/ -m "not integration"

# Integration tests - development (requires local Supabase)
supabase start
uv run pytest backend/tests/integration/ -m "development" -v

# Integration tests - staging (requires network + burner Gmail)
uv run pytest backend/tests/integration/ -m "staging" -v

# All integration tests
uv run pytest backend/tests/integration/ -m "integration" -v

# Smoke tests for production (read-only)
uv run pytest backend/tests/integration/ -m "production" -v
```

### Integration Test Fixtures (`tests/integration/conftest.py`)

```python
import pytest
from selko.config import load_config
from selko.services.auth import get_authenticated_client, get_current_user_id

@pytest.fixture(scope="session")
def development_config():
    """Load development configuration."""
    return load_config(env_override="development")

@pytest.fixture(scope="session")
def staging_config():
    """Load staging configuration."""
    return load_config(env_override="staging")

@pytest.fixture(scope="function")
def authenticated_client(request, development_config):
    """
    Authenticated Supabase client for integration tests.
    Uses test user credentials from config.
    """
    config = development_config
    if hasattr(request, "param") and request.param == "staging":
        config = staging_config

    client = get_authenticated_client(config)
    yield client
    # Cleanup: sign out
    client.auth.sign_out()

@pytest.fixture(scope="function")
def test_user_id(authenticated_client):
    """Get current user ID from authenticated session."""
    return get_current_user_id(authenticated_client)

@pytest.fixture(scope="function")
def admin_client(development_config):
    """
    Admin client using service role key (bypasses RLS).
    Use for setup/teardown of test data.
    """
    from supabase import create_client
    return create_client(
        development_config.supabase_url,
        development_config.supabase_service_role_key
    )

@pytest.fixture(scope="function")
def cleanup_emails(authenticated_client, test_user_id):
    """Delete test emails after test completes."""
    yield
    authenticated_client.table("emails").delete().eq("user_id", test_user_id).execute()
```

---

## Burner Gmail Account Setup

### One-Time Setup (Manual)

1. **Create burner Gmail account:**
   - Account: `selko-staging-test@gmail.com` (example)
   - Use a strong password, store securely
   - Enable 2FA for security

2. **Google Cloud Console setup:**
   - Create project or use existing Selko project
   - Enable Gmail API
   - Add burner account email to OAuth consent screen test users

3. **Authorize OAuth for staging:**
   ```bash
   # Run once to authorize and store tokens
   ENVIRONMENT=staging uv run python -m cli.cli_auth_gmail
   ```
   - Complete OAuth flow in browser
   - Tokens stored in staging database `integrations` table

4. **Prepare test data in Gmail:**
   - Send a few test emails to the burner account
   - Include various label types (starred, important, promotions)
   - Keep inbox small (<100 emails) for fast tests

### Token Refresh Handling

OAuth tokens expire after 1 hour. The staging tests should:
1. Check if token is expired before running
2. Use refresh token to get new access token
3. Update stored credentials in database

This is already implemented in `gmail.get_credentials()` with `creds.refresh()`.

### Making Tests Fully Automatic (No Manual Re-auth)

**The Problem**: Google OAuth refresh tokens have different lifetimes depending on app status:

| App Status | Refresh Token Lifetime | Manual Re-auth Needed? |
|------------|------------------------|------------------------|
| **Testing** (unpublished) | **7 days** | Yes, weekly |
| **Published** (internal or external) | Indefinite* | No |

*Unless user revokes access or you request new scopes

**The Solution**: Publish the OAuth app to get indefinite refresh tokens.

**Steps to enable fully automatic tests:**

1. **Google Cloud Console → OAuth consent screen**
2. **Change status from "Testing" to "In Production"**
3. **Select "Internal"** (if using Google Workspace) or publish externally with limited scopes
4. Once published, refresh tokens won't expire

**After publishing:**
- Staging tests run indefinitely without manual intervention
- CI/CD only needs environment variables (Supabase URL/keys, test user credentials)
- OAuth tokens live in database and auto-refresh via `gmail.get_credentials()`

### Automation Summary by Environment

| Environment | Database | Gmail API | Fully Automatic? |
|-------------|----------|-----------|------------------|
| **Development** | Local Supabase | Mocked (no real API) | ✓ Yes |
| **Staging** | Cloud Supabase | Real (burner account) | ✓ Yes (after OAuth app published) |
| **Production** | Cloud Supabase | Read-only or skipped | ✓ Yes |

---

## CI/CD Integration

### GitHub Actions Workflow

```yaml
# .github/workflows/test.yml
name: Tests

on: [push, pull_request]

jobs:
  unit-tests:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync --extra test
      - run: uv run pytest backend/tests/ -m "not integration" -v

  integration-tests-development:
    runs-on: ubuntu-latest
    services:
      supabase:
        # Use Supabase CLI in Docker or local setup
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - uses: supabase/setup-cli@v1
      - run: supabase start
      - run: uv sync --extra test
      - run: uv run pytest backend/tests/integration/ -m "development" -v
    env:
      ENVIRONMENT: development

  integration-tests-staging:
    runs-on: ubuntu-latest
    # Only run on main branch or manual trigger
    if: github.ref == 'refs/heads/main' || github.event_name == 'workflow_dispatch'
    steps:
      - uses: actions/checkout@v4
      - uses: astral-sh/setup-uv@v4
      - run: uv sync --extra test
      - run: uv run pytest backend/tests/integration/ -m "staging" -v
    env:
      ENVIRONMENT: staging
      SUPABASE_URL: ${{ secrets.STAGING_SUPABASE_URL }}
      SUPABASE_PUBLISHABLE_KEY: ${{ secrets.STAGING_SUPABASE_PUBLISHABLE_KEY }}
      SUPABASE_SERVICE_ROLE_KEY: ${{ secrets.STAGING_SUPABASE_SERVICE_ROLE_KEY }}
      TEST_USER_EMAIL: ${{ secrets.STAGING_TEST_USER_EMAIL }}
      TEST_USER_PASSWORD: ${{ secrets.STAGING_TEST_USER_PASSWORD }}
```

---

## Implementation Order

### Phase 1: Test Infrastructure (Foundation)
1. Create `backend/tests/integration/` directory structure
2. Add pytest markers to `pyproject.toml`
3. Create `integration/conftest.py` with core fixtures
4. Verify local Supabase can be started/reset in tests

### Phase 2: Authentication & User Tests
5. Implement `test_integration_auth.py`
6. Implement `test_integration_users.py`
7. Test RLS enforcement

### Phase 3: OAuth & Integration Tests
8. Implement `test_integration_oauth.py`
9. Test credential storage/retrieval with real DB

### Phase 4: Gmail Tests (Mocked for Development)
10. Add `responses` library for HTTP mocking
11. Implement `test_integration_gmail.py` with mocked API
12. Test rate limiting and retry logic

### Phase 5: Email Pipeline Tests
13. Implement `test_integration_emails.py`
14. Test database triggers
15. Test deduplication

### Phase 6: Staging Tests (Real Gmail)
16. Set up burner Gmail account
17. Run `cli_auth_gmail` to store OAuth tokens
18. Implement staging-specific tests
19. Add staging marker to appropriate tests

### Phase 7: E2E & CLI Tests
20. Implement `test_integration_e2e.py`
21. Implement `test_integration_cli.py`

### Phase 8: CI/CD Integration
22. Create GitHub Actions workflow
23. Configure secrets for staging environment
24. Set up test data cleanup automation

---

## Test Data Management

### Development (Local Supabase)
- Run `supabase db reset` before test suite
- Each test creates its own data with unique IDs
- Fixtures handle cleanup with `yield` pattern

### Staging (Cloud Supabase)
- Use dedicated test user (not shared with manual testing)
- Tests should clean up after themselves
- Consider timestamp-based cleanup for orphaned data

### Production (Read-Only)
- Never create or modify data
- Only read operations allowed
- Use existing data for smoke tests

---

## Success Criteria

Integration tests are complete when:

1. **Coverage**: All services have integration tests
2. **Environments**: Tests run in development and staging
3. **Reliability**: Tests pass consistently (no flaky tests)
4. **Speed**: Development tests complete in <2 minutes
5. **CI/CD**: Automated testing in GitHub Actions
6. **Documentation**: Clear setup instructions for new developers

---

## Dependencies to Add

```toml
# backend/pyproject.toml
[project.optional-dependencies]
test = [
    "pytest>=8.0",
    "pytest-cov>=4.0",
    "responses>=0.25.0",      # HTTP mocking for Gmail API
    "pytest-timeout>=2.0",    # Timeout for slow tests
]
```
