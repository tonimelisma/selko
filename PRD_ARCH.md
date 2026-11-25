# **AI Assistant App: Product & Technical Specification**

## **Part 1: Product Requirements Document (PRD)**

### **1\. Overview**

An AI-powered assistant that automates personal organization by analyzing a user's digital inputs to manage their schedule, to-do list, and digital filing system.

### **2\. Core Value Proposition**

The system automatically ingests unstructured data from emails to create structured action items, calendar events, and organized files without manual user input. Photo-library ingestion (Google Photos) was removed on 2026-11-25, with its code and tables; [`docs/backlog.md`](docs/backlog.md) records why and where the old design lives in git history. The system acts as a "Human-in-the-loop" filter, ensuring accuracy before committing changes to the user's permanent records.

### **3\. Phased Architecture & Roadmap**

#### **3.0. Phase 0: Proof of Concept (Current - PARTIAL)**

* **Platform:** Local Python CLI tools (removed 2026-11-25: the web app is the only client)
* **Purpose:** Validate core data ingestion and AI extraction before building web application
* **Status:** PARTIAL (updated 2026-01-26)

**✅ Implemented Features:**
| Feature | Status | Implementation | Tests |
| :---- | :---- | :---- | :---- |
| Gmail OAuth authentication | ✅ DONE | `backend/selko/api/routes/integrations.py` | Integration tests |
| Email fetching and parsing | ✅ DONE | `backend/selko/services/emails.py` | Unit + Integration |
| Attachment download | ✅ DONE | `backend/selko/services/attachments.py` | Unit + Integration |
| Attachment storage | ✅ DONE | Files under the data directory, SHA-256 deduplication | Integration tests |
| Per-user data isolation | ✅ DONE | Every data-layer function takes the owner (`tests/db/test_ownership.py`) | Ownership tests |
| **Gemini LLM integration** | ✅ DONE | `backend/selko/services/gemini.py` | 55 unit + 10 integration |
| **Calendar event extraction** | ✅ DONE | `backend/selko/services/event_processing.py` | Real API evals |
| **Multimodal AI (text + images)** | ✅ DONE | Email body + attachments | Integration tests |
| Unit + Integration tests | ✅ DONE | **166 total tests** (55 unit + 111 integration) | All passing |

**❌ Not Yet Implemented (MVP scope):**
- ❌ Undo/Redo functionality
- ❌ Google Photos sync (removed 2026-11-25)
- ❌ Web upload interface

#### **3.1. Phase 1: Web-First Cloud Processing (MVP)**

* **Platform:** Responsive Web Application (Dashboard).  
* **Server-Side Sync:** The backend handles connections to third-party providers (Cloud-to-Cloud).  
* **Processing:** All AI analysis occurs on backend servers.  
* **Notification Channel:** Web UI Notifications (Toasts/Badges) & Email Digests.

#### **3.2. Phase 2: Mobile Companion & Local Context**

* **Mobile App:** iOS/Android app for direct camera capture and local device integration.  
* **Local Inference:** On-device processing for privacy.  
* **Push Notifications:** Real-time mobile alerts.

### **4\. Functional Requirements & Data Vectors (By Domain)**

#### **Domain A: Ingestion & Input Vectors**

*The system must support the following ingestion methods for Phase 1\.*

| ID | Feature | Description | Priority | Status |
| :---- | :---- | :---- | :---- | :---- |
| **FR-A.1** | **Cloud Photo Library** | Server detects new photos added to connected providers. | **P0** | ❌ Removed 2026-11-25 |
| **FR-A.2** | **Email Inbox** | Server detects new emails arriving in connected inboxes. Must extract attachments. | **P0** | ✅ **DONE** |
| **FR-A.3** | **Web Upload (Manual)** | Drag-and-drop zone on Web Dashboard for direct file ingestion (PDFs/Images). | **P0** | ❌ Not Started |

#### **Domain B: Intelligence Engine (AI & Logic)**

*Core processing capabilities.*

| ID | Feature | Description | Priority | Status |
| :---- | :---- | :---- | :---- | :---- |
| **FR-B.1** | **OCR & Text Extraction** | Extract text from physical images (handwriting recognition) and parse HTML/Text emails. | **P0** | ✅ **DONE** (Gemini multimodal) |
| **FR-B.2** | **Entity Extraction** | NLP to identify Entities: *Event Date*, *Time*, *Location*, *Vendor*, *Amount*. | **P0** | ✅ **DONE** (Calendar events) |
| **FR-B.3** | **Classification** | Distinguish document types: *Receipt* vs. *Invitation* vs. *Kid's Drawing* vs. *Trash*. | **P0** | 🟡 Partial (Events only) |
| **FR-B.4** | **Smart Idempotency** | Detect duplicates. **Update Logic:** If an email is an update (e.g., "Time Change"), modify the existing event rather than creating a duplicate. | **P0** | 🟡 Partial (Calendar sync idempotent) |
| **FR-B.5** | **Automation Rules** | User-defined logic (e.g., "Always accept from school@district.edu") to bypass review. | **P0** | ✅ **DONE** (Sender rules with auto-approve) |

#### **Domain C: User Experience & Control**

*Interaction model.*

| ID | Feature | Description | Priority | Status |
| :---- | :---- | :---- | :---- | :---- |
| **FR-C.1** | **Review Interface** | Side-by-side view (Source Asset vs. Extracted Data) allowing users to edit, approve, or reject. | **P0** | ✅ **DONE** (Web; the native iOS and Android apps are legacy, unmaintained) |
| **FR-C.2** | **Undo/Redo** | **Compensating Transactions:** Ability to revert any action (Create/Update/Delete) and restore original state. | **P0** | ❌ Not Started |
| **FR-C.3** | **Authentication** | Passwordless or Social Login. Granular scope management for integrations. | **P0** | ✅ **DONE** (email + password, Selko's own sign-in) |

#### **Domain D: System Outputs**

*External actions.*

| ID | Feature | Description | Priority | Status |
| :---- | :---- | :---- | :---- | :---- |
| **FR-D.1** | **Calendar Sync** | Create/Update events in external calendars. | **P0** | ✅ **DONE** (Full CRUD + idempotent sync) |
| **FR-D.2** | **File Storage** | Upload categorized documents to external cloud storage. | **P0** | ❌ Not Started |
| **FR-D.3** | **Task Management** | Create tasks in external task managers. | **P0** | ❌ Not Started |

### **5\. User Journeys & Example Journeys**

#### **Journey 1: The "Event Invitation" (Email \-\> Calendar)** - ✅ COMPLETE

*Goal: User receives a PDF invite and wants it on their calendar without typing.*

| Step | User Action | System Action | Related FR | Status |
| :---- | :---- | :---- | :---- | :---- |
| 1 | User receives email with "Invite.pdf". | System detects email, ingests PDF, performs OCR. | FR-A.2, FR-B.1 | ✅ DONE |
| 2 | N/A | **AI Analysis:** Identifies Date (Oct 5), Time (2 PM), Title (Party). Classifies as "Invitation". | FR-B.2, FR-B.3 | ✅ DONE |
| 3 | User logs into Dashboard. | **Notification:** Badge on "Review" tab. | FR-C.1 | ✅ DONE (Web) |
| 4 | User opens Review Tab. | Displays source email alongside proposed Event details. | FR-C.1 | ✅ DONE |
| 5 | User corrects time and clicks "Approve". | System updates payload, writes to Calendar. | FR-C.1, FR-D.1 | ✅ DONE |
| 6 | N/A | System logs action in Activity History. | FR-C.2 | 🟡 Partial (history view exists, no full undo) |

**Current Implementation:**
- ✅ Automatic email fetch and LLM processing via background workers
- ✅ Review interface on Web (SvelteKit); the iOS and Android apps are legacy, unmaintained
- ✅ Edit, approve, reject events with Google Calendar sync
- ✅ Sender rules for auto-approve/ignore automation
- ✅ History view with event status tracking
- ✅ Idempotent calendar sync (updates existing events, recreates if deleted)

#### **Calendar Sync Phased Approach**

**Phase 1 (Current):** Basic idempotency + sync log table + CLI

The calendar sync is now idempotent:
1. If `google_calendar_event_id` is NULL: CREATE new calendar event
2. If `google_calendar_event_id` exists:
   - Try to UPDATE the existing event
   - If 404 (deleted from Calendar): CREATE new event with new ID
3. All syncs logged to `calendar_sync_log` table for audit trail

**Phase 2 (Future):** Smart merge with drift detection

When syncing and detecting user has manually edited the Calendar event:
1. **Preserve user changes** - their edits are authoritative
2. **Add notes for differences** - append to description like:
   > "Note: You've manually set the address as XYZ, but an email from [sender] on [date] suggests it's [our extracted address]"

This respects user agency while keeping them informed of new information from emails.

The `calendar_sync_log.snapshot_synced` field stores what we sent to Google Calendar, enabling future comparison with the actual Calendar state to detect drift.

#### **Journey 4: The "Kid's Drawing" (Photo \-\> Cloud Storage)** - ❌ NOT BUILT (photo ingestion removed 2026-11-25)

*Goal: User snaps a memory, and system automatically files it to the correct folder.*

| Step | User Action | System Action | Related FR | Status |
| :---- | :---- | :---- | :---- | :---- |
| 1 | User snaps a photo of child's drawing. | Phone syncs photo to Cloud Library. | FR-A.1 | ❌ Not built |
| 2 | N/A | Server detects new asset in Cloud Library. | FR-A.1 | ❌ Not built |
| 3 | N/A | **AI Analysis:** Visual recognition detects content is "Hand-drawn art" or "Child's Drawing". | FR-B.3 | ❌ Not built |
| 4 | N/A | **Rule Check:** System finds user rule: Type: Artwork \-\> Dest: /Family/Kids Art. | FR-B.5 | ❌ Not built |
| 5 | N/A | **Execution:** System copies image to specified folder automatically (bypassing review). | FR-D.2 | ❌ Not built |

**Rationale:** Photo-library ingestion was removed; this journey would need it rebuilt (see [`docs/backlog.md`](docs/backlog.md)).

## **Part 2: Technical Architecture Specification**

### **1\. High-Level Architecture Requirements**

#### **1.1 Frontend Layer**

* **Public Marketing Site:**  
  * **Requirement:** Static content delivery system optimized for SEO, landing pages, and conversion funnels.  
  * **Component:** Registration Wizard for bridging marketing to application onboarding.  
* **Web Dashboard (MVP):**  
  * **Requirement:** Responsive Single Page Application (SPA) accessible via standard web browsers.  
  * **Auth Requirement:** Integration with an Identity Provider supporting Passwordless (Magic Link) and OIDC (Social Login).  
  * **State Management:** Mechanism to poll or refresh job status without full page reloads.  
  * **Ingestion UI:** Secure drag-and-drop interface for direct file uploads.  
* **Mobile App (Phase 2):**  
  * **Requirement:** Native or Cross-Platform mobile application.  
  * **Capability:** Direct access to device camera and local storage APIs.

#### **1.2 Backend Services**

* **API Gateway:**  
  * **Requirement:** Centralized entry point for frontend clients, handling rate limiting, routing, and session validation.  
* **Ingestion Service:**  
  * **Requirement:** Background worker service capable of long-polling and handling webhooks from third-party providers.  
  * **Token Management:** Secure handling and refreshing of OAuth tokens for connected integrations.  
  * **Attachment Parsing:** Ability to recursively parse MIME types to extract embedded attachments (PDFs/Images).  
* **Orchestration Engine:**  
  * **Requirement:** State machine to manage asset lifecycle: Ingest \-\> Analyze \-\> User Review \-\> Execute.  
  * **Transaction Management:** Logic to support "Compensating Transactions" for Undo/Redo functionality.  
* **AI Service Layer:**  
  * **Requirement:** Abstraction layer to interface with OCR and LLM providers, ensuring model agnosticism.

#### **1.3 Infrastructure & Storage**

* **Object/Blob Storage:**  
  * **Requirement:** Scalable storage for unstructured data (email bodies, images, PDFs). Must support encryption at rest.  
* **Relational Database:**  
  * **Requirement:** ACID-compliant database for storing user profiles, relational metadata, taxonomy, and audit logs.  
* **Asynchronous Job Queue:**  
  * **Requirement:** Distributed queue system to decouple lightweight ingestion tasks from resource-intensive AI processing.

### **2\. Core Data Model Requirements**

#### **2.1 User & Configuration**

* **users**: Stores core identity and link to Identity Provider.  
* **integrations**: Stores connection state for third-party providers.  
  * *Critical Fields:* encrypted refresh tokens, scope lists, provider status.  
* **user\_categories**: Stores custom user taxonomy (e.g., "Tax", "Medical").

#### **2.2 Assets & Inferences (The "Brain")**

* **assets**: Represents the raw input unit.  
  * *Requirements:* Must store unique identifiers (external\_id), content hashes for deduplication, and reference links to Object Storage.  
  * *Sources:* Email Providers, Manual Uploads.
* **inferences**: Represents the AI's findings (1 Asset can yield N Inferences).  
  * *Requirements:* Stores extracted structured data (JSON), confidence scores, and links to specific user\_categories.  
  * *States:* PENDING\_REVIEW, APPROVED, REJECTED, AUTO\_EXECUTED.

#### **2.3 History & Logic**

* **automation\_rules**: Stores user-defined logic to bypass manual review.  
  * *Logic:* Trigger (Sender/Type) \-\> Action (Accept/File) \-\> Target (Category).  
* **action\_history**: The Ledger for Undo/Redo.  
  * *Requirements:* Must store previous\_state and new\_state snapshots for every action to enable rollback.  
  * *Fields:* action\_type (CREATE, UPDATE, DELETE), external\_resource\_id (ID of the created calendar event or file).

### **3\. Workflow Logic Requirements**

#### **3.1 Ingestion, Deduplication & Updates**

1. **Ingestion:** System must handle both push (Webhooks) and pull (Polling) strategies.  
2. **Deduplication:** System must calculate and check content\_hash against existing assets to prevent duplicate processing of the same file.  
3. **Semantic Update Resolution:**  
   * System must detect if a new asset is an *update* to an existing record (e.g., a "Time Changed" email).  
   * *Action:* Create an inference marked as **UPDATE** rather than **CREATE**. Merge new values over old values.

#### **3.2 Analysis & Classification**

1. **Processing:** System must perform OCR on images and parsing on text/HTML.  
2. **Rule Evaluation:** System must query automation\_rules before adding to the Review Queue.  
   * *Match:* Execute immediately.  
   * *No Match:* Queue for user review.

#### **3.3 The Review Queue**

1. **UI Requirement:** Must display the source asset (left) and the editable extracted data (right) simultaneously.  
2. **Conflict Resolution:** If the item is an **UPDATE**, the UI must highlight the "Before" vs "After" changes.

#### **3.4 Execution & Undo/Redo**

1. **Execution:** System must write to the external provider (Calendar/Drive) and store the resulting external ID.  
2. **Compensating Transactions (Undo):**  
   * *Requirement:* Triggering "Undo" must reverse the external action.  
   * *Create Undo:* Triggers external DELETE.  
   * *Update Undo:* Triggers external UPDATE (restoring previous\_state).  
   * *Reject Undo:* Triggers state restoration to PENDING\_REVIEW.

---

## **Part 3: Implementation Architecture**

### **0. Current Implementation Status**

**Last Updated:** 2026-01-26

**✅ Completed Components:**

| Component | Status | Files | Tests |
|-----------|--------|-------|-------|
| **Data Layer** | ✅ Complete | `backend/selko/db/` (SQLite) | Real-database tests |
| **Gmail Integration** | ✅ Complete | `selko/services/gmail.py` | 5 integration tests |
| **Email Pipeline** | ✅ Complete | `selko/services/emails.py` | 9 integration tests |
| **Attachment Storage** | ✅ Complete | `selko/services/attachments.py` | 8 integration tests |
| **Gemini LLM Integration** | ✅ Complete | `selko/services/gemini.py` | 55 unit + 10 integration |
| **Calendar Event Extraction** | ✅ Complete | `selko/api/schemas/calendar.py` | Real API evals |
| **Authentication** | ✅ Complete | `selko/services/accounts.py` | Account and route tests |
| **Data isolation** | ✅ Complete | Owner-scoped data layer | `tests/db/test_ownership.py` |

**❌ Not Yet Implemented:**

| Component | Priority | Blocker | Next Steps |
|-----------|----------|---------|------------|
| **Undo/Redo** | P0 | None | Compensating transactions (action_history table created) |
| **Web Upload** | P1 | None | Frontend drag-and-drop |

**Current Capability:**
- ✅ Fetch emails from Gmail (OAuth authenticated)
- ✅ Download and store attachments (SHA-256 deduplication)
- ✅ Extract calendar events from emails using Gemini LLM
- ✅ Process multimodal content (email body + image attachments)
- ✅ Write events to Google Calendar (full CRUD + idempotent sync)
- ✅ Review interface on Web
- ✅ Sender rules for automation (ignore + auto-approve)
- ✅ History view with undo actions
- ❌ No full undo/redo with compensating transactions

**Next Milestone: Phase 2 — Extended Inputs**
1. Undo/Redo with compensating transactions
3. Web upload interface

---

### **1. System Overview**

```
                 Browser (SvelteKit web app, served by the same process)
                                   │  one origin, Bearer token
                                   ▼
┌──────────────────────────── selko (one process) ────────────────────────────┐
│  FastAPI: /auth/* (own sign-in) · data routes · provider ops · /live (SSE)   │
│  Workers: email ingestion (Gmail, Outlook) · LLM extraction · calendar writes │
│  selko.db: one writer + WAL readers · Bus / WorkSignals (in-process wake-ups) │
└───────────────────────────────────────┬─────────────────────────────────────┘
                                        │
                     SELKO_DATA_DIR: selko.db + attachments/ (+ backups/)

Outbound: Gmail API · Microsoft Graph · Google Calendar · LLM providers
```

Selko ships as one container image (`ghcr.io/tonimelisma/selko:<sha>`), built,
checked and cosign-signed by `.github/workflows/image.yml`. It runs as a
non-root user with a read-only root filesystem, no capabilities and `/data` as
its only volume. Design and decisions: `docs/specs/sqlite-single-process/`.

### **2. Development Phases**

#### **Phase 0: Proof of Concept**
- **Status:** COMPLETE (2026-01-23)
- **Goal:** Validate core data ingestion and storage
- **Components:** CLI tools, a hosted Postgres database and storage (since replaced by SQLite), Gmail API
- **Features implemented:**
  - Gmail OAuth authentication
  - Email fetching and parsing
  - Attachment download and storage
  - Content deduplication (SHA-256)
  - Per-user data isolation

#### **Phase 1: MVP (Web-First Cloud Processing)**
- **Status:** ✅ MOSTLY COMPLETE (started 2026-01-25)
- **Goal:** Complete end-to-end journey: Email → LLM → Calendar
- **Components:** FastAPI, Gemini LLM, Google Calendar API, SvelteKit
- **Implementation progress:**
  1. ✅ **LLM integration (Gemini 3 Flash)** - DONE (2026-01-26)
  2. ✅ **Email → LLM analysis pipeline** - DONE (2026-01-26)
  3. ✅ **Calendar sync (write events)** - DONE (full CRUD + idempotent sync)
  4. ✅ **Review interface (web)** - DONE
  5. ❌ Undo/Redo functionality - NOT STARTED
  6. ✅ **Automation rules (sender rules)** - DONE (ignore + auto-approve)

#### **Phase 2: Extended Inputs**
- **Status:** FUTURE
- **Goal:** Add more input sources after Email→Calendar works
- **Features:**
  - Web upload interface
  - Direct camera capture (mobile)

#### **Phase 3: Mobile Companion**
- **Status:** FUTURE
- **Goal:** Native mobile app with on-device processing
- **Features:**
  - iOS/Android apps
  - Local LLM inference
  - Push notifications

### **3. Key Architectural Principles**

#### **3.1 One API, one process, one file**
Clients talk only to Selko's API; there is no database client in the browser.
The API answers the data the screens need (`docs/api-client-endpoints.md`),
scoped to the signed-in user, and pushes change notices over `/live`. The same
process runs the background work, over the same SQLite file, so a write that
creates work wakes the worker in-process instead of through a database
notification channel.

**Benefits:**
- One thing to run, back up and restore: a data directory
- Ownership enforced in one place (the data layer), tested as such
- No network hop between the API and its data

#### **3.2 End-to-End First**
Complete full journeys before expanding scope:
- Do NOT add Task Management until Calendar integration is complete
- Each input→output path must be fully functional before adding more

#### **3.4 LLM-Centric Intelligence**
All intelligence features use the same multimodal LLM (Gemini):
- OCR & text extraction → LLM reads images/PDFs directly
- Entity extraction → LLM extracts dates, times, locations
- Document classification → LLM categorizes content
- No separate OCR service needed - the LLM is multimodal

#### **3.5 Human-in-the-Loop**
Every automated action goes through review:
- Side-by-side view of source vs. extracted data
- User can approve, edit, or reject
- Automation rules can bypass review for trusted sources
- Undo/Redo for all actions

#### **3.6 Simplified Stack (YAGNI)**
Add complexity only when measured need exists:
- Today: one process and one SQLite file
- Add a second process, a queue or a database server only when a measured limit demands it

### **4. The "Async Monolith" Architecture**

Selko is a single asyncio process: the web app, the API and every background
task share one event loop and one database file.

#### **4.1 Component Overview**

| Component | Where | Role |
|---|---|---|
| Web app | built SvelteKit files, served by FastAPI (`mount_web_app`) | The only client |
| API | `selko.api` | Sign-in, data, provider operations, `/live` |
| Ingestion runtime | `selko.workers.ingestion_runtime` | Provider discovery, acquisition, attachments, health floor, calendar mirror |
| Worker pool | `selko.workers.pool` | LLM extraction, calendar writes, recovery |
| Data layer | `selko.db` | One writer (`BEGIN IMMEDIATE`), WAL readers, migrations, typed errors, Bus/WorkSignals |

#### **4.2 The Three Workloads**

1. **Requests:** API calls, short reads and writes.
2. **I/O-bound background work:** provider polling and downloads, waiting on
   network; leases in the database make each item single-owner.
3. **LLM calls:** slow, rate-limited by per-user daily quotas; run in the worker
   pool, never inline in a request (except an explicit "process this email").

Blocking SQLite and CPU work runs in threads (`db.run(...)`), so the loop keeps
serving requests.

### **5. Technology Stack Decisions**

| Layer | Choice | Why |
|---|---|---|
| **Web** | SvelteKit 2 + DaisyUI | Small, fast, static build served by the API |
| **API** | FastAPI (Python) | Async-native; the workload is I/O bound |
| **Data** | SQLite (WAL, STRICT tables) | One file, no server, transactional, enough for this load |
| **Files** | The data directory | Attachments next to the database; one volume to back up |
| **Auth** | Selko's own (bcrypt, HS256 access tokens, rotating refresh cookie) | No external auth service; imported password hashes keep working |
| **Delivery** | A signed container image | The server pulls and verifies it; no deploy credentials in CI |

#### **5.1 Why FastAPI**
- **Async Native:** Heavily I/O bound (Gmail, Graph, LLM APIs). Blocking frameworks would choke concurrency.
- **Pydantic:** Typed request/response models and LLM output validation.

#### **5.2 Why SQLite**
- One user-facing process and a modest data volume: a database server adds a
  network hop, credentials and operations for nothing.
- WAL gives concurrent readers beside the single writer; the single writer
  makes leases and fences simple and race-free.
- Backup is a file copy (`VACUUM INTO` before every migration).

### **6. Rejected Alternatives**

#### **6.1 Rejection: Serverless (Google Cloud Run / AWS Lambda)**
- **Problem:** Serverless instances spin down to zero when idle. That kills the in-process ingestion loop, and a local SQLite file needs one long-lived owner.
- **Workaround Cost:** Keeping a Cloud Run instance "Always On" costs ~$25+/mo.
- **Complexity:** Requires external "Pingers" (Cloud Scheduler) to trigger polling, splitting logic and adding IAM permission complexity.

#### **6.2 Rejection: Microservices / Separate Workers**
- **Architecture:** Deploying a separate "Worker" service for background jobs.
- **Problem:** Two processes contending for one SQLite file, and a message channel between them.
- **Complexity:** Requires a queue service (Redis or similar) to pass work between API and Worker.
- **Verdict:** Overkill for a solo dev MVP.

#### **6.3 Rejection: Django**
- **Problem:** ORM is heavy and synchronous. Overkill for an API-first backend.

### **7. Deployment Strategy**

#### **7.1 The image**
`.github/workflows/image.yml` builds the image once, runs it under the
server's limits (`scripts/image-lane.sh`: read-only root, no capabilities,
400 MB, `/data` only) with the production health invariants, and on `main`
pushes `ghcr.io/tonimelisma/selko:<sha>` and signs it keylessly with cosign.
The server that runs production pulls the newest signed image and verifies the
signature; deployment lives outside this repository.

#### **7.2 Configuration**
An env file: `SELKO_JWT_SECRET`, `ALLOWED_ORIGINS`, `API_PUBLIC_URL`,
`FRONTEND_URL`, OAuth client IDs and secrets, LLM keys,
`ENABLE_BACKGROUND_PROCESSING`. `SELKO_DATA_DIR` is `/data` in the image.
Migrations apply at startup.

#### **7.3 Code Structure**
See `backend/selko/api/app.py` (lifespan: open and migrate the database,
release stale leases, start the workers; mount the web app).

### **8. Security Model**

#### **8.1 Data isolation**
Every public data-layer function that touches a user-owned table takes the
owner and scopes by it; `backend/tests/db/test_ownership.py` fails on one that
does not. Routes answer another user's id with 404.

#### **8.2 Sign-in**
Passwords are bcrypt hashes. Access tokens are short-lived HS256 JWTs; the
refresh token is an HttpOnly, SameSite=Strict cookie scoped to `/auth`, stored
only as its SHA-256, rotated on every use; reuse of a rotated token revokes the
session. Cookie endpoints check `Origin`. Password sign-ins are rate-limited
per address.

#### **8.3 OAuth 2.0**
External integrations use OAuth with minimal scopes:
- Gmail: `gmail.readonly` (read-only access)
- Calendar: `calendar.events` (event management)
- Microsoft: `Mail.Read` and `Calendars.ReadWrite` in one consent (an older mail-only grant is not a writable calendar)

#### **8.4 Storage Isolation**
Attachments live under `<data>/attachments/{user_id}/…`; paths outside the
directory are refused, and `GET /attachments/{id}/content` serves only the
owner's files.

#### **8.5 The container**
Non-root user, read-only root filesystem, no capabilities, no new privileges,
a memory limit, and one writable volume.

### **9. Future Scalability (When to break the Monolith)**

1.  **CPU saturation:** if LLM pre-processing or image work blocks the loop, move it to a process pool first, a second service last.
2.  **Write contention:** if the single writer becomes the bottleneck (measured as `DbBusy` or write latency), batch writes; a database server is the last step.
3.  **Memory:** the image is checked under 400 MB; raise the limit before splitting.

**Current Status:** One process is sufficient for the expected users, given the async, I/O-bound workload.

---

## **Part 4: Testing Strategy**

The test strategy and commands are in [`docs/testing-guide.md`](docs/testing-guide.md);
the gates are in `CLAUDE.md` ("The verification process"). In short:

- **Every database test runs on a real SQLite file** with every migration
  applied (`backend/tests/sqlite_fixtures.py`). Providers (Gmail, Graph, Google
  Calendar, LLMs) are mocked; the database never is.
- **Routes are tested through the real app** with real access tokens, including
  an ownership matrix (`backend/tests/db/test_client_routes.py`).
- **Guards** keep the suite honest: reachability, no hosted-database imports,
  owner-scoped data functions, a single events writer, pinned CHECK domains.
- **The image lane** runs the exact image under the server's limits and checks
  health, the production invariants, sign-in, review with a live update,
  attachment download, and a database imported from a Postgres fixture.
- **Real LLM calls** run only with `--run-llm` and in the evals
  (`docs/evals-process.md`).
