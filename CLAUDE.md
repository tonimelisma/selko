# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Selko** is an AI-powered assistant that automates personal organization by analyzing digital inputs (emails, photos) to manage schedules, to-do lists, and digital filing systems. The system acts as a "Human-in-the-loop" filter, ensuring accuracy before committing changes to permanent records.

See `PRD_ARCH.md` for complete product requirements, technical architecture specification, and implementation details.

---

## ⚠️ MANDATORY FOR ALL AI CODING AGENTS ⚠️

### WORKTREES AND PULL REQUESTS

**Source code changes require worktrees. Config/docs edits are allowed in main.**

```
┌─────────────────────────────────────────────────────────────────────────┐
│  Source code (backend/, frontend/src/, ios/, android/, cli/)           │
│    → MUST use worktree + feature branch + PR                           │
│                                                                         │
│  Config files (.env, docs/, CLAUDE.md, scripts/, supabase/)            │
│    → CAN edit directly in main repo                                    │
└─────────────────────────────────────────────────────────────────────────┘
```

**WHY:**
- Multiple AI agents work simultaneously on different features
- Worktrees provide isolated environments per task
- PRs ensure CI runs before code merges
- Config/docs don't conflict, so they're allowed in main

### Naming Conventions

| Type | Format | Example |
|------|--------|---------|
| **Branch** | `<type>/<task-name>` | `feat/add-login`, `fix/api-timeout`, `docs/readme` |
| **Worktree** | `selko-<type>-<task>` | `selko-feat-add-login`, `selko-fix-api-timeout` |

Types: `feat`, `fix`, `refactor`, `test`, `docs`, `chore`

### Pre-Work Checklist (BEFORE starting any task)

Run these commands from the main repo (`/Users/tonimelisma/Development/selko`):

```bash
# 1. Sync main with GitHub
git fetch origin && git merge --ff-only origin/main

# 2. Clean up stale worktrees (merged PRs)
git worktree list
# For each worktree whose branch has been merged:
git worktree remove ../selko-<type>-<old-task>
git branch -D <type>/<old-task>

# 3. Prune any orphaned worktree refs
git worktree prune

# 4. Create your new worktree
git worktree add ../selko-<type>-<task> -b <type>/<task-name> main

# 5. Move to worktree and install dependencies (if needed)
cd ../selko-<type>-<task>
uv sync                      # Python deps
cd frontend && npm ci && cd ..  # JS deps (if changing frontend)
```

### Enforcement: Claude Code Hook

A PreToolUse hook **BLOCKS source code edits** in the main repository:

```
BLOCKED: Cannot edit source code in the main repository.
```

**Blocked in main:** `backend/`, `frontend/src/`, `ios/*.swift`, `android/*.kt`, `cli/`
**Allowed in main:** `docs/`, `.env*`, `CLAUDE.md`, `.claude/*`, `scripts/`, `supabase/`, `*.md`

---

## DEFINITION OF DONE (DOD)

**Before ANY work increment is considered complete, ALL of the following MUST pass:**

- [ ] **Working in a git worktree** (NOT the main repo directory)
- [ ] **On a feature branch** (NOT main)
- [ ] **Run tests for changed modules** (see test commands below)
- [ ] **Update CHANGELOG.md** with detailed entry for the changes
- [ ] **Git commit** with conventional commit message format
- [ ] **Git push** to your feature branch
- [ ] **Create a Pull Request** with `gh pr create --auto`

### After PR Merges

```bash
# Return to main repo
cd /Users/tonimelisma/Development/selko

# Remove your worktree and branch
git worktree remove ../selko-<type>-<task>
git branch -D <type>/<task-name>

# Sync main
git fetch origin && git merge --ff-only origin/main
```

**DO NOT declare work complete until ALL checklist items pass.**

**Critical Requirements:**
- ALL tests must pass, including integration tests that use real APIs (Gmail, Gemini, etc.)
- Development integration tests require: local Supabase running, seeded Gmail tokens, GEMINI_API_KEY configured
- If ANY test is skipped due to missing configuration, DOD is NOT met - fix the configuration first

### Pre-Commit Hook Enforcement

A git pre-commit hook BLOCKS commits unless tests have been run for changed modules.

**Setup (one-time):**
```bash
cp scripts/pre-commit.hook .git/hooks/pre-commit
chmod +x .git/hooks/pre-commit
```

**The hook checks per-module using native test caches:**
- **backend**: pytest cache at `backend/.pytest_cache/v/cache/lastfailed`
- **frontend**: vitest JSON at `frontend/test-results.json`
- **ios**: xcresult bundle at `ios/TestResults.xcresult`
- **android**: gradle results at `android/app/build/test-results/`

For each module with staged changes, the hook verifies:
- Test results exist and show all tests passed
- No source files are newer than the test results

**CRITICAL FOR AI CODING TOOLS:**

If the hook blocks a commit, you MUST:
1. Read the error message to see which modules need tests
2. Run the native test command for each module (see Test Commands below)
3. Fix any failing tests
4. Commit again

You MUST NEVER:
- Use `git commit --no-verify` to bypass the hook
- Suggest bypassing the hook to the user
- Treat the hook as optional

---

## Development Philosophy

### Direct Supabase Access (No Proxy Layers)
**CRITICAL ARCHITECTURAL PRINCIPLE:** Frontends query Supabase directly. No superfluous layers.

All frontends (Web, Android, iOS) must:
1. **Query Supabase directly** for all data operations (emails, events, integrations, etc.)
2. **Use RLS (Row Level Security)** for access control - enforced at database level
3. **Only call Python API** for operations requiring server-side secrets:
   - OAuth flows (client secrets)
   - Gmail sync (API credentials)
   - LLM processing (Gemini API key)
   - Google Calendar sync (API credentials)

**Why this matters:**
- Reduced latency (Frontend → Supabase vs Frontend → Python → Supabase)
- Simpler backend (9 endpoints instead of 35)
- RLS provides consistent security across all access paths
- Each frontend uses its native Supabase SDK

**The Python API is NOT a general-purpose REST API.** It only handles operations that cannot be done client-side due to secrets or server-side processing requirements.

See `docs/supabase-frontend-queries.md` for canonical query patterns.

### End-to-End First
**CRITICAL PRINCIPLE:** Complete full end-to-end journeys before expanding scope.

- Do NOT add new inputs (Google Photos) until current input (Email) works end-to-end
- Do NOT add new outputs (File Storage, Task Management) until current output (Calendar) works end-to-end
- Each journey must be fully functional before adding complexity

**First Complete Journey: Email -> Calendar Event**
```
Email arrives -> Fetch via Gmail API -> LLM extracts event details ->
User reviews -> Approve/Edit -> Write to Google Calendar -> Done
```

### AI Architecture: LLM-Centric
**All intelligence features use the same multimodal LLM (Gemini):**
- OCR & text extraction -> LLM reads images/PDFs directly (multimodal)
- Entity extraction -> LLM extracts dates, times, locations, vendors, amounts
- Document classification -> LLM categorizes content type

**No separate OCR service needed.** The LLM is multimodal and handles all analysis.

See `docs/gemini-integration.md` for detailed LLM integration patterns.

### YAGNI (You Aren't Gonna Need It)
Add complexity only when measured need exists:
- No Redis until you measure queue performance issues
- No separate microservices until you hit scaling limits
- Start with the simplest solution that works

---

## Quick Reference

### Essential Commands

| Command | Purpose |
|---------|---------|
| `supabase start` | Start local Supabase (Docker) |
| `supabase db reset` | Reset local database |
| `uv run pytest backend/tests/ -v` | Run backend tests |
| `uv run python -m selko.api` | Start FastAPI server |

### CLI Tools

| Command | Purpose |
|---------|---------|
| `uv run python -m cli.cli_user create --email X --password Y` | Create user |
| `uv run python -m cli.cli_user list` | List users |
| `uv run python -m cli.cli_auth_gmail` | Gmail OAuth flow |
| `uv run python -m cli.cli_fetch_emails --max 10` | Fetch emails |
| `uv run python -m cli.cli_seed_tokens --from staging --to development --provider gmail` | Seed tokens |

### Environment Selection

```bash
# Default is development
uv run python -m cli.cli_fetch_emails

# Use staging
ENVIRONMENT=staging uv run python -m cli.cli_fetch_emails
```

---

## Environment Configuration

| File | Purpose | Committed |
|------|---------|-----------|
| `.env` | Local development (Docker) | No |
| `.env.test` | Staging environment | No |
| `.env.production` | Production environment | No |
| `.env.example` | Template for setup | Yes |

### Supabase Instances

| Instance | Project Ref | URL | MCP Server |
|----------|-------------|-----|------------|
| **Staging** | `lxmysergoeaegxlyfzwk` | `https://lxmysergoeaegxlyfzwk.supabase.co` | `supabase selko-staging` |
| **Production** | `khahcozfbnpykspvatrg` | `https://khahcozfbnpykspvatrg.supabase.co` | `supabase selko` |
| Local | N/A | `http://localhost:54321` | N/A (Docker) |

**Critical:** Never confuse production and staging! Always verify which MCP server you're connected to.

---

## Testing

### Test Commands

```bash
# Backend (Python/pytest)
uv run pytest backend/tests/ -v                              # All backend tests
uv run pytest backend/tests/ -m "not integration" -v         # Unit tests only
uv run pytest backend/tests/integration/ -m "development" -v # Integration tests (mocked LLM)
uv run pytest backend/tests/integration/ -m "development" --run-llm -v  # Real LLM (costs $$$)

# Frontend (vitest) - must output JSON for pre-commit hook
cd frontend && npm run test:unit -- --reporter=json --outputFile=test-results.json

# iOS (xcodebuild) - must use -resultBundlePath for pre-commit hook
xcodebuild test -project ios/iOS.xcodeproj -scheme iOS \
  -destination 'platform=iOS Simulator,name=iPhone 16' \
  -resultBundlePath ios/TestResults.xcresult

# Android (gradle)
cd android && ./gradlew test
```

### Test Markers

| Marker | Description |
|--------|-------------|
| `integration` | All integration tests (requires Supabase) |
| `development` | Tests against local Supabase + real Gmail (requires seeded tokens) |
| `staging` | Tests against staging Supabase + real Gmail + real LLM |
| `llm` | Tests requiring real LLM API calls (requires `--run-llm` flag) |

### Test Architecture

| Test Type | Database | LLM | Gmail | Cost |
|-----------|----------|-----|-------|------|
| Unit | None | Mocked | Mocked | $0 |
| Integration (default) | Local | **Mocked** | Real | $0 |
| Integration (real LLM) | Local | **Real** | Real | $$$ |
| Staging (CI only) | Cloud | Real | Real | $$$ |

**When to Use `--run-llm`:**
- Changing LLM prompts or response schemas
- Debugging LLM-specific behavior
- NOT needed for: database changes, API changes, business logic

### Development Test Setup

```bash
# One-time setup after supabase start/reset
supabase start
uv run python -m cli.cli_user create --email test@selko.local --password testpass123 --auto-confirm
uv run python -m cli.cli_seed_tokens --from staging --to development --provider gmail
```

### Token Persistence Rules

**Development tests** (local Supabase + real Gmail):
- Database is ephemeral (reset each `supabase start`)
- Tokens must be re-seeded after `supabase db reset`
- Tests are READ-ONLY for integrations (preserve seeded tokens)
- Use `pytest.fail()` not `pytest.skip()` when credentials are missing

**Staging tests** (cloud Supabase + real Gmail):
- Database is persistent across runs
- Real OAuth tokens from `cli_auth_gmail` must be preserved
- Do NOT use `cleanup_integrations` with real providers in staging

---

## Database Schema

Current tables in `supabase/migrations/`:

### `users`
User profiles linked to Supabase Auth
- `id` (uuid, PK) -> references `auth.users`
- `email`, `display_name`, timestamps
- RLS: Users can view/update/insert own profile
- Auto-created via trigger on auth.users insert

### `integrations`
OAuth tokens for external providers
- `provider`: `gmail`, `google_photos`, `google_calendar`
- `status`: `active`, `expired`, `revoked`, `error`
- `access_token`, `refresh_token`, `token_expiry`
- `scopes[]` - OAuth scopes granted
- `provider_email` - Email associated with integration
- `last_history_id` - Gmail sync cursor
- RLS: Users manage own integrations

### `emails`
Synced Gmail messages
- Gmail identifiers: `gmail_id`, `thread_id`
- Headers: `subject`, `from_email`, `from_name`, `to_emails`, `date_sent`
- `gmail_label_ids[]` - Raw labels from Gmail API
- Auto-computed flags (via trigger): `is_spam`, `is_trash`, `is_promotions`, etc.
- `content_hash` - For deduplication
- RLS: Users manage own emails

### `attachments`
Email attachment metadata
- `gmail_attachment_id`, `filename`, `mime_type`, `size_bytes`
- `storage_path` - Reference to Supabase Storage
- `content_hash` - For deduplication (SHA-256)
- RLS: Users manage own attachments

### `jobs`
Background job queue
- `job_type`: email_fetch, email_process, calendar_sync
- `status`: pending -> processing -> completed/failed/dead
- `payload`: JSONB with job-specific data
- `priority`, `attempts`, `locked_until`, `locked_by`
- See `docs/job-queue.md` for full details

### Supabase Storage Bucket: `attachments`
- Private bucket (not publicly accessible)
- 50 MB file size limit
- User-scoped paths: `{user_id}/{unique_id}_{filename}`
- RLS policies: Users can only access files in their own folder

---

## Authentication Model

All CLI operations use proper user authentication:

1. **User Management**: Uses service role key for admin operations (create/delete users)
2. **Other Operations**: Sign in with `TEST_USER_EMAIL`/`TEST_USER_PASSWORD` from `.env`
3. **RLS Enforcement**: All operations respect Row Level Security policies

No more `--user-id` flag needed - the CLI signs in as the configured test user.

---

## API Server

The Python API only handles **server-side operations** requiring secrets. Data queries go directly to Supabase.

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
| `GET /health/db` | Database connectivity check |
| `GET /integrations/gmail/auth` | Initiate Gmail OAuth flow |
| `GET /integrations/gmail/callback` | Handle OAuth callback (public) |
| `POST /emails/sync` | Sync emails from Gmail API |
| `POST /emails/{id}/process` | Extract events using LLM |
| `POST /emails/batch-process` | Process multiple emails with LLM |
| `GET /calendars` | List user's Google Calendars |
| `POST /events/{id}/sync` | Sync event to Google Calendar |

**All other data access** (listing emails, viewing events, updating status, etc.) goes **directly to Supabase** from frontends. See `docs/supabase-frontend-queries.md` for query patterns.

---

## Reference Documentation

| Document | Purpose |
|----------|---------|
| `docs/parallel-agents.md` | **REQUIRED READING: Worktree + PR workflow for AI agents** |
| `PRD_ARCH.md` | Product requirements, architecture, implementation status |
| `docs/supabase-frontend-queries.md` | Canonical query patterns for all frontends |
| `docs/api-workflow.md` | Server-side API workflow with curl examples |
| `docs/job-queue.md` | Job queue architecture |
| `docs/ci-cd.md` | CI/CD pipeline details |
| `docs/gmail-integration.md` | Gmail API architecture, push vs polling, History API |
| `docs/gemini-integration.md` | Vertex AI setup, Pydantic structured outputs |

---

## License

This is **proprietary, commercially copyrighted software** - NOT open source. Copyright (c) 2026 Toni Melisma. See LICENSE file.
