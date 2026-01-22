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

### Key Data Model Concepts

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
