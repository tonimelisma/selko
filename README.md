# Selko

**Your inbox, quietly turned into an organized life.** Selko is an AI-powered personal assistant that reads your emails, understands what actually matters, and keeps your calendar, to-do lists, and digital filing in order — so you don't have to.

## Project Status

**Live in production.** Selko is running today for real users across web, iOS, and Android — turning everyday email into calendar events, with you always in the loop. Powered by [Anthropic's Claude](https://www.anthropic.com/claude).

## The AI behind Selko

Selko's intelligence runs on **Claude (Sonnet 5)**, a state-of-the-art multimodal LLM. Instead of brittle rules and keyword matching, Selko reasons over the *whole* message the way a sharp personal assistant would:

- **Reads everything** — full email threads plus attachments: PDFs, images, itineraries, invitations, tickets. Multimodal understanding means the details buried in a scanned flyer are just as usable as plain text.
- **Understands intent** — resolves dates, times, time zones, locations, and recurrence, and knows the difference between "let's grab lunch sometime" and a confirmed 2 PM booking.
- **Stays accurate** — extractions are continuously benchmarked against a curated evaluation suite, so quality is measured, not assumed.
- **Provider-flexible** — six LLM providers are supported under the hood, with Claude as the default engine.

## Features

- **Smart email understanding** — Gmail inbox monitoring with AI-powered event extraction
- **Multimodal attachment processing** — pulls events out of PDFs and images, not just text
- **Google Calendar sync** — creates and updates events automatically
- **Human-in-the-loop review** — you approve or edit before anything is committed; you're always in control
- **Cross-platform apps** — native web, iOS, and Android clients
- **Secure by design** — per-user Row-Level Security, OAuth token storage, content deduplication, and isolated dev/staging/production environments

### On the roadmap
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
- **AI**: Anthropic Claude — Sonnet 5 (multimodal LLM); 6 providers supported, Claude default
- **Frontends**: Svelte (Web), Kotlin (Android), Swift (iOS)
- **Package Manager**: [uv](https://github.com/astral-sh/uv)

See [PRD_ARCH.md](PRD_ARCH.md) for complete architecture details.

## Setup

### Prerequisites

- Python 3.14+
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
│   └── llm-integration.md    # LLM integration guide
│
├── supabase/                  # Database migrations
├── frontend/                  # Web app (SvelteKit)
├── ios/                       # iOS app (SwiftUI)
├── android/                   # Android app (Jetpack Compose)
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
| [docs/llm-integration.md](docs/llm-integration.md) | LLM integration patterns |

## License

Proprietary, commercially copyrighted software. Copyright (c) 2026 Toni Melisma. All rights reserved.
