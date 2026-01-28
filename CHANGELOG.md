# Changelog

All notable changes to this project are documented in this file.

## 2026-01-27 (22)

### Reset Stale Jobs on Startup

**Problem:** When the API server crashes or is killed while jobs are in-progress, those jobs remain "locked" until their lock expires. This delays reprocessing by the lock timeout duration.

**Solution:** On startup, immediately call the existing `unlock_expired_*` functions to recover any stale jobs from a previous instance crash.

**Why It's Safe:**
- All job types are idempotent (upsert-based, no duplicates)
- Unlock functions already exist and are tested
- Only resets jobs where `locked_until < now()` (truly stale)

**Files Changed:**
- `backend/selko/api/app.py` - Added stale job recovery after worker pool starts

**Log Output:**
```
INFO: Recovered stale jobs on startup: 2 emails, 1 events, 0 tasks
```
(Only logs if any jobs were recovered)

---

## 2026-01-27 (21)

### Block Interactive Commands in Claude Code

**Problem:** `gh pr checks --watch` is an interactive command that Claude Code cannot parse properly. The output stream causes the agent to hang or produce unparsable results.

**Solution:**
- Created PreToolUse hook to block `gh pr checks --watch` commands
- Updated CLAUDE.md to use polling approach instead: `while ! gh pr checks; do sleep 30; done`
- Added "Blocked Commands" section documenting blocked commands and alternatives

**Files Changed:**
- `.claude/hooks/block-interactive-commands.sh` - New hook script
- `.claude/settings.json` - Added Bash hook matcher
- `CLAUDE.md` - Updated commands and added blocked commands section

---

## 2026-01-27 (20)

### Replace Job Queue with Status-Based Workers

**Architectural Change:** Replaced the `jobs` table with status-based workers that poll data tables directly. The data tables ARE the queue.

**Why:**
- Single source of truth (no job-data synchronization bugs)
- Simpler debugging (query data tables directly to see pending work)
- Natural idempotency (data state is always consistent)

**Before:** `jobs` table → worker claims job → fetches data → updates both job and data
**After:** Worker claims data via status → processes → updates data

**Database Changes:**
- Added claiming columns to `emails`: `locked_until`, `locked_by`, `attempts`, `max_attempts`
- Added sync tracking columns to `events`: `locked_until`, `locked_by`, `sync_attempts`, `max_sync_attempts`, `sync_error`
- Added `syncing` status to events for in-progress calendar sync
- Created atomic claiming RPC functions: `claim_unprocessed_email()`, `claim_approved_event()`, `unlock_expired_email_locks()`, `unlock_expired_event_locks()`
- Dropped `jobs` table entirely
- Created `scheduled_tasks` table for periodic tasks only (email_fetch)

**Service Changes:**
- Deleted `backend/selko/services/jobs.py`
- Created `backend/selko/services/scheduled_tasks.py` for periodic tasks
- Added claiming functions to `emails.py`: `claim_pending_email()`, `complete_email_processing()`, `fail_email_processing()`
- Added claiming functions to `events.py`: `claim_approved_event_for_sync()`, `complete_event_sync()`, `fail_event_sync()`

**Worker Changes:**
- `pool.py`: Polls three sources: scheduled_tasks, pending emails, approved events
- `email_process.py`: Receives full email record (not job payload)
- `calendar_sync.py`: Receives full event record (not job payload)
- `email_fetch.py`: Removed job enqueueing (emails auto-picked up by status)

**Data Flow:**
```
Cron (5 min) -> scheduled_tasks -> emails (status=pending)
                                   -> Worker claims -> LLM -> events (status=pending_review)
User approves -> status=approved -> Worker claims -> Calendar API -> status=synced
```

---

## 2026-01-27 (19)

### CI Fixes and Documentation Updates

**Bug Fixes:**
- Fixed pre-commit hook to work correctly in git worktrees
  - Changed PROJECT_ROOT detection to use `git rev-parse --show-toplevel`
  - Fixed pytest cache detection to check `nodeids` file (created on every run) instead of only `lastfailed` (only created when tests fail)
- Added missing INSERT RLS policy for `calendar_sync_log` table
  - Sync operations can now write audit log entries
- Added `pytest-asyncio` dependency and `asyncio_mode = "auto"` config
  - Async worker tests now run correctly

**Documentation:**
- Updated workflow documentation to use manual merge (auto-merge requires GitHub Pro)
  - Use `gh pr checks --watch && gh pr merge --squash` instead of `gh pr merge --auto --squash`
  - Added explicit cleanup steps for AI agents after PR merge
- Removed PLAN5.md (auto-merge issue resolved by documentation update)

---

## 2026-01-27 (18)

### Opt-in Background Processing

**Change:** Background processing (worker pool + APScheduler) is now OFF by default and requires explicit opt-in.

**Why:** Allows running the API without background workers for development, testing, or lightweight deployments where automatic email fetching isn't needed.

**Configuration:**
- New environment variable: `ENABLE_BACKGROUND_PROCESSING`
- Default: `false` (disabled)
- Set to `true` to enable automatic email fetching and job processing

**Files Changed:**
- `backend/selko/config.py` - Added `enable_background_processing` config field
- `backend/selko/api/app.py` - Conditional startup of workers and scheduler
- `.env.example` - Documented the new variable
- `.env.production` - Enabled for production deployments

**Usage:**
```bash
# Development (background processing disabled by default)
uv run python -m selko.api

# Production or when you want background workers
ENABLE_BACKGROUND_PROCESSING=true uv run python -m selko.api
```

**Note:** CLI tools (`cli_fetch_emails`, `cli_process_emails`) continue to work regardless of this setting since they don't depend on background workers.

---

## 2026-01-27 (17)

### LLM Evaluation Framework Improvements

**New Features:**
- `--dry-run` flag for fixture validation without LLM calls
  - Validates JSON structure (required fields: `input`, `expected`, `events_found`)
  - Checks that referenced attachments exist
  - Reports validation errors for invalid fixtures
- Thread scenario evaluation (`--threads`)
  - Processes multi-email sequences in order
  - Tracks event state across emails in a thread
  - Compares final state against expected outcome
- Configurable model via `SELKO_EVAL_MODEL` environment variable
  - Default remains `gemini-3-flash-preview`
  - Override with e.g. `SELKO_EVAL_MODEL=gemini-2.0-flash`

**Usage Examples:**
```bash
# Validate all fixtures without LLM calls
uv run python -m backend.tests.eval.run_eval --all --dry-run

# Run thread scenario evaluation
uv run python -m backend.tests.eval.run_eval --threads --dry-run

# Use different model
SELKO_EVAL_MODEL=gemini-2.0-flash uv run python -m backend.tests.eval.run_eval --all
```

---

## 2026-01-27 (16)

### Email-to-Calendar Manual CLI Walkthrough

**Purpose:** Create CLI tool for processing emails into saved events and comprehensive walkthrough documentation for the email-to-calendar flow.

**New CLI Tool:** `cli_process_emails`
- Process emails through the LLM to extract calendar events
- `--recent N`: Process N most recent unprocessed emails
- `--email-id ID`: Process a specific email by ID
- `--all`: Process all unprocessed emails
- Events are created with "new" status, awaiting user approval

**New Documentation:** `docs/manual-email-to-calendar-walkthrough.md`
- Step-by-step guide from authenticated user to synced calendar event
- Covers all CLI commands in the email→event→calendar pipeline
- Includes troubleshooting for common issues (quota limits, OAuth errors)

**Commands in order:**
```bash
# 1. Auth & fetch
uv run python -m cli.cli_fetch_emails --max 10

# 2. Process emails to events
uv run python -m cli.cli_process_emails --recent 5

# 3. Review extracted events
uv run python -m cli.cli_events new

# 4. Approve events
uv run python -m cli.cli_events approve <event_id>

# 5. Sync to Google Calendar
uv run python -m cli.cli_events sync <event_id>
```

---

## 2026-01-27 (15)

### Test Coverage Improvements

**New test files:**
- `test_integration_events.py` - Event processing, sender rules, event sources, undo/redo
- `test_integration_calendars.py` - Calendar settings, sync to Google Calendar, cancel events
- `test_integration_gemini.py` - LLM extraction tests (skipped by default due to API costs)

**Key coverage:**
- Event lifecycle: create → approve → sync → cancel
- Sender rules: exact email match, domain wildcards, rule priority
- Event sources: email attribution, multi-source events, undo/redo of sources
- Calendar sync: create/update Google events, audit logging, error handling
- Gemini integration: birthday/appointment extraction, newsletter filtering

**Running LLM tests:**
```bash
# Skip LLM tests (default)
uv run pytest backend/tests/ -v

# Include LLM tests (costs ~$0.01/test)
uv run pytest backend/tests/ -v --run-llm
```

---

## 2026-01-26 (14)

### Job Queue System

**New Tables:**
- `jobs` - Persistent job queue with priorities, retries, scheduled execution
- `usage_quotas` - Track daily usage per user for rate limiting
- `global_limits` - System-wide default limits per resource type

**Job Features:**
- Priority-based claiming (lower number = higher priority)
- Automatic retry with exponential backoff (configurable max attempts)
- Job locking with `FOR UPDATE SKIP LOCKED` to prevent double-processing
- Scheduled jobs via `scheduled_for` timestamp
- Dead letter queue for failed jobs (status: 'dead')

**Rate Limiting:**
- Daily quotas per user per resource type (emails, LLM calls)
- RPC function `check_and_increment_quota` for atomic check-and-increment
- API middleware returns `X-RateLimit-*` headers
- Returns 429 when quota exceeded

**Worker System:**
- Configurable worker pool size via `WORKER_POOL_SIZE`
- APScheduler for periodic tasks (email fetch, job unlock, cleanup)
- Graceful shutdown on SIGINT/SIGTERM

**CLI Updates:**
- `cli_events sync` now enqueues calendar sync jobs
- Jobs processed by background workers

---

## 2026-01-25 (13)

### Complete Event Flow + Calendar Integration

**Event System:**
- Created `events` table with full lifecycle (new → approved → synced/rejected)
- Implemented undo/redo via snapshot storage in `event_sources`
- Event attribution tracks which emails contributed to each event
- Sender rules for auto-trust/auto-ignore patterns

**Calendar Integration:**
- Created `user_calendar_settings` table for default calendar preferences
- Google Calendar sync creates/updates/deletes events
- Audit logging via `calendar_sync_log` table
- Cancel operation prefixes title with "[CANCELLED]"

**CLI Tools:**
- `cli_events` - List, approve, reject, undo events
- `cli_events sync` - Sync approved events to Google Calendar

---

## 2026-01-24 (12)

### Email Processing Status + Gemini Integration

**Email Processing:**
- Added `processing_status` column to emails table
- Status flow: unprocessed → processing → processed/failed
- Trigger prevents re-processing already processed emails

**Gemini Service:**
- Created `selko/services/gemini.py` for LLM event extraction
- Structured output using Pydantic models
- Configurable thinking level (none/low/medium/high)
- Support for email attachments (images, PDFs)

**CLI Tools:**
- `cli_process_emails` - Extract events from emails via LLM

---

## Earlier Entries

See git history for changes prior to 2026-01-24.
