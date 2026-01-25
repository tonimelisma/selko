# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Selko** is an AI-powered assistant that automates personal organization by analyzing digital inputs (emails, photos) to manage schedules, to-do lists, and digital filing systems. The system acts as a "Human-in-the-loop" filter, ensuring accuracy before committing changes to permanent records.

See `PRD_ARCH.md` for complete product requirements, technical architecture specification, and implementation details.

---

## ⚠️ DEFINITION OF DONE - READ BEFORE DECLARING WORK COMPLETE

**Before ANY work increment is considered complete, ALL of the following MUST pass:**

- [ ] **Run unit tests**: `uv run pytest backend/tests/ -m "not integration" -v`
- [ ] **Run staging integration tests**: `ENVIRONMENT=staging uv run pytest backend/tests/integration/ -m "staging" -v`
- [ ] **Git commit** with conventional commit message format (e.g., `feat:`, `fix:`, `test:`, `docs:`)
- [ ] **Git push** to `origin/main`
- [ ] **Update CHANGELOG.md** with detailed entry (if not already done during implementation)

**DO NOT declare work complete, say "done", or mark todos as complete until ALL checklist items pass.**

**Critical:** Staging tests validate real integrations (Gmail API, cloud Supabase) and MUST pass on every commit to ensure production readiness. Never skip staging tests.

---

## Development Philosophy

### End-to-End First
**CRITICAL PRINCIPLE:** Complete full end-to-end journeys before expanding scope.

- Do NOT add new inputs (Google Photos) until current input (Email) works end-to-end
- Do NOT add new outputs (File Storage, Task Management) until current output (Calendar) works end-to-end
- Each journey must be fully functional before adding complexity

**First Complete Journey: Email → Calendar Event**
```
Email arrives → Fetch via Gmail API → LLM extracts event details →
User reviews → Approve/Edit → Write to Google Calendar → Done
```

### AI Architecture: LLM-Centric
**All intelligence features use the same multimodal LLM (Gemini):**
- OCR & text extraction → LLM reads images/PDFs directly (multimodal)
- Entity extraction → LLM extracts dates, times, locations, vendors, amounts
- Document classification → LLM categorizes content type (receipt, invitation, etc.)

**No separate OCR service needed.** The LLM is multimodal and handles all of FR-B.1, FR-B.2, and FR-B.3 from the PRD.

See `docs/gemini-integration.md` for detailed LLM integration patterns.

### YAGNI (You Aren't Gonna Need It)
Add complexity only when measured need exists:
- No Redis until you measure queue performance issues
- No separate microservices until you hit scaling limits
- Start with the simplest solution that works

## Development Environment

### Python Environment Management
- **Package Manager**: Use `uv` for all Python package management and environment operations
- **File Deletion**: Use `trash` command instead of `rm` for safer file deletion

### Project Phase
This is a **Proof of Concept (POC)** phase using local Python scripts to validate core functionality before building the full cloud-based web application.

### Workflow
- **Auto-commit**: After completing each stage of work, automatically git commit and push to remote without waiting for user to request it
- **Documentation**: After every change, update relevant documentation files:
  - `CLAUDE.md` - Development instructions, environment setup, database schema
  - `README.md` - User-facing documentation, setup guides, project structure
  - `PRD_ARCH.md` - Only for product/architecture specification changes
- **Changelog**: Maintain `CHANGELOG.md` with detailed entries for every change:
  - Date and commit hash
  - Files modified with brief description of changes
  - Reason/purpose for the change

### Test Requirements

Before declaring any work increment complete or making git commits:

1. **Run unit tests**: `uv run pytest backend/tests/ -m "not integration" -v`
2. **Run development integration tests**: 
   - Start local Supabase: `supabase start`
   - Run tests: `uv run pytest backend/tests/integration/ -m "development" -v`
3. **Run staging integration tests** (ALWAYS required):
   - Ensure `.env.test` is configured with staging Supabase credentials
   - Ensure Gmail OAuth tokens exist: `ENVIRONMENT=staging uv run python -m cli.cli_auth_gmail`
   - Run: `ENVIRONMENT=staging uv run pytest backend/tests/integration/ -m "staging" -v`

All tests must pass before committing. Do not commit with skipped or failing tests.

**Critical:** Staging tests validate real integrations (Gmail API, cloud Supabase) and must pass on every commit to ensure production readiness.

### Environment Configuration

| File | Purpose | Committed |
|------|---------|-----------|
| `.env` | Local development (Docker) | No |
| `.env.test` | Staging environment | No |
| `.env.production` | Production environment | No |
| `.env.example` | Template for setup | Yes |

### Supabase Setup

**Supabase Instances:**

There are TWO separate Supabase projects:

| Instance | Project Name | Project Ref | URL | MCP Server Name |
|----------|--------------|-------------|-----|-----------------|
| **Staging** | selko-staging | `lxmysergoeaegxlyfzwk` | `https://lxmysergoeaegxlyfzwk.supabase.co` | `supabase selko-staging` |
| **Production** | selko | `khahcozfbnpykspvatrg` | `https://khahcozfbnpykspvatrg.supabase.co` | `supabase selko` |
| Local | N/A | `http://localhost:54321` | N/A (Docker) | No MCP server |

**MCP Server Usage:**
- When using MCP tools, always specify which instance you're targeting
- `supabase selko-staging` - Use for staging environment queries/operations
- `supabase selko` - Use for production environment queries/operations (read-only!)
- Local development uses Docker (`supabase start`) - no MCP server needed

**Critical:** Never confuse production and staging! Always verify which MCP server you're connected to before running queries.

**CLI Commands:**
```bash
# Local development (requires Docker)
supabase start
supabase db reset

# Link to staging
supabase link --project-ref lxmysergoeaegxlyfzwk
supabase db push

# Link to production
supabase link --project-ref khahcozfbnpykspvatrg
supabase db push

# View migration status
supabase migration list
```

## Monorepo Structure

The project uses a monorepo structure with separate packages:

```
selko/
├── backend/                    # Python backend (shared business logic)
│   ├── selko/
│   │   ├── __init__.py
│   │   ├── config.py          # Centralized configuration
│   │   ├── logging.py         # Centralized logging setup
│   │   ├── api/               # FastAPI application
│   │   │   ├── __init__.py
│   │   │   ├── __main__.py    # Dev server entry point
│   │   │   ├── app.py         # FastAPI app factory
│   │   │   ├── deps.py        # Dependencies (auth, config)
│   │   │   ├── schemas/       # Pydantic response models
│   │   │   │   ├── common.py
│   │   │   │   ├── emails.py
│   │   │   │   └── integrations.py
│   │   │   └── routes/        # API route modules
│   │   │       ├── health.py
│   │   │       ├── emails.py
│   │   │       └── integrations.py
│   │   └── services/
│   │       ├── __init__.py
│   │       ├── auth.py        # User auth (sign in/out)
│   │       ├── users.py       # User CRUD (admin operations)
│   │       ├── integrations.py # OAuth token storage
│   │       ├── gmail.py       # Gmail OAuth + API (with rate limiting)
│   │       ├── emails.py      # Email parsing + storage
│   │       └── attachments.py # Attachment download + storage
│   ├── tests/                  # Test suite
│   │   ├── conftest.py        # Pytest fixtures (unit tests)
│   │   ├── test_config.py     # Config unit tests
│   │   ├── test_emails.py     # Email parsing unit tests
│   │   ├── test_attachments.py # Attachment unit tests
│   │   ├── test_integrations.py # OAuth unit tests (mocked)
│   │   └── integration/       # Integration tests (real Supabase)
│   │       ├── conftest.py    # Integration test fixtures
│   │       ├── test_integration_auth.py
│   │       ├── test_integration_users.py
│   │       ├── test_integration_oauth.py
│   │       ├── test_integration_gmail.py
│   │       ├── test_integration_emails.py
│   │       ├── test_integration_attachments.py
│   │       ├── test_integration_rls_security.py
│   │       ├── test_integration_e2e.py
│   │       ├── test_integration_cli.py
│   │       └── test_integration_api.py  # FastAPI endpoint tests
│   └── pyproject.toml
│
├── cli/                        # CLI tools for POC and development
│   ├── __init__.py
│   ├── cli_user.py            # User management CLI
│   ├── cli_auth_gmail.py      # Gmail OAuth CLI
│   ├── cli_fetch_emails.py    # Email fetch CLI
│   ├── cli_seed_tokens.py     # Token seeding between environments
│   ├── credentials.json       # Google OAuth app credentials
│   └── pyproject.toml
│
├── web/                        # Web frontend (placeholder)
├── ios/                        # iOS app (placeholder)
├── android/                    # Android app (placeholder)
│
├── supabase/                   # Database
│   ├── config.toml
│   └── migrations/
│
├── pyproject.toml              # Root workspace config
└── .env, .env.test, .env.production
```

### CLI Tools

**User Management:**
```bash
# Create a user (first time only per environment)
uv run python -m cli.cli_user create --email test@selko.local --password testpass123

# List all users
uv run python -m cli.cli_user list

# Delete a user
uv run python -m cli.cli_user delete --user-id <uuid>
```

**Gmail Integration:**
```bash
# Authenticate with Gmail (stores token in database)
uv run python -m cli.cli_auth_gmail

# Fetch emails
uv run python -m cli.cli_fetch_emails --max 10

# Fetch emails AND download attachments
uv run python -m cli.cli_fetch_emails --max 10 --fetch-attachments
```

**Token Seeding (for local-real testing):**
```bash
# Copy Gmail tokens from staging to local development
uv run python -m cli.cli_seed_tokens --from staging --to development --provider gmail

# This enables running real Gmail tests against local Supabase
# Tokens are copied with automatic user ID remapping
```

**Environment Selection:**
```bash
# Use ENVIRONMENT variable to select environment
ENVIRONMENT=staging uv run python -m cli.cli_fetch_emails

# Default is development if not specified
uv run python -m cli.cli_fetch_emails
```

**Environments:**
- `development` (default) - Uses `.env` file, connects to local Supabase
- `staging` - Uses `.env.test` file, connects to cloud staging Supabase
- `production` - Uses `.env.production` file, connects to cloud production Supabase

| Flag | Description |
|------|-------------|
| `-v`, `--verbose` | Enable verbose (DEBUG) logging |
| `-q`, `--quiet` | Only show warnings and errors |
| `--max` | Maximum emails to fetch (for cli_fetch_emails) |
| `--fetch-attachments` | Also download and store email attachments |

### FastAPI Server

**Running the API:**
```bash
# Start development server (with auto-reload)
uv run python -m selko.api

# Server runs at http://localhost:8000
# API docs at http://localhost:8000/docs (Swagger UI)
# ReDoc at http://localhost:8000/redoc
```

**API Endpoints:**
| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | No | Basic health check |
| GET | `/health/db` | No | Database connectivity |
| GET | `/emails` | Yes | List emails (paginated) |
| GET | `/emails/{id}` | Yes | Get single email |
| GET | `/integrations` | Yes | List integrations |
| GET | `/integrations/{provider}` | Yes | Get integration status |

**Authentication:**
The API uses JWT tokens from Supabase. To get a token for testing:
```bash
# Sign in and get access token
TOKEN=$(uv run python -c "
from selko.config import load_config
from selko.services.auth import get_authenticated_client
config = load_config()
client = get_authenticated_client(config)
print(client.auth.get_session().access_token)
")

# Use the token
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/emails
```

**Running Tests:**
```bash
# Install test dependencies
uv sync --extra test

# Run unit tests only (fast, no external dependencies)
uv run pytest backend/tests/ -m "not integration" -v

# Run all tests including integration (requires local Supabase)
supabase start
uv run pytest backend/tests/ -v

# Run integration tests only
uv run pytest backend/tests/integration/ -m "development" -v

# Run staging integration tests (real Gmail)
uv run pytest backend/tests/integration/ -m "staging" -v

# Run with coverage
uv run pytest backend/tests/ --cov=selko
```

**Test Markers:**
| Marker | Description |
|--------|-------------|
| `integration` | All integration tests (requires Supabase) |
| `development` | Tests against local Supabase + real Gmail (requires seeded tokens) |
| `staging` | Tests against staging Supabase + real Gmail |
| `production` | Read-only smoke tests for production |

**All integration tests use real Gmail API** - no mocking. This ensures tests validate actual 3rd-party integration behavior.

See `PRD_ARCH.md` Part 4 for detailed testing strategy.

**Development Testing (Real Gmail with Local Supabase):**

Development tests use local Supabase with real Gmail API tokens seeded from staging.

```bash
# One-time setup after supabase start/reset
supabase start
uv run python -m cli.cli_user create --email test@selko.local --password testpass123 --auto-confirm
uv run python -m cli.cli_seed_tokens --from staging --to development --provider gmail

# Run development integration tests (uses real Gmail)
uv run pytest backend/tests/integration/ -m "development" -v
```

Benefits:
- Test real Gmail integration without deploying to staging
- Fast iteration with isolated local database
- CI automatically seeds tokens and runs these tests

**Token Persistence Rules:**

**Development tests** (local Supabase + real Gmail):
- Database is ephemeral (reset each `supabase start`)
- Uses real Gmail API tokens seeded from staging via `cli_seed_tokens`
- Tokens must be re-seeded after `supabase db reset`
- Tests are READ-ONLY for integrations (preserve seeded tokens)
- Use `pytest.fail()` not `pytest.skip()` when credentials are missing

**Staging tests** (cloud Supabase + real Gmail):
- Database is persistent across runs
- Real OAuth tokens from `cli_auth_gmail` must be preserved
- Staging tests should be READ-ONLY for integrations
- Do NOT use `cleanup_integrations` with real providers in staging
- Use `pytest.fail()` not `pytest.skip()` when credentials are missing

**Production tests**:
- Read-only smoke tests only
- Never modify data

**Test User Management Across Environments:**

Each environment has **separate users with different UUIDs**:

| Environment | Config File | Example Email | User UUID | OAuth Tokens |
|-------------|-------------|---------------|-----------|--------------|
| Development | `.env` | `test@selko.local` | `abc123...` | Seeded from staging |
| Staging | `.env.test` | `test@selko.local` | `xyz789...` | Real from OAuth flow |

OAuth tokens in the `integrations` table are stored with `user_id` foreign key.
When you copy tokens between environments, the `cli_seed_tokens` script automatically
remaps the user ID from the source user to the target user (matched by email).

### Authentication Model

All CLI operations use proper user authentication:

1. **User Management**: Uses service role key for admin operations (create/delete users)
2. **Other Operations**: Sign in with `TEST_USER_EMAIL`/`TEST_USER_PASSWORD` from `.env`
3. **RLS Enforcement**: All operations respect Row Level Security policies

No more `--user-id` flag needed - the CLI signs in as the configured test user.

## CI/CD Pipeline

### Overview

The CI/CD pipeline ensures code quality and manages deployments across three environments:

| Environment | Database | Deployment | Purpose |
|-------------|----------|------------|---------|
| **Development** | Local Docker | Manual (local only) | Fast iteration with isolated database |
| **Staging** | Cloud Supabase | **Automatic on main push** | Pre-production validation with real services |
| **Production** | Cloud Supabase | Manual trigger only | Live environment (manual safety gate) |

### Pipeline Flow

**On Pull Request:**
```
PR opened/updated
    ↓
Unit Tests (no external dependencies)
    ↓
Integration Tests (local Supabase via Docker)
    ↓
✅ PR ready for review (no deployment)
```

**On Push to Main:**
```
Code merged to main
    ↓
Unit Tests + Integration Tests (local Supabase)
    ↓
Deploy to Staging (ATOMIC)
    ├─ 1. Deploy database migrations (supabase db push)
    └─ 2. Deploy FastAPI to Render (auto-deploys via GitHub integration)
    ↓
Integration Tests (Staging)
    └─ Tests the DEPLOYED code with real Gmail API
    ↓
✅ Staging environment running latest code
```

**On Manual Trigger or Git Tag:**
```
workflow_dispatch or tag push
    ↓
Deploy to Production (ATOMIC)
    ├─ 1. Deploy database migrations (supabase db push)
    └─ 2. Deploy FastAPI to Render (manual deploy or auto-deploy on tag)
    ↓
(Optional) Production smoke tests (read-only)
    ↓
✅ Production environment updated
```

### Critical Deployment Principle: Atomic Updates

**Database and application MUST deploy together.**

**Why:** Breaking changes require synchronized deployment:
- New code expecting new schema → 500 errors if schema not updated
- New schema with old code → potential issues if not backward compatible

**Implementation:** Each deployment job runs migrations first, then deploys the application. If migrations fail, application deployment is skipped.

### GitHub Actions Jobs

| Job | Runs On | Dependencies | Purpose |
|-----|---------|--------------|---------|
| `unit-tests` | Every push/PR | None | Fast validation, no external services |
| `integration-tests-development` | Every push/PR | None | Spins up local Supabase in Docker |
| `deploy-staging` | Main push only | unit-tests, integration-tests-development | Deploy DB + API to staging |
| `integration-tests-staging` | Main push only | deploy-staging | Validate deployed staging environment |
| `deploy-production` | Manual/tag only | None | Deploy DB + API to production |

### Required GitHub Secrets

Configure at: Repository → Settings → Secrets and variables → Actions

| Secret | Purpose | How to Generate |
|--------|---------|-----------------|
| `SUPABASE_ACCESS_TOKEN` | Authenticate Supabase CLI for migrations | https://supabase.com/dashboard/account/tokens |
| `STAGING_SUPABASE_URL` | Staging database connection | Supabase dashboard |
| `STAGING_SUPABASE_ANON_KEY` | Staging API access | Supabase dashboard → Settings → API |
| `STAGING_SUPABASE_SERVICE_ROLE_KEY` | Staging admin operations | Supabase dashboard → Settings → API |
| `STAGING_TEST_USER_EMAIL` | Test user for staging integration tests | Burner Gmail account |
| `STAGING_TEST_USER_PASSWORD` | Test user password | Set when creating user |
| `GOOGLE_CLIENT_ID` | OAuth for Gmail integration | Google Cloud Console |
| `GOOGLE_CLIENT_SECRET` | OAuth secret | Google Cloud Console |

**Note on naming:** GitHub secrets use `STAGING_*` prefix to distinguish environments, but the workflow maps these to unprefixed environment variables (`TEST_USER_EMAIL`, etc.) that the code expects.

### Local vs CI Differences

**Local Development:**
- Uses `.env` file with `TEST_USER_EMAIL=test@selko.local`
- Manual deployment (`supabase db push`, `fly deploy`)
- Local Supabase via `supabase start`

**GitHub Actions:**
- Uses GitHub Secrets mapped to environment variables
- Automatic deployment on main push (staging only)
- Ephemeral Supabase instances for dev tests

### Deployment Commands

**Manual Staging Deployment:**
```bash
# Link to staging
supabase link --project-ref lxmysergoeaegxlyfzwk

# Deploy migrations
supabase db push

# FastAPI auto-deploys to Render via GitHub integration
# See PRD_ARCH.md Part 3 for deployment details
```

**Manual Production Deployment:**
```bash
# Link to production
supabase link --project-ref khahcozfbnpykspvatrg

# Deploy migrations
supabase db push

# FastAPI deploys to Render (manual or auto on tag)
# See PRD_ARCH.md Part 3 for deployment details
```

**Trigger Production Deployment via GitHub:**
```bash
# Option 1: Manual workflow dispatch
gh workflow run test.yml

# Option 2: Create and push a tag
git tag -a v1.0.0 -m "Release 1.0.0"
git push origin v1.0.0
```

See `PRD_ARCH.md` Part 3 for Render deployment details.

## Backend Technology Stack

### Framework Decision (2026-01-22)

**Selected:** FastAPI + Supabase (simplified stack)

See `PRD_ARCH.md` Part 3 for stack decisions and rejection rationale.

**Why FastAPI:**
- Async-native (efficient with Supabase I/O)
- Automatic OpenAPI/Swagger documentation
- Type-safe with Pydantic (works with existing type hints)
- Low overhead for solo developer
- Production-ready (Netflix, Uber, Microsoft)
- Score: 92% (highest ranked)

**Why NOT Redis/ARQ (for now):**
- Supabase PostgreSQL can handle queues (table-based or LISTEN/NOTIFY)
- Supabase pg_cron handles polling/scheduling (built-in)
- FastAPI BackgroundTasks sufficient for simple async jobs
- Add Redis only when you actually need it (YAGNI principle)

**Alternative Considered:** Django+DRF rejected (conflicts with Supabase RLS architecture)

**Simplified Stack:**
- POC: FastAPI + Supabase (2 components)
- MVP: Add PostgreSQL queue if BackgroundTasks insufficient (still free)
- Scale: Add Redis + ARQ only when hitting real limits (1000s jobs/hour)

**Migration Strategy:**
- Phase 1: Keep CLI tools (current)
- Phase 2: Add FastAPI with BackgroundTasks (non-breaking)
- Phase 3: Add PostgreSQL table queue if needed (still using Supabase)
- Phase 4: Add Redis/ARQ only if PostgreSQL queue can't keep up
- CLI tools remain for development/debugging

**When to Implement:**
- Start building web/mobile UI (need REST APIs)
- Need webhooks (e.g., Gmail push notifications)
- Have background jobs (attachment OCR, AI processing)

## Architecture Overview

### Phased Approach
1. **Phase 1 (Current POC)**: Local Python scripts to prove AI processing capabilities
2. **Phase 2 (MVP)**: Web-First Cloud Processing with responsive web dashboard
3. **Phase 3**: Mobile companion app with local inference

### Core System Components (Target Architecture)

**Data Flow**: Ingestion → Analysis → Review → Execution

1. **Ingestion Layer**
   - Cloud Photo Library sync
   - Email inbox monitoring with attachment extraction
   - Manual web upload interface

2. **Intelligence Engine**
   - OCR & text extraction (handwriting recognition)
   - Entity extraction (dates, times, locations, vendors, amounts)
   - Document classification (receipts, invitations, drawings, etc.)
   - Smart idempotency & update detection
   - User-defined automation rules

3. **Review Interface**
   - Side-by-side view (source asset vs. extracted data)
   - Edit, approve, or reject functionality
   - Undo/Redo with compensating transactions

4. **Output Layer**
   - Calendar sync (create/update events)
   - Cloud file storage (categorized uploads)
   - Task management integration

### Database Schema (POC)

Current tables in `supabase/migrations/`:

**`users`** - User profiles linked to Supabase Auth
- `id` (uuid, PK) → references `auth.users`
- `email`, `display_name`, timestamps
- RLS: Users can view/update/insert own profile
- Auto-created via trigger on auth.users insert

**`integrations`** - OAuth tokens for external providers
- `provider`: `gmail`, `google_photos`, `google_calendar`
- `status`: `active`, `expired`, `revoked`, `error`
- `access_token`, `refresh_token`, `token_expiry`
- `scopes[]` - OAuth scopes granted
- `provider_email` - Email associated with integration
- `last_history_id` - Gmail sync cursor
- RLS: Users manage own integrations
- Indexes: `idx_integrations_user_status` for status queries
- Triggers: `set_integrations_updated_at` auto-updates timestamp

**`emails`** - Synced Gmail messages
- Gmail identifiers: `gmail_id`, `thread_id`
- Headers: `subject`, `from_email`, `from_name`, `to_emails`, `date_sent`
- `gmail_label_ids[]` - Raw labels from Gmail API
- Auto-computed flags (via trigger): `is_spam`, `is_trash`, `is_promotions`, `is_social`, `is_updates`, `is_forums`, `is_primary`, `is_important`, `is_starred`, `is_unread`
- `content_hash` - For deduplication
- RLS: Users manage own emails
- Indexes: `idx_emails_user_date` for date queries, `idx_emails_content_hash` for deduplication

**`attachments`** - Email attachment metadata
- `gmail_attachment_id`, `filename`, `mime_type`, `size_bytes`
- `storage_path` - Reference to Supabase Storage
- `content_hash` - For deduplication (SHA-256)
- RLS: Users manage own attachments
- Index: `idx_attachments_content_hash` for deduplication lookups

**Supabase Storage Bucket: `attachments`**
- Private bucket (not publicly accessible)
- 50 MB file size limit
- User-scoped paths: `{user_id}/{unique_id}_{filename}`
- RLS policies: Users can only access files in their own folder
- Supported MIME types: images, PDFs, Office docs, text, CSV, ZIP

### Future Data Model (MVP)

- **assets**: Raw input units (emails, photos, PDFs) with content hashing for deduplication
- **inferences**: AI-extracted structured data from assets (1 asset → N inferences)
  - States: PENDING_REVIEW, APPROVED, REJECTED, AUTO_EXECUTED
- **automation_rules**: User-defined logic to bypass manual review
- **action_history**: Ledger for undo/redo with state snapshots

### Critical Business Logic

**Update vs. Create Detection**: System must semantically detect if a new asset is an update to existing data (e.g., "Time Changed" email) and merge values rather than creating duplicates.

**Compensating Transactions**: Every action (CREATE/UPDATE/DELETE) must be reversible by storing previous_state and external resource IDs.

## Next Steps (MVP Roadmap)

Implementation order (end-to-end focus):

| Priority | Feature | PRD Reference | Notes |
|----------|---------|---------------|-------|
| **1** | LLM integration | FR-B.1, FR-B.2, FR-B.3 | Gemini via Vertex AI |
| **2** | Email → LLM analysis | FR-A.2 + FR-B.* | Parse emails/attachments with AI |
| **3** | Calendar sync (write) | FR-D.1 | Complete first end-to-end journey |
| **4** | Review interface | FR-C.1 | Human-in-loop before auto-execution |
| **5** | Undo/Redo | FR-C.2 | Safety net for calendar writes |
| **6** | Automation rules | FR-B.5 | Bypass review for trusted sources |
| **7** | FastAPI web framework | Architecture | API for web/mobile clients |
| **8** | Google Photos sync | FR-A.1 | ONLY after email→calendar works |

## Reference Documentation

### Technical Guides
- `docs/gmail-integration.md` - Gmail API architecture, push vs polling, History API
- `docs/gemini-integration.md` - Vertex AI setup, Pydantic structured outputs, multimodal input

## License

This is **proprietary, commercially copyrighted software** - NOT open source. Copyright (c) 2026 Toni Melisma. See LICENSE file.
