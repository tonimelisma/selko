# Selko

AI-powered assistant that automates personal organization by analyzing digital inputs (emails, photos) to manage schedules, to-do lists, and digital filing systems.

## Project Status

**Phase 1 (POC)**: Validating core functionality with local Python scripts before building the full cloud-based web application.

## Features

### Implemented (POC)
- Email inbox monitoring via Gmail API
- Attachment extraction and storage (Supabase Storage)
- Content deduplication (SHA-256 hashing)
- Multi-environment support (development/staging/production)
- User authentication with Row-Level Security (RLS)
- OAuth token storage in database

### Planned (MVP)
- AI-powered analysis via Gemini LLM (OCR, entity extraction, classification)
- Google Calendar sync (create/update events)
- Human-in-the-loop review interface
- Undo/Redo with compensating transactions
- Automation rules for trusted sources

### Future
- Cloud Photo Library sync
- Web upload interface
- Task management integration
- Mobile app with on-device processing

## Tech Stack

### Current (POC)
- **Backend**: Python, Supabase (PostgreSQL + Auth + Storage)
- **API Framework**: FastAPI (async, with automatic OpenAPI docs)
- **Package Manager**: [uv](https://github.com/astral-sh/uv)
- **Database**: PostgreSQL via Supabase
- **Integrations**: Gmail API, Google Calendar API, Google Photos API

### Planned (MVP)
- **Background Jobs**: FastAPI BackgroundTasks → PostgreSQL queue (if needed)
- **Scheduling**: APScheduler (Python) or pg_cron (Supabase built-in)
- **Hosting**: Render (free tier for POC, scales to production)
- **Cost**: $0/mo (POC on free tiers) → $35-45/mo (MVP)

**Architecture Decision:** Keep it simple - FastAPI + Supabase only. No Redis/ARQ unless measured need (>1000 jobs/hour). See `PRD_ARCH.md` Part 3 for rationale.

## Setup

### Prerequisites

- Python 3.10+
- [uv](https://github.com/astral-sh/uv) package manager
- [Supabase CLI](https://supabase.com/docs/guides/cli)
- Docker Desktop (for local Supabase)

### Installation

```bash
# Clone the repository
git clone https://github.com/tonimelisma/selko.git
cd selko

# Install Python dependencies
uv sync

# Copy environment template
cp .env.example .env
# Edit .env with your local credentials
```

### Local Development

```bash
# Start local Supabase (requires Docker)
supabase start

# Apply migrations
supabase db reset

# Create a test user (one-time setup)
uv run python -m cli.cli_user create --email test@selko.local --password testpass123

# Add credentials to .env
# TEST_USER_EMAIL=test@selko.local
# TEST_USER_PASSWORD=testpass123

# Authenticate with Gmail (stores token in database)
uv run python -m cli.cli_auth_gmail

# Fetch emails
uv run python -m cli.cli_fetch_emails

# Fetch more emails
uv run python -m cli.cli_fetch_emails --max 50

# Set up git pre-commit hook (enforces test requirements)
cp scripts/pre-commit.hook .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

> **First-time setup?** See [TODO.md](TODO.md) for step-by-step checklists for development, staging, and production environments.

### Multi-Environment Support

The application supports three environments via the `ENVIRONMENT` variable:

| Environment | Config File | Supabase |
|-------------|-------------|----------|
| `development` | `.env` | Local (Docker) |
| `staging` | `.env.test` | Cloud staging |
| `production` | `.env.production` | Cloud production |

```bash
# Use staging environment
ENVIRONMENT=staging uv run python -m cli.cli_fetch_emails

# Use production environment
ENVIRONMENT=production uv run python -m cli.cli_user list
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `ENVIRONMENT` | Environment name: `development`, `staging`, or `production` |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_PUBLISHABLE_KEY` | Supabase publishable key (format: `sb_publishable_XXX` or JWT for local) |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase service role key (server-side only) |
| `SUPABASE_JWT_SECRET` | JWT secret for API auth (Dashboard > Settings > API) |
| `SUPABASE_DB_URL` | Direct PostgreSQL connection string |
| `SUPABASE_PROJECT_REF` | Project reference ID |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret |
| `TEST_USER_EMAIL` | Test user email for CLI authentication |
| `TEST_USER_PASSWORD` | Test user password for CLI authentication |

### Database Migrations

Migrations are in `supabase/migrations/`. To deploy:

```bash
# Link to your Supabase project
supabase link --project-ref <PROJECT_REF>

# Push migrations
supabase db push

# Check status
supabase migration list
```

## Project Structure

```
selko/
├── backend/                    # Python backend (shared business logic)
│   ├── selko/
│   │   ├── __init__.py
│   │   ├── config.py          # Centralized configuration
│   │   ├── logging.py         # Centralized logging
│   │   └── services/
│   │       ├── auth.py        # User authentication
│   │       ├── users.py       # User management (admin)
│   │       ├── integrations.py # OAuth token storage
│   │       ├── gmail.py       # Gmail OAuth + API
│   │       ├── emails.py      # Email parsing + storage
│   │       └── attachments.py # Attachment download + storage
│   ├── tests/                  # Test suite
│   │   ├── conftest.py        # Pytest fixtures
│   │   ├── test_*.py          # Unit tests
│   │   └── integration/       # Integration tests
│   ├── api/                    # FastAPI application
│   │   ├── app.py             # App factory
│   │   ├── deps.py            # Dependencies (auth)
│   │   ├── schemas/           # Pydantic models
│   │   └── routes/            # API endpoints
│   └── pyproject.toml
│
├── cli/                        # CLI tools
│   ├── cli_user.py            # User management
│   ├── cli_auth_gmail.py      # Gmail OAuth
│   ├── cli_fetch_emails.py    # Email fetching
│   ├── cli_seed_tokens.py     # Token seeding between environments
│   ├── credentials.json       # Google OAuth credentials (gitignored)
│   └── pyproject.toml
│
├── web/                        # Web frontend (placeholder)
├── ios/                        # iOS app (placeholder)
├── android/                    # Android app (placeholder)
│
├── docs/                       # Documentation
│   ├── architecture/          # System design docs
│   ├── guides/                # Technical integration guides
│   └── plans/                 # Implementation plans
│
├── supabase/
│   ├── config.toml            # Supabase CLI configuration
│   └── migrations/            # Database migrations
│
├── .env                       # Local development config (gitignored)
├── .env.test                  # Staging environment (gitignored)
├── .env.production            # Production environment (gitignored)
├── .env.example               # Environment template
├── pyproject.toml             # Root workspace config
├── CLAUDE.md                  # AI assistant instructions
├── PRD_ARCH.md                # Product requirements & architecture
├── CHANGELOG.md               # Detailed change history
└── README.md                  # This file
```

## API Server

Start the FastAPI development server:

```bash
# Start server with auto-reload
uv run python -m selko.api

# Server runs at http://localhost:8000
# API documentation at http://localhost:8000/docs
```

### Authentication

The API uses Supabase's built-in authentication. You must register/login to get a JWT token, then include it in the `Authorization` header for all authenticated endpoints.

**Supabase Auth Endpoints:**

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `https://<project>.supabase.co/auth/v1/signup` | Register new user |
| POST | `https://<project>.supabase.co/auth/v1/token?grant_type=password` | Login (get JWT) |
| POST | `https://<project>.supabase.co/auth/v1/logout` | Logout |
| GET | `https://<project>.supabase.co/auth/v1/user` | Get current user |

**Register a new user:**

```bash
# Register user (returns access_token)
curl -X POST "https://<project>.supabase.co/auth/v1/signup" \
  -H "apikey: $SUPABASE_ANON_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"secret123"}' \
  | jq -r '.access_token'
```

**Login (if user already exists):**

```bash
# Login and save token
curl -X POST "https://<project>.supabase.co/auth/v1/token?grant_type=password" \
  -H "apikey: $SUPABASE_ANON_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email":"user@example.com","password":"secret123"}' \
  | jq -r '.access_token' > token.txt

TOKEN=$(cat token.txt)
```

**For local development:**

```bash
# Use local Supabase URL
SUPABASE_URL="http://localhost:54321"
SUPABASE_ANON_KEY="<from supabase start output>"

# Register user
curl -X POST "$SUPABASE_URL/auth/v1/signup" \
  -H "apikey: $SUPABASE_ANON_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"testpass123"}' \
  | jq -r '.access_token' > token.txt
```

**Use the token with API requests:**

```bash
TOKEN=$(cat token.txt)
curl -H "Authorization: Bearer $TOKEN" http://localhost:8000/emails
```

### API Endpoints

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/health` | No | Health check |
| GET | `/health/db` | No | Database connectivity check |
| **Emails** | | | |
| GET | `/emails` | Yes | List emails (paginated) |
| GET | `/emails/{id}` | Yes | Get single email with details |
| POST | `/emails/sync` | Yes | Manually fetch emails from Gmail |
| POST | `/emails/{id}/process` | Yes | Extract events from specific email |
| POST | `/emails/batch-process` | Yes | Process multiple recent emails |
| GET | `/emails/{id}/attachments` | Yes | List attachments for an email |
| **Integrations** | | | |
| GET | `/integrations` | Yes | List all integrations |
| GET | `/integrations/{provider}` | Yes | Get integration status |
| GET | `/integrations/gmail/auth` | Yes | Initiate Gmail OAuth (redirects to Google) |
| GET | `/integrations/gmail/callback` | No | OAuth callback (Google redirects here) |
| DELETE | `/integrations/{provider}` | Yes | Disconnect integration |
| **Attachments** | | | |
| GET | `/attachments/{id}` | Yes | Get attachment metadata |
| GET | `/attachments/{id}/download` | Yes | Download attachment file |
| **Events** | | | |
| GET | `/events/new` | Yes | List events pending approval |
| GET | `/events/approved` | Yes | List approved/synced events |
| GET | `/events/updates` | Yes | List event change log |
| GET | `/events/{id}` | Yes | Get event with all source emails |
| POST | `/events/{id}/approve` | Yes | Approve event for calendar sync |
| POST | `/events/{id}/reject` | Yes | Reject event |
| POST | `/events/{id}/restore` | Yes | Restore rejected event |
| POST | `/events/{id}/sync` | Yes | Sync approved event to Google Calendar |
| GET | `/events/{id}/sources` | Yes | List all source emails for event |
| POST | `/events/{id}/sources/{source_id}/undo` | Yes | Undo email contribution |
| POST | `/events/{id}/sources/{source_id}/redo` | Yes | Re-apply undone contribution |

### Manual API Workflow

This workflow demonstrates complete manual control of the Selko system via REST API, step-by-step from registration to calendar sync.

**Prerequisites:**
```bash
# Start local Supabase
supabase start

# Start API server (in separate terminal)
uv run python -m selko.api

# Get Supabase connection details from supabase start output
SUPABASE_URL="http://localhost:54321"
SUPABASE_ANON_KEY="<from output>"
```

**Step 1: Register and Login**

```bash
# Register new user and save token
curl -X POST "$SUPABASE_URL/auth/v1/signup" \
  -H "apikey: $SUPABASE_ANON_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"testpass123"}' \
  | jq -r '.access_token' > token.txt

# OR login if user exists
curl -X POST "$SUPABASE_URL/auth/v1/token?grant_type=password" \
  -H "apikey: $SUPABASE_ANON_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"testpass123"}' \
  | jq -r '.access_token' > token.txt

TOKEN=$(cat token.txt)
```

**Step 2: Connect Gmail (OAuth)**

```bash
# Initiate OAuth flow (opens browser)
curl -X GET "http://localhost:8000/integrations/gmail/auth" \
  -H "Authorization: Bearer $TOKEN"

# This redirects to Google consent screen
# After you approve, Google redirects back to /integrations/gmail/callback
# Callback automatically saves credentials to database

# Verify integration connected
curl -X GET "http://localhost:8000/integrations/gmail" \
  -H "Authorization: Bearer $TOKEN"
```

**Step 3: Fetch Emails**

```bash
# Manually fetch emails from Gmail (with attachments)
curl -X POST "http://localhost:8000/emails/sync" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"max_results":10,"fetch_attachments":true}'

# Response:
# {
#   "fetched": 10,
#   "saved": 10,
#   "attachments_downloaded": 3
# }
```

**Step 4: List Emails**

```bash
# List synced emails
curl -X GET "http://localhost:8000/emails?limit=10" \
  -H "Authorization: Bearer $TOKEN"

# Get specific email
EMAIL_ID=$(curl -s "http://localhost:8000/emails" \
  -H "Authorization: Bearer $TOKEN" | jq -r '.items[0].id')

curl -X GET "http://localhost:8000/emails/$EMAIL_ID" \
  -H "Authorization: Bearer $TOKEN"
```

**Step 5: Process Email (Extract Events)**

```bash
# Extract events from specific email using LLM
curl -X POST "http://localhost:8000/emails/$EMAIL_ID/process" \
  -H "Authorization: Bearer $TOKEN"

# Response:
# {
#   "num_events": 2,
#   "num_new": 2,
#   "num_updated": 0,
#   "event_ids": ["uuid1", "uuid2"]
# }

# OR process multiple recent emails
curl -X POST "http://localhost:8000/emails/batch-process" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"max_emails":5}'
```

**Step 6: Review Pending Events**

```bash
# List events pending approval
curl -X GET "http://localhost:8000/events/new" \
  -H "Authorization: Bearer $TOKEN"

# Get event details with source emails
EVENT_ID=$(curl -s "http://localhost:8000/events/new" \
  -H "Authorization: Bearer $TOKEN" | jq -r '.[0].id')

curl -X GET "http://localhost:8000/events/$EVENT_ID" \
  -H "Authorization: Bearer $TOKEN"
```

**Step 7: Approve Event**

```bash
# Approve event for calendar sync
curl -X POST "http://localhost:8000/events/$EVENT_ID/approve" \
  -H "Authorization: Bearer $TOKEN"

# Response: {"status": "approved"}
```

**Step 8: Sync to Google Calendar**

```bash
# Sync approved event to Google Calendar
curl -X POST "http://localhost:8000/events/$EVENT_ID/sync" \
  -H "Authorization: Bearer $TOKEN"

# Response:
# {
#   "event_id": "uuid",
#   "google_calendar_event_id": "google_event_id",
#   "synced_at": "2026-01-26T12:00:00Z",
#   "status": "synced"
# }
```

**Step 9: Download Attachments (Optional)**

```bash
# List attachments for email
curl -X GET "http://localhost:8000/emails/$EMAIL_ID/attachments" \
  -H "Authorization: Bearer $TOKEN"

# Download specific attachment
ATTACHMENT_ID=$(curl -s "http://localhost:8000/emails/$EMAIL_ID/attachments" \
  -H "Authorization: Bearer $TOKEN" | jq -r '.[0].id')

curl -X GET "http://localhost:8000/attachments/$ATTACHMENT_ID/download" \
  -H "Authorization: Bearer $TOKEN" \
  --output downloaded_file.pdf
```

**Step 10: List Approved Events**

```bash
# View all approved/synced events
curl -X GET "http://localhost:8000/events/approved" \
  -H "Authorization: Bearer $TOKEN"
```

**Complete Journey:**
1. Register/Login → Get JWT token
2. Connect Gmail → OAuth flow
3. Fetch emails → Downloads to database + storage
4. Process email → LLM extracts events
5. Review events → View details with sources
6. Approve event → Mark ready for sync
7. Sync to calendar → Write to Google Calendar
8. Download attachments → Retrieve files

This workflow provides full manual control for development, testing, and CLI automation. All endpoints respect Row Level Security (RLS) - users can only access their own data.

## CLI Commands

### User Management

```bash
# Create a user
uv run python -m cli.cli_user create --email user@example.com --password secret

# List all users
uv run python -m cli.cli_user list

# Delete a user
uv run python -m cli.cli_user delete --user-id <uuid>
```

### Gmail Integration

```bash
# Authenticate with Gmail (interactive OAuth flow)
uv run python -m cli.cli_auth_gmail

# Fetch emails (uses credentials from database)
uv run python -m cli.cli_fetch_emails --max 20

# Fetch emails AND download attachments
uv run python -m cli.cli_fetch_emails --max 10 --fetch-attachments

# Enable verbose logging
uv run python -m cli.cli_fetch_emails -v --max 10

# Quiet mode (only warnings/errors)
uv run python -m cli.cli_fetch_emails -q --max 100
```

### Token Seeding

Copy OAuth tokens between environments to enable local testing with real Gmail API:

```bash
# Copy Gmail tokens from staging to local development
uv run python -m cli.cli_seed_tokens --from staging --to development --provider gmail

# Tokens are copied with automatic user ID remapping
# Required for running development integration tests
```

**Attachment Storage:**
- Files stored in Supabase Storage (`attachments` bucket)
- User-scoped paths: `{user_id}/{unique_id}_{filename}`
- Content deduplication via SHA-256 hash
- Maximum file size: 50 MB

### Running Tests

The project has 71+ tests covering all services. Tests are designed to minimize LLM API costs during local development.

```bash
# Install test dependencies
uv sync --extra test

# Run unit tests only (fast, no external dependencies)
uv run pytest backend/tests/ -m "not integration" -v

# Run development integration tests (local Supabase + mocked LLM)
# One-time setup after supabase start/reset:
supabase start
uv run python -m cli.cli_user create --email test@selko.local --password testpass123 --auto-confirm
uv run python -m cli.cli_seed_tokens --from staging --to development --provider gmail

# Run tests (uses mocked LLM by default)
uv run pytest backend/tests/integration/ -m "development" -v

# Run with REAL LLM (costs money - use sparingly)
uv run pytest backend/tests/integration/ -m "development" --run-llm -v

# Run with coverage report
uv run pytest backend/tests/ --cov=selko
```

**Test Categories:**
| Marker | Description | LLM API |
|--------|-------------|---------|
| `integration` | All integration tests (requires Supabase) | Mocked by default |
| `development` | Tests against local Supabase + real Gmail | Mocked by default |
| `staging` | Tests against staging Supabase + real Gmail | Real (CI only) |
| `llm` | Tests requiring real LLM API calls | Requires `--run-llm` flag |

**Test Architecture:**
- **Unit tests**: Fully mocked, no external dependencies
- **Integration tests (default)**: Real database + real Gmail + **mocked LLM** (no API costs)
- **Integration tests with `--run-llm`**: Real database + real Gmail + **real LLM** (costs money)
- **Staging tests (CI)**: Always run with real LLM to validate deployed environment

**Why Mock LLM Locally?**
- Fast iteration: Run full test suite dozens of times per day without costs
- Test orchestration: Validate service integration, database queries, business logic
- Staging validates real LLM: CI runs real LLM tests after each deployment

**When to Use `--run-llm`:**
- Before committing changes to LLM prompts or schemas
- Debugging LLM-specific issues
- Verifying LLM behavior changes
- NOT needed for most development work (service logic, database, API changes)

**Token Seeding:**

Development tests use real Gmail tokens seeded from staging:

```bash
# Seed tokens from staging to local (with user ID remapping)
uv run python -m cli.cli_seed_tokens --from staging --to development --provider gmail
```

**Before Every Commit:**
1. Run unit tests: `uv run pytest backend/tests/ -m "not integration" -v`
2. Run integration tests (mocked LLM): `uv run pytest backend/tests/integration/ -m "development" -v`
3. If you changed LLM code: `uv run pytest backend/tests/integration/ -m "development" --run-llm -v`

CI will run staging tests with real LLM automatically after deployment.

See `PRD_ARCH.md` Part 4 for detailed testing strategy.

## Documentation

**Core Documents:**
- [CLAUDE.md](CLAUDE.md) - Development guidelines and database schema
- [PRD_ARCH.md](PRD_ARCH.md) - Product requirements and architecture specification
- [CHANGELOG.md](CHANGELOG.md) - Detailed change history

**Architecture & Decisions:**
- [PRD_ARCH.md](PRD_ARCH.md) - Product requirements, architecture, and implementation details

**Technical Guides:**
- [docs/gmail-integration.md](docs/gmail-integration.md) - Gmail API integration details
- [docs/gemini-integration.md](docs/gemini-integration.md) - LLM integration patterns

## License

Proprietary, commercially copyrighted software. Copyright (c) 2026 Toni Melisma. All rights reserved.
