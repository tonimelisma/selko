# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Selko** is an AI-powered assistant that automates personal organization by analyzing digital inputs (emails, photos) to manage schedules, to-do lists, and digital filing systems. The system acts as a "Human-in-the-loop" filter, ensuring accuracy before committing changes to permanent records.

See `PRD_ARCH.md` for complete product requirements and technical architecture specification.
See `docs/architecture/ARCHITECTURE.md` for high-level system diagrams.

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

See `docs/guides/gemini-integration.md` for detailed LLM integration patterns.

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

### Environment Configuration

| File | Purpose | Committed |
|------|---------|-----------|
| `.env` | Local development (Docker) | No |
| `.env.test` | Staging environment | No |
| `.env.production` | Production environment | No |
| `.env.example` | Template for setup | Yes |

### Supabase Setup

**Environments:**
| Environment | Project Ref | URL |
|-------------|-------------|-----|
| Local | N/A | `http://localhost:54321` |
| Staging | `lxmysergoeaegxlyfzwk` | `https://lxmysergoeaegxlyfzwk.supabase.co` |
| Production | `khahcozfbnpykspvatrg` | `https://khahcozfbnpykspvatrg.supabase.co` |

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
| `development` | Tests against local Supabase |
| `staging` | Tests against staging Supabase + real Gmail |
| `production` | Read-only smoke tests for production |

See `INTEGRATION_TESTS_PLAN.md` for detailed testing strategy.

### Authentication Model

All CLI operations use proper user authentication:

1. **User Management**: Uses service role key for admin operations (create/delete users)
2. **Other Operations**: Sign in with `TEST_USER_EMAIL`/`TEST_USER_PASSWORD` from `.env`
3. **RLS Enforcement**: All operations respect Row Level Security policies

No more `--user-id` flag needed - the CLI signs in as the configured test user.

## Backend Technology Stack

### Framework Decision (2026-01-22)

**Selected:** FastAPI + Supabase (simplified stack)

See `BACKEND_FRAMEWORK_EVALUATION.md` for complete analysis of 7 frameworks.
See `SIMPLIFIED_STACK.md` for rationale on avoiding feature creep.

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
- `docs/guides/gmail-integration.md` - Gmail API architecture, push vs polling, History API
- `docs/guides/gemini-integration.md` - Vertex AI setup, Pydantic structured outputs, multimodal input

### Architecture Decisions
- `BACKEND_FRAMEWORK_EVALUATION.md` - Why FastAPI (7 frameworks evaluated)
- `HOSTING_EVALUATION.md` - Why Fly.io (10 platforms evaluated)
- `SIMPLIFIED_STACK.md` - Why no Redis/ARQ for POC/MVP

### Plans (Historical)
- `docs/plans/attachment-storage.md` - Email attachment implementation (COMPLETED)

## License

This is **proprietary, commercially copyrighted software** - NOT open source. Copyright (c) 2026 Toni Melisma. See LICENSE file.
