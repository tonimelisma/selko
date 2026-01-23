# Changelog

All notable changes to this project are documented in this file.

## 2026-01-23

### Documentation Alignment & Restructuring

**Files created:**
- `docs/architecture/ARCHITECTURE.md` - High-level system overview with ASCII diagrams
- `docs/guides/gmail-integration.md` - Gmail API technical guide (moved from root)
- `docs/guides/gemini-integration.md` - LLM integration patterns (moved from root)
- `docs/plans/attachment-storage.md` - Implementation plan (moved, marked COMPLETED)

**Files modified:**
- `CLAUDE.md` - Added critical sections:
  - "Development Philosophy" (end-to-end journeys first)
  - "AI Architecture" (all intelligence via LLM, no separate OCR)
  - "Next Steps" (MVP roadmap with correct order)
  - "Reference Documentation" (links to guides)
- `README.md` - Updated:
  - "Features" section: split into Implemented/Planned/Future
  - Added `attachments.py` to project structure
  - Documented `--fetch-attachments` flag
  - Expanded testing section (71+ tests, markers explained)
  - Added `docs/` folder to project structure
  - Updated Documentation section with all new docs
- `PRD_ARCH.md` - Added "Phase 0: POC" section with implementation status

**Files deleted:**
- `Accessing Gmail Data with Python.md` - Moved to `docs/guides/gmail-integration.md`
- `gemini_apis.md` - Moved to `docs/guides/gemini-integration.md`
- `PLAN_ATTACHMENT_STORAGE.md` - Moved to `docs/plans/attachment-storage.md`

**Documentation Structure:**
```
docs/
├── architecture/
│   └── ARCHITECTURE.md      # System overview + diagrams
├── guides/
│   ├── gmail-integration.md # Gmail API technical details
│   └── gemini-integration.md # LLM integration patterns
└── plans/
    └── attachment-storage.md # Completed implementation plan
```

**Key Alignment Fixes:**
1. Clarified phase terminology: POC (Phase 0) vs MVP (Phase 1)
2. Documented that all AI/intelligence features use multimodal LLM (no separate OCR)
3. Established end-to-end first principle (Email→Calendar before Photos)
4. Committed previously untracked reference docs
5. Marked attachment storage plan as COMPLETED

**Reason:** Documentation alignment as identified in analysis. Consolidate overlapping content, commit valuable reference docs, clarify development philosophy and next steps.

---

### Attachment Storage Implementation & CI/CD Improvements

**Files created:**
- `backend/selko/services/attachments.py` - Attachment service module (download, upload, deduplication, metadata)
- `backend/tests/test_attachments.py` - Unit tests for attachment functions (17 tests)
- `backend/tests/integration/test_integration_attachments.py` - Integration tests for attachment storage
- `backend/tests/integration/test_integration_rls_security.py` - Cross-user RLS denial tests (critical security)
- `supabase/migrations/20260122000004_create_storage_buckets.sql` - Storage bucket creation with RLS policies

**Files modified:**
- `.github/workflows/test.yml` - CI/CD reliability improvements:
  - Replaced `sleep 10` with health check for Supabase readiness
  - Added uv dependency caching for faster CI
  - Fixed .env creation with proper quoting
  - Improved test user creation error handling
- `backend/selko/services/__init__.py` - Added attachment service exports
- `backend/selko/services/gmail.py` - Added `extract_attachments()` function for parsing MIME multipart
- `backend/selko/services/emails.py` - `save_emails()` now returns records (not just count) for attachment linking
- `backend/selko/config.py` - Added storage configuration (bucket name, max file size)
- `cli/cli_fetch_emails.py` - Added `--fetch-attachments` flag for downloading attachments
- `backend/tests/integration/conftest.py` - Added attachment-related fixtures

**Attachment Storage Features:**
- Download attachments from Gmail API with rate limiting and retry
- Upload to Supabase Storage with user-scoped paths (`{user_id}/{unique_id}_{filename}`)
- Content deduplication using SHA-256 hash (skip duplicates across emails)
- Metadata storage in `attachments` table linked to email records
- 50 MB file size limit with configurable MIME type allowlist
- RLS policies: users can only access their own folder in storage

**CI/CD Improvements:**
- Health check loop replaces fragile `sleep 10` for Supabase readiness
- uv dependency caching reduces CI build time
- Proper quoting prevents issues with special characters in .env
- Better error messaging for test user creation

**Security Tests Added:**
- Cross-user email read denial
- Cross-user email update denial
- Cross-user email delete denial
- Cross-user attachment access denial
- Cross-user integration access denial
- Injection attempt (inserting data with wrong user_id)

**CLI Usage:**
```bash
# Fetch emails AND download attachments
uv run python -m cli.cli_fetch_emails --max 10 --fetch-attachments
```

**Reason:** Implement email attachment storage as planned in `PLAN_ATTACHMENT_STORAGE.md`. Improve CI/CD reliability based on code review findings. Add critical security tests for multi-tenant isolation.

---

## 2026-01-22

### Technology Stack Evaluations (Simplified)

**Files created:**
- `BACKEND_FRAMEWORK_EVALUATION.md` - Comprehensive analysis of 7 Python backend frameworks + 6 job queue options
- `HOSTING_EVALUATION.md` - Comprehensive analysis of 10 hosting platforms for POC/MVP deployment
- `PLAN_ATTACHMENT_STORAGE.md` - Detailed implementation plan for email attachment storage (6 phases)
- `SIMPLIFIED_STACK.md` - Reality check on avoiding feature creep, why Redis/ARQ not needed for POC/MVP

**Files modified:**
- `CLAUDE.md` - Added "Backend Technology Stack" section with simplified recommendations (FastAPI + Supabase only)
- `README.md` - Added "Planned (MVP)" tech stack section

**Backend Framework Decision:**
- **Selected:** FastAPI (standalone)
- **Score:** 92% (highest of 7 frameworks evaluated)
- **Rationale:** Async-native, automatic OpenAPI docs, type-safe, low overhead for solo dev, production-ready
- **Rejected:** Django+DRF (conflicts with Supabase RLS architecture)
- **Alternatives:** Litestar (81%), Flask (79%)

**Background Jobs Decision:**
- **POC:** FastAPI BackgroundTasks (in-process, simple)
- **MVP:** PostgreSQL table-based queue if needed (uses existing Supabase, free)
- **Scale:** Redis + ARQ only when actually needed (1000s jobs/hour)
- **Rationale:** YAGNI principle - don't add Redis until you measure the need

**Polling/Scheduling Decision:**
- **Selected:** Supabase pg_cron (built-in PostgreSQL extension)
- **Alternative:** APScheduler (Python) or systemd timers on Fly.io
- **Rationale:** Use what's already available in Supabase

**Hosting Platform Decision:**
- **Selected:** Fly.io
- **Score:** 91% (highest of 10 platforms evaluated)
- **Rationale:** Best free tier ($0/mo POC), perfect FastAPI support, minimal DevOps, production-ready scaling
- **Alternative:** Railway (86%, better DX but $15/mo)
- **Rejected:** AWS/Azure (overkill), Heroku (overpriced), VPS (too much ops work)

**Simplified Stack:**
- POC: FastAPI + Supabase (2 components, $0/mo)
- MVP: Add PostgreSQL queue if needed (still 2 components, $25/mo for Supabase Pro)
- Scale: Add Redis only when PostgreSQL queue insufficient (measure first!)

**Evaluation Criteria:**
- Backend: 14 weighted criteria (developer velocity, learning curve, API development, job queue integration, observability, etc.)
- Hosting: 14 weighted criteria (developer experience, operational overhead, cost, FastAPI support, Redis hosting, etc.)
- Both evaluations include cost projections, code examples, deployment configs, migration strategies

**Key Insights:**
1. Modern platforms (Fly.io, Railway) vastly better than traditional cloud (AWS/Azure) for solo developers
2. FastAPI ideal for async workloads with Supabase
3. PostgreSQL can handle queues for POC/MVP (table-based or LISTEN/NOTIFY)
4. Supabase pg_cron handles scheduling (no need for external cron service)
5. Start with $0/mo (Fly.io free tier + Supabase free tier)
6. Add complexity only when measured limits are hit (YAGNI)

**Reason:** Document technology decisions for backend framework and hosting platform before MVP implementation. Reality check on avoiding premature optimization and feature creep - start simple, add complexity only when needed.

---

### Integration Tests Implementation

**Files created:**
- `backend/tests/integration/__init__.py` - Integration tests package
- `backend/tests/integration/conftest.py` - Integration test fixtures (authenticated clients, temp users, cleanup)
- `backend/tests/integration/test_integration_auth.py` - Authentication tests (6 tests)
- `backend/tests/integration/test_integration_users.py` - User management tests (10 tests)
- `backend/tests/integration/test_integration_oauth.py` - OAuth credential storage tests (10 tests)
- `backend/tests/integration/test_integration_gmail.py` - Gmail API tests with mocking (13 tests)
- `backend/tests/integration/test_integration_emails.py` - Email parsing and storage tests (15 tests)
- `backend/tests/integration/test_integration_e2e.py` - End-to-end pipeline tests (4 tests)
- `backend/tests/integration/test_integration_cli.py` - CLI subprocess tests (13 tests)

**Files modified:**
- `backend/pyproject.toml` - Added pytest markers (integration, development, staging, production), responses library for HTTP mocking
- `INTEGRATION_TESTS_PLAN.md` - Added OAuth automation section explaining how to avoid manual re-auth
- `CLAUDE.md` - Updated test directory structure, added test commands and marker documentation

**Test Coverage:**
- **71 integration tests** covering all services
- Development tests: Local Supabase + mocked Gmail API
- Staging tests: Cloud Supabase + real Gmail (burner account)
- Full automation: OAuth tokens auto-refresh, no manual intervention after initial setup

**Reason:** Implement integration tests as planned in INTEGRATION_TESTS_PLAN.md to ensure all services work correctly with real Supabase.

---

### Integration Tests Plan

**Files created:**
- `INTEGRATION_TESTS_PLAN.md` - Comprehensive plan for implementing integration tests

**Contents:**
- Environment strategy (development/staging/production) with different test approaches per environment
- Test categories: Authentication, User Management, OAuth, Gmail API, Email Pipeline, E2E, CLI
- Pytest markers for selective test execution
- Integration test fixtures design
- Burner Gmail account setup instructions for staging tests
- CI/CD GitHub Actions workflow template
- Implementation order (8 phases)
- Test data management strategy

**Reason:** Plan integration testing strategy before implementation. Staging environment will use real Gmail API with burner accounts for validation.

---

### POC Hardening - Testing, Logging, and Fixes

**Files created:**
- `backend/selko/logging.py` - Centralized logging configuration with verbose/quiet support
- `backend/tests/__init__.py` - Test suite package marker
- `backend/tests/conftest.py` - Pytest fixtures for testing
- `backend/tests/test_config.py` - Configuration loading tests
- `backend/tests/test_emails.py` - Email parsing tests (RFC 5322 compliance)
- `backend/tests/test_integrations.py` - OAuth credential storage tests
- `supabase/migrations/20260122000002_add_indexes.sql` - Performance indexes for emails, integrations, attachments
- `supabase/migrations/20260122000003_add_updated_at_triggers.sql` - Auto-update timestamps on integrations/users

**Files modified:**
- `backend/selko/config.py` - Added `add_logging_arguments()` helper, improved error handling, use logger
- `backend/selko/services/auth.py` - Use logging, catch specific `AuthApiError`
- `backend/selko/services/users.py` - Use logging, conditional email confirmation by environment
- `backend/selko/services/integrations.py` - Use logging, catch specific `PostgrestAPIError`
- `backend/selko/services/gmail.py` - Use logging, catch `RefreshError`/`HttpError`, add rate limiting
- `backend/selko/services/emails.py` - Use stdlib `email.utils` for RFC 5322 parsing, use upsert for efficiency
- `cli/cli_user.py` - Add `-v`/`--verbose` and `-q`/`--quiet` flags
- `cli/cli_auth_gmail.py` - Add verbose/quiet flags, use logging
- `cli/cli_fetch_emails.py` - Add verbose/quiet flags, use logging
- `backend/pyproject.toml` - Add test dependencies (pytest, pytest-cov)
- `pyproject.toml` - Add test dependencies
- `CLAUDE.md` - Updated structure, CLI flags, database indexes/triggers
- `README.md` - Updated structure, added testing section

**Improvements:**
1. **Logging Infrastructure**: Replace all `print()` with Python logging module; CLI supports `-v`/`-q` flags
2. **Email Parsing Fix**: Use stdlib `email.utils.parseaddr()` and `getaddresses()` for RFC 5322 compliance (handles quoted names with commas, angle brackets)
3. **Database Efficiency**: Replace 2-query SELECT+INSERT/UPDATE pattern with single upsert
4. **Exception Handling**: Catch specific exceptions (`AuthApiError`, `PostgrestAPIError`, `RefreshError`) instead of generic `Exception`
5. **Conditional Email Confirmation**: Auto-confirm users in development only; staging/production require email verification
6. **Gmail Rate Limiting**: Exponential backoff for 429 errors, small delays between requests
7. **Database Indexes**: Add indexes for common query patterns (user+date, content_hash, status)
8. **Database Triggers**: Auto-update `updated_at` timestamps on integrations and users tables
9. **Test Suite**: 27 unit tests covering config, email parsing, and integrations

**Reason:** POC hardening to improve code quality, reliability, and maintainability before further development.

---

### 1159713 - Refactor POC to monorepo with proper user authentication

**Files created:**
- `backend/pyproject.toml` - Backend package configuration
- `backend/selko/__init__.py` - Backend package marker
- `backend/selko/config.py` - Centralized configuration (enhanced from poc/config.py)
- `backend/selko/services/__init__.py` - Services package exports
- `backend/selko/services/auth.py` - User authentication with sign_in_with_password
- `backend/selko/services/users.py` - User CRUD with admin (service role) operations
- `backend/selko/services/integrations.py` - OAuth token storage in database
- `backend/selko/services/gmail.py` - Gmail OAuth flow and API interactions
- `backend/selko/services/emails.py` - Email parsing and database storage
- `cli/pyproject.toml` - CLI package configuration
- `cli/__init__.py` - CLI package marker
- `cli/cli_user.py` - User management CLI (create, list, delete)
- `cli/cli_auth_gmail.py` - Gmail OAuth CLI (stores tokens in database)
- `cli/cli_fetch_emails.py` - Email fetching CLI
- `cli/credentials.json` - Moved from poc/
- `supabase/migrations/20260122000001_auto_create_user_profile.sql` - Trigger for auto-creating user profiles
- `web/README.md` - Web frontend placeholder
- `ios/README.md` - iOS app placeholder
- `android/README.md` - Android app placeholder

**Files modified:**
- `pyproject.toml` - Converted to uv workspace configuration
- `.env.example` - Added TEST_USER_EMAIL and TEST_USER_PASSWORD
- `CLAUDE.md` - Updated with new monorepo structure and CLI commands
- `README.md` - Updated with new project structure and setup instructions

**Files deleted:**
- `poc/` directory - Replaced by backend/ and cli/ packages

**Reason:** Major refactoring to:
1. Implement proper user authentication with RLS enforcement (no more --user-id flag)
2. Store OAuth tokens in database instead of local token.json files
3. Reorganize as monorepo with separate backend and CLI packages
4. Add user management CLI since Supabase CLI doesn't support user CRUD
5. Add database trigger to auto-create user profiles on signup

---

## 2026-01-21

### 564d62b - Update documentation with POC multi-environment support

**Files changed:**
- `CLAUDE.md` - Added POC Scripts section with module descriptions and CLI usage examples
- `README.md` - Updated Local Development section with new commands, added Multi-Environment Support section, updated Project Structure to include new files

**Reason:** Document the new multi-environment POC configuration system for developers.

---

### ed0a44e - Support both SUPABASE_ANON_KEY and SUPABASE_PUBLISHABLE_API_KEY in config

**Files changed:**
- `poc/config.py` - Added fallback to check `SUPABASE_PUBLISHABLE_API_KEY` if `SUPABASE_ANON_KEY` is not set

**Reason:** Allow using either the legacy JWT-based anon key or the newer publishable API key format for Supabase client authentication. Staging environment had only the publishable key configured.

---

### ffdc3ca - Add auto-commit workflow instruction to CLAUDE.md

**Files changed:**
- `CLAUDE.md` - Added Workflow section with auto-commit instruction

**Reason:** Ensure Claude Code automatically commits and pushes after completing each stage of work.

---

### 9a41f34 - Add environment-aware config and Supabase integration to POC

**Files changed:**
- `poc/__init__.py` - Created package marker
- `poc/config.py` - Created centralized configuration module with environment detection (development/staging/production)
- `poc/auth_gmail.py` - Updated to use config module, added `--env` CLI argument
- `poc/fetch_emails.py` - Updated to use config module, added Supabase integration for storing emails, added `--env` and `--user-id` CLI arguments
- `pyproject.toml` - Added supabase dependency
- `uv.lock` - Updated with supabase and its dependencies

**Reason:** Implement 3-environment strategy (development/staging/production) for POC scripts, enabling testing against different Supabase instances.

---

### 1649551 - Add project documentation

**Files changed:**
- `README.md` - Created with project overview, setup instructions, environment variables, and project structure
- `CLAUDE.md` - Added Supabase environment configuration, CLI commands, and database schema documentation
- `.env.example` - Expanded with comprehensive template including all Supabase and Google OAuth variables

**Reason:** Provide comprehensive documentation for developers setting up and working with the project.

---

### ddf8fa6 - Fix uuid generation to use built-in gen_random_uuid()

**Files changed:**
- `supabase/migrations/20260121000001_create_users.sql` - Removed uuid-ossp extension dependency
- `supabase/migrations/20260121000002_create_integrations.sql` - Changed `uuid_generate_v4()` to `gen_random_uuid()`
- `supabase/migrations/20260121000003_create_emails.sql` - Changed `uuid_generate_v4()` to `gen_random_uuid()`
- `supabase/migrations/20260121000004_create_attachments.sql` - Changed `uuid_generate_v4()` to `gen_random_uuid()`

**Reason:** Replace `uuid_generate_v4()` with `gen_random_uuid()` which is built into PostgreSQL 13+ and doesn't require the uuid-ossp extension. Fixes migration failures on fresh Supabase projects where the extension schema isn't in the search_path.

---

### 48d34aa - Fix function search_path security warning

**Files changed:**
- `supabase/migrations/20260121000005_fix_function_search_path.sql` - Created migration to set immutable search_path on `parse_gmail_labels` trigger function

**Reason:** Set immutable search_path on trigger function to prevent search_path injection attacks. Addresses Supabase security advisor warning.

---

### 0b52051 - Add Supabase setup with Gmail schema migrations

**Files changed:**
- `.env.example` - Created with basic Supabase configuration template
- `.gitignore` - Added entries for environment files and Supabase local data
- `pyproject.toml` - Added python-dotenv dependency
- `supabase/.gitignore` - Created for Supabase CLI local files
- `supabase/config.toml` - Created Supabase CLI configuration
- `supabase/migrations/20260121000001_create_users.sql` - Created users table with RLS
- `supabase/migrations/20260121000002_create_integrations.sql` - Created integrations table for OAuth tokens
- `supabase/migrations/20260121000003_create_emails.sql` - Created emails table with Gmail label parsing trigger
- `supabase/migrations/20260121000004_create_attachments.sql` - Created attachments table
- `uv.lock` - Updated with python-dotenv

**Reason:** Initialize Supabase CLI project and create database schema for Gmail integration POC. Establishes foundation for storing synced emails with proper RLS policies.

---

### f2d6a0f - Add Gmail API integration POC with OAuth authentication

**Files changed:**
- `.gitignore` - Created with Python, credentials, and IDE ignores
- `.python-version` - Set Python version to 3.10
- `CLAUDE.md` - Created with project overview and development instructions
- `LICENSE` - Created proprietary license file
- `PRD_ARCH.md` - Created product requirements and architecture specification
- `poc/auth_gmail.py` - Created Gmail OAuth authentication script
- `poc/fetch_emails.py` - Created email fetching script
- `pyproject.toml` - Created with project dependencies (google-auth, google-api-python-client)
- `uv.lock` - Created with locked dependencies

**Reason:** Initial project setup with Gmail API integration POC for validating email ingestion functionality.
