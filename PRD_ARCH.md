# **AI Assistant App: Product & Technical Specification**

## **Part 1: Product Requirements Document (PRD)**

### **1\. Overview**

An AI-powered assistant that automates personal organization by analyzing a user's digital inputs to manage their schedule, to-do list, and digital filing system.

### **2\. Core Value Proposition**

The system automatically ingests unstructured data from emails and photos to create structured action items, calendar events, and organized files without manual user input. It acts as a "Human-in-the-loop" filter, ensuring accuracy before committing changes to the user's permanent records.

### **3\. Phased Architecture & Roadmap**

#### **3.0. Phase 0: Proof of Concept (Current - COMPLETE)**

* **Platform:** Local Python CLI tools
* **Purpose:** Validate core data ingestion before building web application
* **Status:** COMPLETE (2026-01-23)

**Implemented Features:**
| Feature | Status | Implementation |
| :---- | :---- | :---- |
| Gmail OAuth authentication | DONE | `cli/cli_auth_gmail.py` |
| Email fetching and parsing | DONE | `backend/selko/services/emails.py` |
| Attachment download | DONE | `backend/selko/services/attachments.py` |
| Supabase Storage upload | DONE | With SHA-256 deduplication |
| RLS-enforced multi-tenancy | DONE | All tables have RLS policies |
| Unit + Integration tests | DONE | 71+ tests across all services |

**Not Yet Implemented (MVP scope):**
- LLM integration (Gemini)
- Calendar sync
- Review interface
- Undo/Redo

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

| ID | Feature | Description | Priority |
| :---- | :---- | :---- | :---- |
| **FR-A.1** | **Cloud Photo Library** | Server detects new photos added to connected providers. Primary method for "mobile" photo ingestion in Phase 1\. | **P0** |
| **FR-A.2** | **Email Inbox** | Server detects new emails arriving in connected inboxes. Must extract attachments. | **P0** |
| **FR-A.3** | **Web Upload (Manual)** | Drag-and-drop zone on Web Dashboard for direct file ingestion (PDFs/Images). | **P0** |

#### **Domain B: Intelligence Engine (AI & Logic)**

*Core processing capabilities.*

| ID | Feature | Description | Priority |
| :---- | :---- | :---- | :---- |
| **FR-B.1** | **OCR & Text Extraction** | Extract text from physical images (handwriting recognition) and parse HTML/Text emails. | **P0** |
| **FR-B.2** | **Entity Extraction** | NLP to identify Entities: *Event Date*, *Time*, *Location*, *Vendor*, *Amount*. | **P0** |
| **FR-B.3** | **Classification** | Distinguish document types: *Receipt* vs. *Invitation* vs. *Kid's Drawing* vs. *Trash*. | **P0** |
| **FR-B.4** | **Smart Idempotency** | Detect duplicates. **Update Logic:** If an email is an update (e.g., "Time Change"), modify the existing event rather than creating a duplicate. | **P0** |
| **FR-B.5** | **Automation Rules** | User-defined logic (e.g., "Always accept from school@district.edu") to bypass review. | **P0** |

#### **Domain C: User Experience & Control**

*Interaction model.*

| ID | Feature | Description | Priority |
| :---- | :---- | :---- | :---- |
| **FR-C.1** | **Review Interface** | Side-by-side view (Source Asset vs. Extracted Data) allowing users to edit, approve, or reject. | **P0** |
| **FR-C.2** | **Undo/Redo** | **Compensating Transactions:** Ability to revert any action (Create/Update/Delete) and restore original state. | **P0** |
| **FR-C.3** | **Authentication** | Passwordless or Social Login. Granular scope management for integrations. | **P0** |

#### **Domain D: System Outputs**

*External actions.*

| ID | Feature | Description | Priority |
| :---- | :---- | :---- | :---- |
| **FR-D.1** | **Calendar Sync** | Create/Update events in external calendars. | **P0** |
| **FR-D.2** | **File Storage** | Upload categorized documents to external cloud storage. | **P0** |
| **FR-D.3** | **Task Management** | Create tasks in external task managers. | **P0** |

### **5\. User Journeys & Example Journeys**

#### **Journey 1: The "Event Invitation" (Email \-\> Calendar)**

*Goal: User receives a PDF invite and wants it on their calendar without typing.*

| Step | User Action | System Action | Related FR |
| :---- | :---- | :---- | :---- |
| 1 | User receives email with "Invite.pdf". | System detects email, ingests PDF, performs OCR. | FR-A.2, FR-B.1 |
| 2 | N/A | **AI Analysis:** Identifies Date (Oct 5), Time (2 PM), Title (Party). Classifies as "Invitation". | FR-B.2, FR-B.3 |
| 3 | User logs into Dashboard. | **Notification:** Badge on "Review" tab. | FR-C.1 |
| 4 | User opens Review Tab. | Displays PDF side-by-side with proposed Event details. | FR-C.1 |
| 5 | User corrects time (OCR read 5 PM as 6 PM) and clicks "Approve". | System updates payload, writes to Calendar. | FR-C.1, FR-D.1 |
| 6 | N/A | System logs "Event Created (User Modified)" in Activity Log. | FR-C.2 |

#### **Journey 4: The "Kid's Drawing" (Photo \-\> Cloud Storage)**

*Goal: User snaps a memory, and system automatically files it to the correct folder.*

| Step | User Action | System Action | Related FR |
| :---- | :---- | :---- | :---- |
| 1 | User snaps a photo of child's drawing. | Phone syncs photo to Cloud Library. | FR-A.1 |
| 2 | N/A | Server detects new asset in Cloud Library. | FR-A.1 |
| 3 | N/A | **AI Analysis:** Visual recognition detects content is "Hand-drawn art" or "Child's Drawing". | FR-B.3 |
| 4 | N/A | **Rule Check:** System finds user rule: Type: Artwork \-\> Dest: /Family/Kids Art. | FR-B.5 |
| 5 | N/A | **Execution:** System copies image to specified folder automatically (bypassing review). | FR-D.2 |

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
  * *Sources:* Email Providers, Photo Libraries, Manual Uploads.  
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