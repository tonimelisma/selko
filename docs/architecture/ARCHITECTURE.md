# Selko Architecture Overview

This document provides a high-level architectural overview of the Selko system. For detailed product requirements, see `PRD_ARCH.md`.

## System Overview

Selko is an AI-powered assistant that automates personal organization by analyzing digital inputs (emails, photos) to manage schedules, to-do lists, and digital filing systems.

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              SELKO ARCHITECTURE                              │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                              │
│  ┌─────────────┐    ┌─────────────┐    ┌─────────────┐    ┌─────────────┐   │
│  │   Gmail     │    │   Google    │    │   Web       │    │   Manual    │   │
│  │   API       │    │   Photos    │    │   Upload    │    │   Camera    │   │
│  └──────┬──────┘    └──────┬──────┘    └──────┬──────┘    └──────┬──────┘   │
│         │                  │                  │                  │          │
│         └──────────────────┴────────┬─────────┴──────────────────┘          │
│                                     ▼                                        │
│                    ┌────────────────────────────────────┐                   │
│                    │       INGESTION LAYER              │                   │
│                    │  (OAuth, MIME parsing, Storage)    │                   │
│                    └────────────────┬───────────────────┘                   │
│                                     │                                        │
│                                     ▼                                        │
│                    ┌────────────────────────────────────┐                   │
│                    │      SUPABASE (PostgreSQL)         │                   │
│                    │  ┌──────────┐  ┌──────────────┐    │                   │
│                    │  │  emails  │  │ attachments  │    │                   │
│                    │  └──────────┘  └──────────────┘    │                   │
│                    │  ┌──────────────────────────────┐  │                   │
│                    │  │    Supabase Storage (S3)     │  │                   │
│                    │  └──────────────────────────────┘  │                   │
│                    └────────────────┬───────────────────┘                   │
│                                     │                                        │
│                                     ▼                                        │
│                    ┌────────────────────────────────────┐                   │
│                    │      INTELLIGENCE ENGINE           │                   │
│                    │   (Gemini LLM - multimodal)        │                   │
│                    │  ┌─────────────────────────────┐   │                   │
│                    │  │ OCR, Entity Extraction,     │   │                   │
│                    │  │ Classification, Update      │   │                   │
│                    │  │ Detection                   │   │                   │
│                    │  └─────────────────────────────┘   │                   │
│                    └────────────────┬───────────────────┘                   │
│                                     │                                        │
│                                     ▼                                        │
│                    ┌────────────────────────────────────┐                   │
│                    │      REVIEW INTERFACE              │                   │
│                    │   (Human-in-the-loop)              │                   │
│                    │  ┌─────────────────────────────┐   │                   │
│                    │  │ Source ←→ Extracted Data    │   │                   │
│                    │  │ Approve / Edit / Reject     │   │                   │
│                    │  └─────────────────────────────┘   │                   │
│                    └────────────────┬───────────────────┘                   │
│                                     │                                        │
│         ┌───────────────────────────┼───────────────────────────┐           │
│         ▼                           ▼                           ▼           │
│  ┌─────────────┐           ┌─────────────┐            ┌─────────────┐       │
│  │   Google    │           │   Cloud     │            │    Task     │       │
│  │   Calendar  │           │   Storage   │            │   Manager   │       │
│  └─────────────┘           └─────────────┘            └─────────────┘       │
│                                                                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Development Phases

### Phase 0: Proof of Concept (Current)
- **Status:** COMPLETE
- **Goal:** Validate core data ingestion and storage
- **Components:** CLI tools, Supabase (PostgreSQL + Storage), Gmail API
- **Features implemented:**
  - Gmail OAuth authentication
  - Email fetching and parsing
  - Attachment download and storage
  - Content deduplication (SHA-256)
  - RLS-enforced multi-tenancy

### Phase 1: MVP (Web-First Cloud Processing)
- **Status:** PLANNED
- **Goal:** Complete end-to-end journey: Email → LLM → Calendar
- **Components:** FastAPI, Gemini LLM, Google Calendar API
- **Order of implementation:**
  1. LLM integration (Gemini via Vertex AI)
  2. Email → LLM analysis pipeline
  3. Calendar sync (write events)
  4. Review interface (web dashboard)
  5. Undo/Redo functionality
  6. Automation rules

### Phase 2: Extended Inputs
- **Status:** FUTURE
- **Goal:** Add more input sources after Email→Calendar works
- **Features:**
  - Google Photos sync
  - Web upload interface
  - Direct camera capture (mobile)

### Phase 3: Mobile Companion
- **Status:** FUTURE
- **Goal:** Native mobile app with on-device processing
- **Features:**
  - iOS/Android apps
  - Local LLM inference
  - Push notifications

## Key Architectural Principles

### 1. End-to-End First
Complete full journeys before expanding scope:
- Do NOT add Google Photos until Email→Calendar works end-to-end
- Do NOT add Task Management until Calendar integration is complete
- Each input→output path must be fully functional before adding more

### 2. LLM-Centric Intelligence
All intelligence features use the same multimodal LLM (Gemini):
- OCR & text extraction → LLM reads images/PDFs directly
- Entity extraction → LLM extracts dates, times, locations
- Document classification → LLM categorizes content
- No separate OCR service needed - the LLM is multimodal

### 3. Human-in-the-Loop
Every automated action goes through review:
- Side-by-side view of source vs. extracted data
- User can approve, edit, or reject
- Automation rules can bypass review for trusted sources
- Undo/Redo for all actions

### 4. Simplified Stack (YAGNI)
Add complexity only when measured need exists:
- POC: CLI + Supabase (2 components, $0/mo)
- MVP: Add FastAPI (still 2 components)
- Scale: Add Redis only when PostgreSQL queue insufficient

## Data Flow

```
Input Sources          Database              Processing            Outputs
─────────────          ────────              ──────────            ───────
Gmail API ──────┐
                │      ┌─────────────┐       ┌────────────┐       ┌──────────┐
Google Photos ──┼──►   │   emails    │ ──►   │   LLM      │ ──►   │ Calendar │
                │      │ attachments │       │  (Gemini)  │       │ Storage  │
Web Upload ─────┘      │   storage   │       └────────────┘       │ Tasks    │
                       └─────────────┘              │             └──────────┘
                              ▲                     │
                              │                     ▼
                              │            ┌────────────────┐
                              └────────────│ Review Queue   │
                                           │ (User Approval)│
                                           └────────────────┘
```

## Security Model

### Row-Level Security (RLS)
All database access is controlled by Supabase RLS policies:
- Users can only see their own data
- Service role key for admin operations only
- User credentials (JWT) for all normal operations

### OAuth 2.0
External integrations use OAuth with minimal scopes:
- Gmail: `gmail.readonly` (read-only access)
- Calendar: `calendar.events` (event management)
- Photos: `photoslibrary.readonly` (read-only access)

### Storage Isolation
Supabase Storage uses user-scoped paths:
- Pattern: `{user_id}/{unique_id}_{filename}`
- RLS policies enforce folder-level access
- Users cannot access other users' files

## Technology Stack

| Layer | Component | Purpose |
|-------|-----------|---------|
| **Data** | Supabase PostgreSQL | Relational data, RLS |
| **Storage** | Supabase Storage | Attachment files (S3-compatible) |
| **API** | FastAPI (planned) | REST API, async processing |
| **AI** | Gemini (Vertex AI) | Multimodal LLM |
| **Auth** | Supabase Auth | User management, JWT |
| **Hosting** | Fly.io (planned) | Application deployment |

## Related Documents

- [PRD_ARCH.md](../../PRD_ARCH.md) - Full product requirements and architecture spec
- [CLAUDE.md](../../CLAUDE.md) - Developer guidelines and database schema
- [Backend Framework Evaluation](../../BACKEND_FRAMEWORK_EVALUATION.md) - Framework decision rationale
- [Simplified Stack](../../SIMPLIFIED_STACK.md) - Why we avoid complexity
- [Gmail Integration Guide](../guides/gmail-integration.md) - Gmail API technical details
- [Gemini Integration Guide](../guides/gemini-integration.md) - LLM integration patterns
