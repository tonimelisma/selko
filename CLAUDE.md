# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Selko** is an AI-powered assistant that automates personal organization by analyzing digital inputs (emails, photos) to manage schedules, to-do lists, and digital filing systems. The system acts as a "Human-in-the-loop" filter, ensuring accuracy before committing changes to permanent records.

See `PRD_ARCH.md` for complete product requirements and technical architecture specification.

## Development Environment

### Python Environment Management
- **Package Manager**: Use `uv` for all Python package management and environment operations
- **File Deletion**: Use `trash` command instead of `rm` for safer file deletion

### Project Phase
This is a **Proof of Concept (POC)** phase using local Python scripts to validate core functionality before building the full cloud-based web application.

### Environment Configuration

| File | Purpose | Committed |
|------|---------|-----------|
| `.env` | Local development (Docker) | No |
| `.env.test` | Staging environment | No |
| `.env.production` | Production environment | No |
| `.env.example` | Template for setup | Yes |

### Supabase Setup

**Environments:**
| Environment | Project Ref | URL |
|-------------|-------------|-----|
| Local | N/A | `http://localhost:54321` |
| Staging | `lxmysergoeaegxlyfzwk` | `https://lxmysergoeaegxlyfzwk.supabase.co` |
| Production | `khahcozfbnpykspvatrg` | `https://khahcozfbnpykspvatrg.supabase.co` |

**CLI Commands:**
```bash
# Local development (requires Docker)
supabase start
supabase db reset

# Link to staging
supabase link --project-ref lxmysergoeaegxlyfzwk
supabase db push

# Link to production
supabase link --project-ref khahcozfbnpykspvatrg
supabase db push

# View migration status
supabase migration list
```

## Architecture Overview

### Phased Approach
1. **Phase 1 (Current POC)**: Local Python scripts to prove AI processing capabilities
2. **Phase 2 (MVP)**: Web-First Cloud Processing with responsive web dashboard
3. **Phase 3**: Mobile companion app with local inference

### Core System Components (Target Architecture)

**Data Flow**: Ingestion → Analysis → Review → Execution

1. **Ingestion Layer**
   - Cloud Photo Library sync
   - Email inbox monitoring with attachment extraction
   - Manual web upload interface

2. **Intelligence Engine**
   - OCR & text extraction (handwriting recognition)
   - Entity extraction (dates, times, locations, vendors, amounts)
   - Document classification (receipts, invitations, drawings, etc.)
   - Smart idempotency & update detection
   - User-defined automation rules

3. **Review Interface**
   - Side-by-side view (source asset vs. extracted data)
   - Edit, approve, or reject functionality
   - Undo/Redo with compensating transactions

4. **Output Layer**
   - Calendar sync (create/update events)
   - Cloud file storage (categorized uploads)
   - Task management integration

### Database Schema (POC)

Current tables in `supabase/migrations/`:

**`users`** - User profiles linked to Supabase Auth
- `id` (uuid, PK) → references `auth.users`
- `email`, `display_name`, timestamps
- RLS: Users can view/update own profile

**`integrations`** - OAuth tokens for external providers
- `provider`: `gmail`, `google_photos`, `google_calendar`
- `status`: `active`, `expired`, `revoked`, `error`
- `access_token`, `refresh_token`, `token_expiry`
- `last_history_id` - Gmail sync cursor
- RLS: Users manage own integrations

**`emails`** - Synced Gmail messages
- Gmail identifiers: `gmail_id`, `thread_id`
- Headers: `subject`, `from_email`, `from_name`, `to_emails`, `date_sent`
- `gmail_label_ids[]` - Raw labels from Gmail API
- Auto-computed flags (via trigger): `is_spam`, `is_trash`, `is_promotions`, `is_social`, `is_updates`, `is_forums`, `is_primary`, `is_important`, `is_starred`, `is_unread`
- `content_hash` - For deduplication
- RLS: Users manage own emails

**`attachments`** - Email attachment metadata
- `gmail_attachment_id`, `filename`, `mime_type`, `size_bytes`
- `storage_path` - Reference to Supabase Storage
- `content_hash` - For deduplication
- RLS: Users manage own attachments

### Future Data Model (MVP)

- **assets**: Raw input units (emails, photos, PDFs) with content hashing for deduplication
- **inferences**: AI-extracted structured data from assets (1 asset → N inferences)
  - States: PENDING_REVIEW, APPROVED, REJECTED, AUTO_EXECUTED
- **automation_rules**: User-defined logic to bypass manual review
- **action_history**: Ledger for undo/redo with state snapshots

### Critical Business Logic

**Update vs. Create Detection**: System must semantically detect if a new asset is an update to existing data (e.g., "Time Changed" email) and merge values rather than creating duplicates.

**Compensating Transactions**: Every action (CREATE/UPDATE/DELETE) must be reversible by storing previous_state and external resource IDs.

## License

This is **proprietary, commercially copyrighted software** - NOT open source. Copyright (c) 2026 Toni Melisma. See LICENSE file.
