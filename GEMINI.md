# Selko Project Context

## Project Overview
**Selko** is an AI-powered assistant designed to automate personal organization by processing digital inputs (emails, photos) to manage schedules, to-do lists, and digital filing systems.

**Current Phase:** Proof of Concept (POC) / Early MVP.
**Architecture:** Monorepo with a shared Python backend, CLI tools, and a FastAPI service.
**Primary Technologies:**
*   **Language:** Python 3.10+
*   **Package Manager:** `uv`
*   **Database & Auth:** Supabase (PostgreSQL)
*   **API Framework:** FastAPI
*   **AI/LLM:** Gemini (via Vertex AI) - planned for OCR and entity extraction
*   **Integrations:** Gmail API, Google Calendar API

## Directory Structure
*   `backend/`: Shared business logic, services, schemas, and the FastAPI application (`selko.api`).
*   `cli/`: Command-line tools for development and management (`cli_user.py`, `cli_fetch_emails.py`).
*   `supabase/`: Database migrations and local Supabase configuration.
*   `docs/`: Architecture documentation and guides.
*   `.github/workflows/`: CI/CD pipelines.

## Building and Running

### Prerequisites
*   Python 3.10+
*   `uv` package manager
*   Supabase CLI
*   Docker (for local development)

### Installation & Setup
```bash
# Install dependencies
uv sync

# Configure environment
cp .env.example .env
# Edit .env with your credentials (see .env.example)
```

### Local Development Loop
1.  **Start Database:**
    ```bash
    supabase start
    supabase db reset  # Apply migrations and seed if needed
    ```

2.  **Run CLI Tools:**
    ```bash
    # Create test user
    uv run python -m cli.cli_user create --email test@selko.local --password <pass>

    # Fetch emails
    uv run python -m cli.cli_fetch_emails --max 10
    ```

3.  **Run API Server:**
    ```bash
    uv run python -m selko.api
    # Access docs at http://localhost:8000/docs
    ```

### Testing
Use `pytest` via `uv` to run tests.
*   **Unit Tests:** `uv run pytest backend/tests/ -m "not integration"`
*   **Integration Tests (Local DB):** `uv run pytest backend/tests/integration/ -m "development"`
*   **Staging Tests:** `uv run pytest backend/tests/integration/ -m "staging"`

## Development Workflow

### Core Mandates
- **Auto-commit**: After completing each stage of work, automatically git commit and push to remote without waiting for user to request it.
- **Documentation**: After every change, update relevant documentation files:
  - `CLAUDE.md` / `GEMINI.md` - Development instructions, environment setup, database schema.
  - `README.md` - User-facing documentation, setup guides, project structure.
  - `PRD_ARCH.md` - Only for product/architecture specification changes.
- **Changelog**: Maintain `CHANGELOG.md` with detailed entries for every change:
  - Date and commit hash.
  - Files modified with brief description of changes.
  - Reason/purpose for the change.

## Development Conventions

### Code Style & Philosophy
*   **End-to-End First:** Complete full user journeys (e.g., Email -> Calendar) before adding breadth.
*   **LLM-Centric:** Use multimodal LLMs for OCR, entity extraction, and classification instead of specialized narrow models.
*   **YAGNI:** Avoid complex infrastructure (Redis, microservices) until strictly necessary.
*   **Environment Isolation:** Strict separation between `development` (local), `staging` (cloud test), and `production` environments via `.env` files and CI/CD jobs.

### Configuration
Configuration is centralized in `backend/selko/config.py` and loaded via environment variables.
*   `SUPABASE_PUBLISHABLE_KEY` and `SUPABASE_URL` are required.
*   `SUPABASE_SERVICE_ROLE_KEY` is required for admin tasks.

### Database Migrations
Managed via Supabase CLI.
*   New migration: `supabase db diff -f description_of_change`
*   Apply locally: `supabase db reset` (or `up`)
*   Deploy: CI/CD automatically handles `supabase db push` to Staging/Production.

### CI/CD
GitHub Actions workflow (`test.yml`) handles:
1.  Linting & Unit Tests
2.  Integration Tests (against ephemeral local Supabase)
3.  Atomic Deployment to Staging (Migrations + App)
4.  Verification Tests on Staging
