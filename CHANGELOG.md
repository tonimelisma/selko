# Changelog

All notable changes to this project are documented in this file.

## 2026-01-21

### 564d62b - Update documentation with POC multi-environment support

**Files changed:**
- `CLAUDE.md` - Added POC Scripts section with module descriptions and CLI usage examples
- `README.md` - Updated Local Development section with new commands, added Multi-Environment Support section, updated Project Structure to include new files

**Reason:** Document the new multi-environment POC configuration system for developers.

---

### ed0a44e - Support both SUPABASE_ANON_KEY and SUPABASE_PUBLISHABLE_API_KEY in config

**Files changed:**
- `poc/config.py` - Added fallback to check `SUPABASE_PUBLISHABLE_API_KEY` if `SUPABASE_ANON_KEY` is not set

**Reason:** Allow using either the legacy JWT-based anon key or the newer publishable API key format for Supabase client authentication. Staging environment had only the publishable key configured.

---

### ffdc3ca - Add auto-commit workflow instruction to CLAUDE.md

**Files changed:**
- `CLAUDE.md` - Added Workflow section with auto-commit instruction

**Reason:** Ensure Claude Code automatically commits and pushes after completing each stage of work.

---

### 9a41f34 - Add environment-aware config and Supabase integration to POC

**Files changed:**
- `poc/__init__.py` - Created package marker
- `poc/config.py` - Created centralized configuration module with environment detection (development/staging/production)
- `poc/auth_gmail.py` - Updated to use config module, added `--env` CLI argument
- `poc/fetch_emails.py` - Updated to use config module, added Supabase integration for storing emails, added `--env` and `--user-id` CLI arguments
- `pyproject.toml` - Added supabase dependency
- `uv.lock` - Updated with supabase and its dependencies

**Reason:** Implement 3-environment strategy (development/staging/production) for POC scripts, enabling testing against different Supabase instances.

---

### 1649551 - Add project documentation

**Files changed:**
- `README.md` - Created with project overview, setup instructions, environment variables, and project structure
- `CLAUDE.md` - Added Supabase environment configuration, CLI commands, and database schema documentation
- `.env.example` - Expanded with comprehensive template including all Supabase and Google OAuth variables

**Reason:** Provide comprehensive documentation for developers setting up and working with the project.

---

### ddf8fa6 - Fix uuid generation to use built-in gen_random_uuid()

**Files changed:**
- `supabase/migrations/20260121000001_create_users.sql` - Removed uuid-ossp extension dependency
- `supabase/migrations/20260121000002_create_integrations.sql` - Changed `uuid_generate_v4()` to `gen_random_uuid()`
- `supabase/migrations/20260121000003_create_emails.sql` - Changed `uuid_generate_v4()` to `gen_random_uuid()`
- `supabase/migrations/20260121000004_create_attachments.sql` - Changed `uuid_generate_v4()` to `gen_random_uuid()`

**Reason:** Replace `uuid_generate_v4()` with `gen_random_uuid()` which is built into PostgreSQL 13+ and doesn't require the uuid-ossp extension. Fixes migration failures on fresh Supabase projects where the extension schema isn't in the search_path.

---

### 48d34aa - Fix function search_path security warning

**Files changed:**
- `supabase/migrations/20260121000005_fix_function_search_path.sql` - Created migration to set immutable search_path on `parse_gmail_labels` trigger function

**Reason:** Set immutable search_path on trigger function to prevent search_path injection attacks. Addresses Supabase security advisor warning.

---

### 0b52051 - Add Supabase setup with Gmail schema migrations

**Files changed:**
- `.env.example` - Created with basic Supabase configuration template
- `.gitignore` - Added entries for environment files and Supabase local data
- `pyproject.toml` - Added python-dotenv dependency
- `supabase/.gitignore` - Created for Supabase CLI local files
- `supabase/config.toml` - Created Supabase CLI configuration
- `supabase/migrations/20260121000001_create_users.sql` - Created users table with RLS
- `supabase/migrations/20260121000002_create_integrations.sql` - Created integrations table for OAuth tokens
- `supabase/migrations/20260121000003_create_emails.sql` - Created emails table with Gmail label parsing trigger
- `supabase/migrations/20260121000004_create_attachments.sql` - Created attachments table
- `uv.lock` - Updated with python-dotenv

**Reason:** Initialize Supabase CLI project and create database schema for Gmail integration POC. Establishes foundation for storing synced emails with proper RLS policies.

---

### f2d6a0f - Add Gmail API integration POC with OAuth authentication

**Files changed:**
- `.gitignore` - Created with Python, credentials, and IDE ignores
- `.python-version` - Set Python version to 3.10
- `CLAUDE.md` - Created with project overview and development instructions
- `LICENSE` - Created proprietary license file
- `PRD_ARCH.md` - Created product requirements and architecture specification
- `poc/auth_gmail.py` - Created Gmail OAuth authentication script
- `poc/fetch_emails.py` - Created email fetching script
- `pyproject.toml` - Created with project dependencies (google-auth, google-api-python-client)
- `uv.lock` - Created with locked dependencies

**Reason:** Initial project setup with Gmail API integration POC for validating email ingestion functionality.
