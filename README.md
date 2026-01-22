# Selko

AI-powered assistant that automates personal organization by analyzing digital inputs (emails, photos) to manage schedules, to-do lists, and digital filing systems.

## Project Status

**Phase 1 (POC)**: Validating core functionality with local Python scripts before building the full cloud-based web application.

## Features (Planned)

- Email inbox monitoring with attachment extraction
- Cloud Photo Library sync
- OCR & text extraction (including handwriting)
- Entity extraction (dates, times, locations, vendors, amounts)
- Document classification (receipts, invitations, drawings)
- Calendar sync with create/update events
- Human-in-the-loop review interface

## Tech Stack

- **Backend**: Python, Supabase (PostgreSQL + Auth + Storage)
- **Package Manager**: [uv](https://github.com/astral-sh/uv)
- **Database**: PostgreSQL via Supabase
- **Integrations**: Gmail API, Google Calendar API, Google Photos API

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
```

### Multi-Environment Support

The CLI supports three environments via the `--env` flag or `ENVIRONMENT` variable:

| Environment | Config File | Supabase |
|-------------|-------------|----------|
| `development` | `.env` | Local (Docker) |
| `staging` | `.env.test` | Cloud staging |
| `production` | `.env.production` | Cloud production |

```bash
# Use staging environment
uv run python -m cli.cli_fetch_emails --env staging

# Use production environment
uv run python -m cli.cli_user list --env production
```

### Environment Variables

| Variable | Description |
|----------|-------------|
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_ANON_KEY` | Supabase anonymous/public key |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase service role key (server-side only) |
| `SUPABASE_DB_URL` | Direct PostgreSQL connection string |
| `SUPABASE_PROJECT_REF` | Project reference ID |
| `GOOGLE_CLIENT_ID` | Google OAuth client ID |
| `GOOGLE_CLIENT_SECRET` | Google OAuth client secret |
| `ENVIRONMENT` | `development`, `staging`, or `production` |
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
│   │   └── services/
│   │       ├── auth.py        # User authentication
│   │       ├── users.py       # User management (admin)
│   │       ├── integrations.py # OAuth token storage
│   │       ├── gmail.py       # Gmail OAuth + API
│   │       └── emails.py      # Email parsing + storage
│   └── pyproject.toml
│
├── cli/                        # CLI tools
│   ├── cli_user.py            # User management
│   ├── cli_auth_gmail.py      # Gmail OAuth
│   ├── cli_fetch_emails.py    # Email fetching
│   ├── credentials.json       # Google OAuth credentials (gitignored)
│   └── pyproject.toml
│
├── web/                        # Web frontend (placeholder)
├── ios/                        # iOS app (placeholder)
├── android/                    # Android app (placeholder)
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
```

## Documentation

- [CLAUDE.md](CLAUDE.md) - Development guidelines and database schema
- [PRD_ARCH.md](PRD_ARCH.md) - Product requirements and architecture specification
- [CHANGELOG.md](CHANGELOG.md) - Detailed change history

## License

Proprietary, commercially copyrighted software. Copyright (c) 2026 Toni Melisma. All rights reserved.
