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
- AI-powered event extraction via Gemini LLM

### Planned (MVP)
- Google Calendar sync (create/update events)
- Human-in-the-loop review interface
- Undo/Redo with compensating transactions
- Automation rules for trusted sources

## Architecture

**Direct Supabase Access** - All frontends query Supabase directly for data operations. The Python API only handles server-side operations requiring secrets (OAuth, Gmail sync, LLM processing, Calendar sync).

```
Frontend (Web/Android/iOS)
    │
    ├─── Data queries ──→ Supabase (direct, RLS-protected)
    │
    └─── Server-side ops ──→ Python API (9 endpoints)
                              └── OAuth, Gmail, LLM, Calendar
```

## Tech Stack

- **Data Layer**: Supabase (PostgreSQL + Auth + Storage + RLS)
- **Server-Side API**: Python, FastAPI (only for operations requiring secrets)
- **AI**: Google Gemini (multimodal LLM)
- **Frontends**: Svelte (Web), Kotlin (Android), Swift (iOS)
- **Package Manager**: [uv](https://github.com/astral-sh/uv)

See [PRD_ARCH.md](PRD_ARCH.md) for complete architecture details.

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
uv run python -m cli.cli_fetch_emails --max 10

# Set up git pre-commit hook (enforces test requirements)
cp scripts/pre-commit.hook .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

### Multi-Environment Support

| Environment | Config File | Supabase |
|-------------|-------------|----------|
| `development` | `.env` | Local (Docker) |
| `staging` | `.env.test` | Cloud staging |
| `production` | `.env.production` | Cloud production |

```bash
# Use staging environment
ENVIRONMENT=staging uv run python -m cli.cli_fetch_emails
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `ENVIRONMENT` | Environment name: `development`, `staging`, or `production` |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_PUBLISHABLE_KEY` | Supabase publishable key |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase service role key (server-side only) |
| `SUPABASE_JWT_SECRET` | JWT secret for API auth |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret |
| `TEST_USER_EMAIL` | Test user email for CLI authentication |
| `TEST_USER_PASSWORD` | Test user password |

## Project Structure

```
selko/
├── backend/                    # Python backend
│   ├── selko/
│   │   ├── config.py          # Configuration
│   │   ├── api/               # FastAPI application
│   │   ├── services/          # Business logic
│   │   └── workers/           # Background job workers
│   └── tests/                 # Test suite
│
├── cli/                       # CLI tools
│   ├── cli_user.py           # User management
│   ├── cli_auth_gmail.py     # Gmail OAuth
│   ├── cli_fetch_emails.py   # Email fetching
│   └── cli_seed_tokens.py    # Token seeding
│
├── docs/                      # Documentation
│   ├── api-workflow.md       # Manual API workflow examples
│   ├── job-queue.md          # Job queue architecture
│   ├── ci-cd.md              # CI/CD pipeline
│   ├── gmail-integration.md  # Gmail API guide
│   └── gemini-integration.md # LLM integration guide
│
├── supabase/                  # Database migrations
├── web/                       # Web frontend (placeholder)
├── ios/                       # iOS app (placeholder)
├── android/                   # Android app (placeholder)
│
├── CLAUDE.md                  # Development guidelines
├── PRD_ARCH.md               # Product requirements & architecture
└── CHANGELOG.md              # Change history
```

## API Server

The Python API handles **server-side operations only** (OAuth, Gmail sync, LLM processing, Calendar sync). Data queries go directly to Supabase.

```bash
# Start development server
uv run python -m selko.api

# Server: http://localhost:8000
# API docs: http://localhost:8000/docs (Swagger UI)
```

### Available Endpoints (9 total)

| Endpoint | Purpose |
|----------|---------|
| `GET /health` | Health check |
| `GET /integrations/gmail/auth` | Initiate Gmail OAuth |
| `POST /emails/sync` | Sync emails from Gmail |
| `POST /emails/{id}/process` | Extract events with LLM |
| `GET /calendars` | List Google Calendars |
| `POST /events/{id}/sync` | Sync event to Calendar |

### Data Access

All data queries (emails, events, integrations) go **directly to Supabase** from frontends:

```bash
# Login via Supabase Auth
TOKEN=$(curl -s "$SUPABASE_URL/auth/v1/token?grant_type=password" \
  -H "apikey: $SUPABASE_ANON_KEY" \
  -H "Content-Type: application/json" \
  -d '{"email":"test@example.com","password":"testpass123"}' \
  | jq -r '.access_token')

# Query Supabase directly (not the Python API)
curl "$SUPABASE_URL/rest/v1/emails?select=id,subject,from_email&limit=10" \
  -H "apikey: $SUPABASE_ANON_KEY" \
  -H "Authorization: Bearer $TOKEN"
```

See [docs/supabase-frontend-queries.md](docs/supabase-frontend-queries.md) for query patterns and [docs/api-workflow.md](docs/api-workflow.md) for server-side API usage.

## CLI Commands

```bash
# User management
uv run python -m cli.cli_user create --email user@example.com --password secret
uv run python -m cli.cli_user list

# Gmail integration
uv run python -m cli.cli_auth_gmail
uv run python -m cli.cli_fetch_emails --max 20 --fetch-attachments

# Token seeding (for local testing with real Gmail)
uv run python -m cli.cli_seed_tokens --from staging --to development --provider gmail
```

## Running Tests

```bash
# Install test dependencies
uv sync --extra test

# Run all tests (required before commits)
uv run pytest backend/tests/ -v

# Run unit tests only
uv run pytest backend/tests/ -m "not integration" -v

# Run integration tests (requires local Supabase)
supabase start
uv run pytest backend/tests/integration/ -m "development" -v
```

See [CLAUDE.md](CLAUDE.md) for detailed test configuration and markers.

## Documentation

| Document | Purpose |
|----------|---------|
| [CLAUDE.md](CLAUDE.md) | Development guidelines, database schema, test configuration |
| [PRD_ARCH.md](PRD_ARCH.md) | Product requirements and architecture specification |
| [docs/supabase-frontend-queries.md](docs/supabase-frontend-queries.md) | **Canonical query patterns for all frontends** |
| [docs/api-workflow.md](docs/api-workflow.md) | Server-side API workflow (OAuth, sync, LLM) |
| [docs/job-queue.md](docs/job-queue.md) | Job queue architecture |
| [docs/ci-cd.md](docs/ci-cd.md) | CI/CD pipeline details |
| [docs/gmail-integration.md](docs/gmail-integration.md) | Gmail API integration |
| [docs/gemini-integration.md](docs/gemini-integration.md) | LLM integration patterns |

## License

Proprietary, commercially copyrighted software. Copyright (c) 2026 Toni Melisma. All rights reserved.
