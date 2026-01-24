# Render Migration Plan

This document outlines the steps to migrate the Selko backend to a "Monolith" architecture on Render, replacing the previous Fly.io strategy.

## 1. Architecture Overview

We are moving to an **Async Monolith** architecture:
- **Framework:** FastAPI (Python) serving both API and background tasks.
- **Hosting:** Render Web Service (Starter Plan, $7/mo).
- **Scheduling:** `APScheduler` running within the main application process.
- **Workers:** `FastAPI BackgroundTasks` for immediate offloading; `APScheduler` for periodic jobs.
- **Database:** Supabase (PostgreSQL + Auth + Storage).

## 2. Codebase Refactoring

### 2.1 Dependencies
**File:** `backend/pyproject.toml`
- Add `apscheduler` to `dependencies`.

### 2.2 Service Refactoring (Support for System Tasks)
To support the cron job (which runs without a user session), we must refactor services to allow explicit user targeting.

**File:** `backend/selko/services/emails.py`
- Modify `save_emails`: Accept an optional `user_id` argument.
  - If `user_id` is provided, use it.
  - If `user_id` is `None`, fall back to `get_current_user_id(client)` (preserve existing behavior for API).

**File:** `backend/selko/services/integrations.py`
- Create `get_all_active_integrations(client: Client, provider: str) -> list[dict]`:
  - New function for the system scheduler.
  - Uses the provided `client` (which will be initialized with Service Role Key) to fetch all active integrations.
  - Returns raw list of integration rows (including `user_id`, `access_token`, `refresh_token`).
- Update `update_oauth_credentials`:
  - Accept optional `user_id`.
  - Logic: If `user_id` provided, use it; else derive from `client`.

### 2.3 New Polling Logic
**File:** `backend/selko/tasks.py` (New File)
- Implement `poll_gmail_integrations()`:
  - Initialize Supabase Client with `SUPABASE_SERVICE_ROLE_KEY` (bypassing RLS).
  - Call `get_all_active_integrations`.
  - Loop through each integration:
    - Construct `Credentials`.
    - Refresh token if expired (and update DB using `update_oauth_credentials`).
    - Call `fetch_messages`.
    - Call `save_emails` (passing `user_id`).
    - Handle errors per user (log but don't crash the loop).

### 2.4 Application Entry Point
**File:** `backend/selko/api/app.py`
- Import `AsyncIOScheduler` from `apscheduler.schedulers.asyncio`.
- Import `poll_gmail_integrations` from `selko.tasks`.
- In `create_app`:
  - Initialize `scheduler = AsyncIOScheduler()`.
  - Add job: `scheduler.add_job(poll_gmail_integrations, "interval", minutes=5)`.
  - Start scheduler: `scheduler.start()` in the startup event (or lifespan context).

### 2.5 Configuration
**File:** `backend/selko/config.py`
- Ensure `SUPABASE_SERVICE_ROLE_KEY` is loaded (it already is).

## 3. Documentation & Deployment

### 3.1 Documentation Cleanup
- Remove outdated evaluation docs:
  - `BACKEND_FRAMEWORK_EVALUATION.md`
  - `HOSTING_EVALUATION.md`
  - `SIMPLIFIED_STACK.md`
- Update `README.md`:
  - Remove Fly.io references.
  - Add "Deployment on Render" section.

### 3.2 Deployment Config
- Create `render.yaml` (optional, but good for IaC) or document the manual setup in `README.md`.
- **Start Command:** `uvicorn selko.api.app:app --host 0.0.0.0 --port $PORT`
- **Build Command:** `pip install uv && uv pip install -r pyproject.toml` (or standard pip install).

## 4. Verification

1.  **Unit Tests:** Ensure refactored `save_emails` still passes existing tests.
2.  **Manual Test:** Run `poll_gmail_integrations()` locally (via a temporary script) to verify it can fetch emails for a test user without a session.
