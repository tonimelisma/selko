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

- Python 3.11+
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

# Run the POC scripts
uv run python poc/fetch_emails.py
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
├── poc/                    # Proof of concept scripts
│   ├── fetch_emails.py     # Gmail API integration
│   ├── credentials.json    # Google OAuth credentials (gitignored)
│   └── token.json          # OAuth tokens (gitignored)
├── supabase/
│   ├── config.toml         # Supabase CLI configuration
│   └── migrations/         # Database migrations
├── .env.example            # Environment template
├── CLAUDE.md               # AI assistant instructions
├── PRD_ARCH.md             # Product requirements & architecture
├── pyproject.toml          # Python project configuration
└── README.md               # This file
```

## Documentation

- [CLAUDE.md](CLAUDE.md) - Development guidelines and database schema
- [PRD_ARCH.md](PRD_ARCH.md) - Product requirements and architecture specification

## License

Proprietary, commercially copyrighted software. Copyright (c) 2026 Toni Melisma. All rights reserved.
