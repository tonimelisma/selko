# Implementation Plan: Email Attachment Storage (Simplified)

**Date:** 2026-01-22 (Updated)
**Branch:** `claude/plan-attachment-storage-lm7AY`
**PRD Reference:** Part 2, Section 1.2 (Ingestion Service - Attachment Parsing) & Section 1.3 (Object/Blob Storage)

## Overview

Implement end-to-end attachment storage for Gmail emails, including download from Gmail API, content deduplication, upload to Supabase Storage, and metadata tracking in the database.

**Architecture:** Simple Python services (no Redis, no ARQ) - aligns with simplified stack (FastAPI + Supabase only)

## Current State Analysis

### What Exists
- ✅ Database schema: `attachments` table with RLS policies (`20260121000004_create_attachments.sql`)
- ✅ Email parsing: `parse_gmail_message()` detects `has_attachments` boolean
- ✅ Supabase Storage: Enabled with 50MiB limit, S3 protocol support
- ✅ Authentication: User auth working with RLS enforcement
- ✅ Testing framework: pytest with fixtures in `backend/tests/`

### What's Missing
- ❌ No Storage buckets configured
- ❌ No attachment download logic from Gmail API
- ❌ No attachment service module
- ❌ No content hashing/deduplication
- ❌ No CLI integration for attachment processing
- ❌ No tests for attachment functionality

## PRD Requirements Mapping

| Requirement | Description | Priority |
|-------------|-------------|----------|
| **FR-A.2** | Email Inbox - Must extract attachments | **P0** |
| **FR-B.4** | Smart Idempotency - Detect duplicates via content hashing | **P0** |
| **Arch 1.2** | Attachment Parsing - Recursively parse MIME types for PDFs/Images | Required |
| **Arch 1.3** | Object/Blob Storage - Scalable, encrypted at rest | Required |
| **Arch 2.2** | Content hashes for deduplication | Required |

## Implementation Plan

### Phase 1: Storage Infrastructure (Foundation)

**Goal:** Configure Supabase Storage buckets and policies

#### 1.1 Create Storage Migration
- **File:** `supabase/migrations/20260122000004_create_storage_buckets.sql`
- **Actions:**
  - Create `attachments` bucket (private)
  - Set file size limit: 50 MB
  - Configure allowed MIME types: `image/*`, `application/pdf`, `application/*`, `text/*`
  - Enable RLS policies:
    - Users can upload to `{user_id}/*` paths only
    - Users can read/delete their own attachments
  - Add bucket policies for encryption at rest (if configurable)

#### 1.2 Update Configuration
- **File:** `backend/selko/config.py`
- **Actions:**
  - Add `storage_bucket_attachments: str` field to `Config` dataclass
  - Default value: `"attachments"`
  - Environment variable: `STORAGE_BUCKET_ATTACHMENTS` (optional override)

#### 1.3 Environment Files
- **Files:** `.env.example`, local `.env`
- **Actions:**
  - Document `STORAGE_BUCKET_ATTACHMENTS=attachments` (optional)
  - No changes needed for staging/production (use defaults)

**Validation:**
- Run `supabase db reset` locally
- Verify bucket exists in Supabase Studio (http://127.0.0.1:54323)
- Test manual file upload via Studio UI

---

### Phase 2: Attachment Service Module (Core Logic)

**Goal:** Create reusable attachment handling service

#### 2.1 Create Attachment Service
- **File:** `backend/selko/services/attachments.py`
- **Functions:**

```python
def calculate_content_hash(data: bytes) -> str:
    """Calculate SHA-256 hash of attachment content for deduplication."""
    # Use hashlib.sha256(data).hexdigest()

def check_duplicate_attachment(
    client: Client,
    content_hash: str,
) -> Optional[dict]:
    """Check if attachment with same hash already exists for user.

    Returns existing attachment record if found, None otherwise.
    """
    # Query attachments table by content_hash and user_id

def download_gmail_attachment(
    service,
    message_id: str,
    attachment_id: str,
) -> bytes:
    """Download attachment data from Gmail API.

    Args:
        service: Gmail API service
        message_id: Gmail message ID
        attachment_id: Gmail attachment ID

    Returns:
        Raw attachment bytes (decoded from base64url)

    Raises:
        AttachmentError: If download fails or rate limited
    """
    # Call service.users().messages().attachments().get()
    # Handle rate limiting with exponential backoff (like fetch_messages)
    # Decode base64url data
    # Return bytes

def upload_to_storage(
    client: Client,
    user_id: str,
    filename: str,
    data: bytes,
    mime_type: str,
    bucket: str = "attachments",
) -> str:
    """Upload attachment to Supabase Storage.

    Args:
        client: Authenticated Supabase client
        user_id: User UUID for path namespacing
        filename: Original filename
        data: File bytes
        mime_type: MIME type
        bucket: Storage bucket name

    Returns:
        Storage path (e.g., "{user_id}/{uuid}_{filename}")

    Raises:
        AttachmentError: If upload fails
    """
    # Generate unique filename: f"{user_id}/{uuid4()}_{filename}"
    # Use client.storage.from_(bucket).upload()
    # Return storage path

def save_attachment_metadata(
    client: Client,
    email_id: str,
    gmail_attachment_id: str,
    filename: str,
    mime_type: str,
    size_bytes: int,
    storage_path: str,
    content_hash: str,
) -> dict:
    """Save attachment metadata to database.

    Args:
        client: Authenticated Supabase client
        email_id: UUID of parent email record
        gmail_attachment_id: Gmail's attachment ID
        filename: Original filename
        mime_type: MIME type
        size_bytes: File size in bytes
        storage_path: Path in Supabase Storage
        content_hash: SHA-256 hash for deduplication

    Returns:
        Created attachment record

    Raises:
        AttachmentError: If database insert fails
    """
    # user_id auto-determined from auth session (like emails.py)
    # Insert into attachments table
    # Return created record

def process_attachment(
    client: Client,
    gmail_service,
    email_id: str,
    message_id: str,
    attachment_part: dict,
    config: Config,
) -> Optional[dict]:
    """Process a single email attachment end-to-end.

    This is the main orchestration function that:
    1. Downloads attachment from Gmail
    2. Calculates content hash
    3. Checks for duplicates
    4. Uploads to storage (if new)
    5. Saves metadata to database

    Args:
        client: Authenticated Supabase client
        gmail_service: Gmail API service
        email_id: UUID of parent email in database
        message_id: Gmail message ID
        attachment_part: Gmail API attachment part dict
        config: Application config

    Returns:
        Attachment record (new or existing), or None if skipped

    Raises:
        AttachmentError: If processing fails
    """
    # Extract metadata from attachment_part
    # Download data
    # Calculate hash
    # Check duplicates
    # If duplicate: log skip, return existing record
    # If new: upload to storage, save metadata
    # Return record

class AttachmentError(Exception):
    """Raised when attachment operations fail."""
```

#### 2.2 Error Handling
- Custom exception: `AttachmentError`
- Retry logic for Gmail API rate limits (429 errors)
- Graceful handling of:
  - Oversized attachments (>50MB) - log warning, skip
  - Network failures - retry with backoff
  - Storage quota exceeded - raise clear error

#### 2.3 Logging
- Use structured logging (like `emails.py`)
- Log levels:
  - DEBUG: Hash calculations, duplicate checks
  - INFO: Successful uploads, duplicate skips
  - WARNING: Skipped oversized files, rate limits
  - ERROR: Failed downloads, storage errors

**Validation:**
- Unit tests for each function (see Phase 5)
- Manual testing with sample attachments

---

### Phase 3: Gmail Service Extension

**Goal:** Add attachment extraction to email fetching

#### 3.1 Extend Gmail Service
- **File:** `backend/selko/services/gmail.py`
- **New Function:**

```python
def extract_attachments(email: dict) -> list[dict]:
    """Extract attachment metadata from Gmail message.

    Recursively parses MIME multipart structure to find all attachments.

    Args:
        email: Full Gmail message object from API

    Returns:
        List of attachment part dicts with keys:
        - attachment_id: Gmail attachment ID
        - filename: Original filename
        - mime_type: MIME type
        - size_bytes: Size in bytes

    Note:
        Does NOT download attachment data - only extracts metadata.
    """
    # Recursively walk email.payload.parts
    # Check for parts with filename or attachmentId
    # Extract metadata (don't download data yet)
    # Return list of attachment dicts
```

#### 3.2 Update Email Parser
- **File:** `backend/selko/services/emails.py`
- **Modify:** `parse_gmail_message()`
- **Action:**
  - Already sets `has_attachments` - keep this
  - No changes needed (attachment processing happens separately)

**Rationale:** Keep email parsing separate from attachment processing for modularity and performance. Attachments are fetched on-demand.

---

### Phase 4: CLI Integration

**Goal:** Enable attachment fetching via CLI tool

#### 4.1 Update Email Fetch CLI
- **File:** `cli/cli_fetch_emails.py`
- **Changes:**

```python
# Add new flag
parser.add_argument(
    "--fetch-attachments",
    action="store_true",
    help="Also download and store email attachments (default: False)",
)

# After saving emails, if flag enabled:
if args.fetch_attachments:
    logger.info("Fetching attachments for saved emails...")
    from selko.services.attachments import process_attachment
    from selko.services.gmail import extract_attachments

    total_processed = 0
    for email_data, email_record in zip(messages, saved_email_records):
        attachments = extract_attachments(email_data)
        if not attachments:
            continue

        logger.info(f"Processing {len(attachments)} attachments for email {email_record['id']}")
        for att_part in attachments:
            try:
                process_attachment(
                    client=client,
                    gmail_service=service,
                    email_id=email_record['id'],
                    message_id=email_data['id'],
                    attachment_part=att_part,
                    config=config,
                )
                total_processed += 1
            except AttachmentError as e:
                logger.error(f"Failed to process attachment: {e}")
                continue

    logger.info(f"Processed {total_processed} attachments")
```

#### 4.2 Update CLI Help Text
- Document new `--fetch-attachments` flag
- Add examples:
  ```bash
  # Fetch emails with attachments
  uv run python -m cli.cli_fetch_emails --max 10 --fetch-attachments
  ```

#### 4.3 Return Value Enhancement
- Modify `save_emails()` to return list of created/updated records (not just count)
- Needed to get `email_id` for attachment processing

**Validation:**
- Test with real Gmail account
- Verify attachments appear in database
- Check Supabase Storage for uploaded files

---

### Phase 5: Testing

**Goal:** Comprehensive test coverage

#### 5.1 Unit Tests for Attachments Service
- **File:** `backend/tests/test_attachments.py`
- **Test Cases:**

```python
def test_calculate_content_hash():
    """Test SHA-256 hash calculation."""
    # Known input -> known hash

def test_check_duplicate_attachment_found(db_client, test_user):
    """Test duplicate detection when hash exists."""
    # Insert existing attachment
    # Query by hash
    # Assert found

def test_check_duplicate_attachment_not_found(db_client, test_user):
    """Test no duplicate when hash doesn't exist."""

def test_upload_to_storage(db_client, test_user):
    """Test file upload to Supabase Storage."""
    # Upload test file
    # Verify path returned
    # Verify file exists in storage

def test_save_attachment_metadata(db_client, test_user, test_email):
    """Test database record creation."""
    # Save metadata
    # Query back
    # Assert fields match

def test_process_attachment_new(db_client, gmail_service_mock, test_email, config):
    """Test end-to-end processing of new attachment."""
    # Mock Gmail download
    # Process attachment
    # Verify storage upload
    # Verify database record

def test_process_attachment_duplicate(db_client, gmail_service_mock, test_email, config):
    """Test duplicate attachment is skipped."""
    # Create existing attachment with same hash
    # Process new attachment with same content
    # Verify no new storage upload
    # Verify existing record returned

def test_process_attachment_oversized(db_client, gmail_service_mock, test_email, config):
    """Test oversized attachment is skipped."""
    # Mock large file (>50MB)
    # Verify graceful skip

def test_process_attachment_rate_limited(db_client, gmail_service_mock, test_email, config):
    """Test retry logic on 429 errors."""
    # Mock 429 response -> success on retry
    # Verify exponential backoff
```

#### 5.2 Integration Tests
- **File:** `backend/tests/test_integration_attachments.py`
- **Test Cases:**

```python
@pytest.mark.integration
def test_fetch_emails_with_attachments(db_client, gmail_service, config):
    """Test end-to-end email + attachment fetching."""
    # Requires test Gmail account with known attachment
    # Fetch email
    # Process attachments
    # Verify database state
    # Verify storage state
```

#### 5.3 Test Fixtures
- **File:** `backend/tests/conftest.py`
- **New Fixtures:**

```python
@pytest.fixture
def test_email(db_client, test_user):
    """Create a test email record."""
    # Insert email
    # Yield email record
    # Cleanup

@pytest.fixture
def gmail_service_mock():
    """Mock Gmail API service."""
    # Mock service.users().messages().attachments().get()
    # Return fake attachment data

@pytest.fixture
def sample_attachment_data():
    """Sample attachment bytes for testing."""
    # Return small test file (e.g., 1KB PDF)
```

#### 5.4 Test Execution
```bash
# Run all tests
uv run pytest backend/tests/ -v

# Run only attachment tests
uv run pytest backend/tests/test_attachments.py -v

# Run with coverage
uv run pytest backend/tests/ --cov=selko.services.attachments
```

**Validation:**
- All tests pass
- Coverage >80% for attachments.py

---

### Phase 6: Documentation

**Goal:** Update all documentation for attachment storage

#### 6.1 Update CLAUDE.md
- **Section:** Database Schema (POC)
- **Add to `attachments` table description:**

```markdown
**Storage Integration:**
- Files stored in Supabase Storage bucket: `attachments`
- Path pattern: `{user_id}/{uuid}_{filename}`
- Content deduplication via SHA-256 `content_hash`
- RLS enforced: users only access their own attachments
- Max file size: 50 MB
- Supported MIME types: images, PDFs, documents

**Attachment Processing:**
- CLI flag: `--fetch-attachments` (opt-in)
- Duplicate detection: Same hash = skip download, reuse storage path
- Oversized files: Logged and skipped gracefully
- Rate limiting: Exponential backoff on 429 errors
```

#### 6.2 Update README.md
- **Section:** CLI Tools
- **Update Gmail Integration:**

```markdown
**Fetch Emails with Attachments:**
```bash
# Fetch emails only (no attachments)
uv run python -m cli.cli_fetch_emails --max 10

# Fetch emails AND download attachments
uv run python -m cli.cli_fetch_emails --max 10 --fetch-attachments
```

**Storage:**
- Attachments stored in Supabase Storage (bucket: `attachments`)
- Files encrypted at rest
- Content deduplication prevents duplicate storage
- Max file size: 50 MB
```

#### 6.3 Update PRD_ARCH.md (if needed)
- No changes needed - implementation matches spec

#### 6.4 Update CHANGELOG.md
- **Entry:**

```markdown
## 2026-01-22 - Attachment Storage Implementation

**Commit:** [hash after implementation]

### Added
- **Storage Infrastructure:**
  - `supabase/migrations/20260122000004_create_storage_buckets.sql`: Attachments bucket with RLS
  - Storage bucket config in `backend/selko/config.py`

- **Attachment Service:**
  - `backend/selko/services/attachments.py`: Complete attachment handling
    - `calculate_content_hash()`: SHA-256 hashing for deduplication
    - `download_gmail_attachment()`: Gmail API download with rate limiting
    - `upload_to_storage()`: Supabase Storage upload
    - `save_attachment_metadata()`: Database persistence
    - `process_attachment()`: End-to-end orchestration
    - `check_duplicate_attachment()`: Deduplication logic

- **Gmail Service Extension:**
  - `extract_attachments()` in `backend/selko/services/gmail.py`: MIME parsing

- **CLI Enhancement:**
  - `--fetch-attachments` flag in `cli/cli_fetch_emails.py`
  - Optional attachment processing during email fetch

- **Testing:**
  - `backend/tests/test_attachments.py`: Comprehensive unit tests
  - `backend/tests/test_integration_attachments.py`: Integration tests
  - Test fixtures for attachment testing

### Modified
- `backend/selko/config.py`: Added storage bucket configuration
- `backend/selko/services/emails.py`: Modified `save_emails()` to return records
- `cli/cli_fetch_emails.py`: Added attachment processing workflow
- `CLAUDE.md`, `README.md`: Updated documentation

### Purpose
Implements FR-A.2 (Email attachment extraction) and Arch 1.3 (Object/Blob Storage) from PRD.
Enables deduplication (FR-B.4) via content hashing. Provides foundation for future AI
processing of attachments (OCR, classification).
```

---

## Implementation Sequence

### Recommended Order
1. **Phase 1** (Storage) - Foundation must exist first
2. **Phase 2** (Service) - Core logic before integration
3. **Phase 3** (Gmail) - Gmail extension needed for CLI
4. **Phase 5** (Testing) - Write tests alongside Phases 2-3 (TDD approach)
5. **Phase 4** (CLI) - Integration after core is tested
6. **Phase 6** (Docs) - Final step after everything works

### Iterative Development
- After Phase 1: Test bucket creation manually
- After Phase 2: Test service functions in isolation
- After Phase 3: Test Gmail extraction with mock data
- After Phase 4: Test full workflow with real Gmail account
- After Phase 5: Verify all tests pass
- After Phase 6: Final review and commit

---

## Success Criteria

### Functional Requirements
- ✅ CLI can fetch emails with `--fetch-attachments` flag
- ✅ Attachments downloaded from Gmail API
- ✅ Files uploaded to Supabase Storage
- ✅ Metadata saved to `attachments` table
- ✅ Duplicate attachments detected and skipped
- ✅ RLS enforced (users only see their attachments)
- ✅ Oversized files (>50MB) gracefully skipped
- ✅ Rate limiting handled with retries

### Non-Functional Requirements
- ✅ Test coverage >80% for attachments service
- ✅ All tests pass in CI
- ✅ Documentation updated
- ✅ CHANGELOG entry created
- ✅ Code follows existing patterns (like `emails.py`)
- ✅ Logging consistent with project standards

### Future-Proofing
- ✅ Content hashing enables deduplication across emails
- ✅ Storage paths namespaced by user_id for multi-tenancy
- ✅ Modular design allows easy extension for:
  - OCR processing (Phase 2 of product)
  - Document classification
  - Cloud photo library ingestion (similar pattern)

---

## Risk Mitigation

### Technical Risks
| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Gmail API rate limits | High | Medium | Exponential backoff, retry logic |
| Large attachments (>50MB) | Medium | Low | Skip with clear logging |
| Storage quota exceeded | Low | High | Monitor usage, clear error messages |
| Duplicate hash collisions | Very Low | Medium | SHA-256 (cryptographically secure) |
| MIME parsing edge cases | Medium | Medium | Test with diverse email samples |

### Operational Risks
| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Storage costs | Medium | Medium | Start with small limits, monitor |
| Privacy/GDPR concerns | Low | High | User-scoped RLS, encryption at rest |
| Orphaned files | Low | Low | Future: cleanup job for deleted emails |

---

## Future Enhancements (Out of Scope)

### Phase 2 MVP (Web App)
- Web UI for viewing attachments
- Direct upload via drag-and-drop (FR-A.3)
- Attachment thumbnails/previews
- Download from web interface

### Phase 3 (Advanced Features)
- OCR processing of image attachments (FR-B.1)
- Document classification (FR-B.3)
- Virus scanning integration
- Backup/archival to S3 Glacier
- Cleanup job for orphaned files

### Performance Optimizations
- Batch attachment processing
- Parallel downloads (asyncio)
- Thumbnail generation for images
- CDN integration for delivery

---

## Questions & Decisions

### Resolved
- **Q:** Should attachments be processed automatically or opt-in?
  **A:** Opt-in via `--fetch-attachments` flag (POC phase). Default to automatic in MVP.

- **Q:** Where to store files?
  **A:** Supabase Storage (native integration, encryption, RLS).

- **Q:** How to handle duplicates?
  **A:** Content hash (SHA-256) check before upload. Reuse existing storage path.

- **Q:** What about inline images vs. attachments?
  **A:** Start with explicit attachments only. Inline images in future phase.

### Open Questions
- **Q:** Should we implement virus scanning?
  **A:** Not in POC. Consider for MVP (use ClamAV or external service).

- **Q:** Should we generate thumbnails for images?
  **A:** Not in POC. Add in MVP web UI phase.

- **Q:** How to handle email forwarding (same attachment, different email)?
  **A:** Current design handles via deduplication. Both emails reference same storage path.

---

## Appendix

### Relevant Code References
- Email parsing: `backend/selko/services/emails.py:24-81`
- Gmail API: `backend/selko/services/gmail.py:136-199`
- Database schema: `supabase/migrations/20260121000004_create_attachments.sql`
- Config loading: `backend/selko/config.py:71-131`
- Test patterns: `backend/tests/test_emails.py`

### External Documentation
- Gmail API Attachments: https://developers.google.com/gmail/api/guides/downloads
- Supabase Storage: https://supabase.com/docs/guides/storage
- Supabase Python Client: https://supabase.com/docs/reference/python/storage-from-upload
- MIME RFC: https://datatracker.ietf.org/doc/html/rfc2045

### Migration Ordering
- Current latest: `20260122000003_add_updated_at_triggers.sql`
- New migration: `20260122000004_create_storage_buckets.sql`
- No conflicts expected

---

**Plan Status:** Draft - Ready for Review
**Next Steps:** Approve plan → Begin Phase 1 implementation
