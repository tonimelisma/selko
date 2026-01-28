# Testing Guide

Comprehensive testing documentation for Selko.

## Test Commands

### Backend (Python/pytest)

```bash
# All backend tests
uv run pytest backend/tests/ -v

# Unit tests only (no external dependencies)
uv run pytest backend/tests/ -m "not integration" -v

# Integration tests with mocked LLM
uv run pytest backend/tests/integration/ -m "development" -v

# Integration tests with real LLM (costs $$$)
uv run pytest backend/tests/integration/ -m "development" --run-llm -v
```

### Frontend (Vitest)

```bash
# Run tests with JSON output (required for pre-commit hook)
cd frontend && npm run test:unit -- --reporter=json --outputFile=test-results.json
```

### iOS (XCTest)

```bash
# Run tests with result bundle (required for pre-commit hook)
xcodebuild test -project ios/iOS.xcodeproj -scheme iOS \
  -destination 'platform=iOS Simulator,name=iPhone 16' \
  -resultBundlePath ios/TestResults.xcresult
```

### Android (Gradle)

```bash
cd android && ./gradlew test
```

## Test Markers

| Marker | Description | Requirements |
|--------|-------------|--------------|
| `integration` | All integration tests | Local Supabase running |
| `development` | Tests against local Supabase + real Gmail | Seeded tokens |
| `staging` | Tests against cloud Supabase + real services | CI only |
| `llm` | Tests requiring real LLM API calls | `--run-llm` flag |

## Test Architecture

| Test Type | Database | LLM | Gmail | Cost |
|-----------|----------|-----|-------|------|
| Unit | None | Mocked | Mocked | $0 |
| Integration (default) | Local | **Mocked** | Real | $0 |
| Integration (real LLM) | Local | **Real** | Real | $$$ |
| Staging (CI only) | Cloud | Real | Real | $$$ |

## When to Use `--run-llm`

Use `--run-llm` when:
- Changing LLM prompts or response schemas
- Debugging LLM-specific behavior

Don't use `--run-llm` for:
- Database changes
- API changes
- Business logic changes

## Development Test Setup

### Initial Setup

```bash
# Start local Supabase
supabase start

# Create test user
uv run python -m cli.cli_user create \
  --email test@selko.local \
  --password testpass123 \
  --auto-confirm

# Seed Gmail tokens from staging
uv run python -m cli.cli_seed_tokens \
  --from staging \
  --to development \
  --provider gmail
```

### After Database Reset

After running `supabase db reset`, you must re-run the setup:

```bash
uv run python -m cli.cli_user create --email test@selko.local --password testpass123 --auto-confirm
uv run python -m cli.cli_seed_tokens --from staging --to development --provider gmail
```

### Refreshing Expired OAuth Tokens

If Gmail tests fail with `unauthorized_client` or `credentials expired or revoked`:

```bash
# Step 1: Run OAuth flow to get fresh tokens (stores in staging)
ENVIRONMENT=staging uv run python -m cli.cli_auth_gmail

# Step 2: Seed fresh tokens to development
uv run python -m cli.cli_seed_tokens --from staging --to development --provider gmail
```

This stores tokens in staging (persistent) so they can be seeded to development later.

## Token Persistence Rules

### Development (Local Supabase)

- Database is **ephemeral** (reset on `supabase start`)
- Tokens must be re-seeded after `supabase db reset`
- Tests are **READ-ONLY** for integrations (preserve seeded tokens)
- Use `pytest.fail()` not `pytest.skip()` when credentials missing

### Staging (Cloud Supabase)

- Database is **persistent** across runs
- Real OAuth tokens from `cli_auth_gmail` must be preserved
- **Never** use `cleanup_integrations` with real providers in staging

## Pre-Commit Hook

A git pre-commit hook blocks commits unless tests have been run for changed modules.

### Setup

```bash
cp scripts/pre-commit.hook .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

### How It Works

The hook checks per-module using native test caches:

| Module | Cache Location |
|--------|----------------|
| backend | `backend/.pytest_cache/v/cache/lastfailed` |
| frontend | `frontend/test-results.json` |
| ios | `ios/TestResults.xcresult` |
| android | `android/app/build/test-results/` |

For each module with staged changes, the hook verifies:
1. Test results exist and show all tests passed
2. No source files are newer than the test results

### If Hook Blocks Your Commit

1. Read the error message to see which modules need tests
2. Run the native test command for that module
3. Fix any failing tests
4. Commit again

**Never bypass the hook with `--no-verify`.**

## Continuous Integration

Tests run automatically on pull requests. See `docs/ci-cd.md` for CI pipeline details.
