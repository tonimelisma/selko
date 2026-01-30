# Web Screens Specification

This document defines all web screens for Selko, prioritized by the Email → Calendar user journey.

## Priority Levels

| Priority | Definition |
|----------|------------|
| **P0-Critical** | Required for MVP (Email → Calendar journey) |
| **P1-Important** | Required shortly after MVP launch |
| **P2-Future** | Phase 2+ features |

---

## Screen Inventory

| Screen | Priority | Status | Description |
|--------|----------|--------|-------------|
| Login | P0 | ✅ Done | User authentication |
| Register | P0 | ✅ Done | User registration |
| Dashboard | P0 | 🟡 Partial | Central hub with overview |
| Review Queue | P0 | ❌ Not Started | Approve/edit/reject extracted data |
| Event Detail | P0 | ❌ Not Started | Side-by-side source vs. extracted |
| Integrations | P0 | ❌ Not Started | Connect Gmail, Google Calendar |
| Activity History | P0 | ❌ Not Started | View past actions, undo/redo |
| Email List | P1 | ❌ Not Started | Browse fetched emails |
| Email Detail | P1 | ❌ Not Started | View email content |
| Web Upload | P1 | ❌ Not Started | Manual file upload |
| Automation Rules | P1 | ❌ Not Started | Auto-approve rules |
| Settings | P1 | ❌ Not Started | User preferences |

---

## P0-Critical Screens (MVP)

### 1. Login Screen

**Route:** `/login`
**Status:** ✅ Done
**File:** `frontend/src/routes/login/+page.svelte`

**Purpose:** Authenticate existing users.

**Functionality:**
- Email/password input
- Error handling for invalid credentials
- "Forgot password" link (uses Supabase password reset)
- Link to registration

**Design Notes:**
- Centered card layout
- Minimal distractions
- Clear error messages

---

### 2. Register Screen

**Route:** `/register`
**Status:** ✅ Done
**File:** `frontend/src/routes/register/+page.svelte`

**Purpose:** Create new user accounts.

**Functionality:**
- Email, password, confirm password inputs
- Client-side validation (password match, minimum length)
- Success message with email confirmation instructions
- Link to login

---

### 3. Dashboard (Home)

**Route:** `/app`
**Status:** 🟡 Partial
**File:** `frontend/src/routes/app/+page.svelte`

**Purpose:** Central hub showing system status and pending items.

**Functionality (Required for MVP):**

```
┌─────────────────────────────────────────────────────────────────┐
│  [Logo] Selko                           [Integrations] [Logout] │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  📥 Review Queue                              [View All] │   │
│  │  ─────────────────────────────────────────────────────── │   │
│  │  3 items pending review                                  │   │
│  │                                                          │   │
│  │  📅 Birthday Party - Oct 5, 2:00 PM                     │   │
│  │     Source: Email from school@district.edu              │   │
│  │     [Review]                                            │   │
│  │                                                          │   │
│  │  📅 Dentist Appointment - Oct 10, 9:30 AM               │   │
│  │     Source: Email from clinic@dental.com                │   │
│  │     [Review]                                            │   │
│  │                                                          │   │
│  │  📅 Team Meeting - Oct 12, 3:00 PM                      │   │
│  │     Source: Email from manager@company.com              │   │
│  │     [Review]                                            │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  ⚡ Quick Actions                                        │   │
│  │  ─────────────────────────────────────────────────────── │   │
│  │  [Sync Emails]  [Upload File]  [View History]           │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌──────────────────────────┐  ┌──────────────────────────┐   │
│  │  📧 Email Stats          │  │  📅 Calendar Stats       │   │
│  │  ─────────────────────── │  │  ─────────────────────── │   │
│  │  Total: 127 emails       │  │  Approved: 15 events     │   │
│  │  Processed: 120          │  │  Synced: 12 events       │   │
│  │  Last sync: 5 min ago    │  │  Last sync: 2 min ago    │   │
│  └──────────────────────────┘  └──────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │  🔗 Integrations Status                                  │   │
│  │  ─────────────────────────────────────────────────────── │   │
│  │  Gmail: ✅ Connected (selko.test@gmail.com)             │   │
│  │  Google Calendar: ✅ Connected                          │   │
│  │  Google Photos: ⚪ Not connected        [Connect]       │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Data Requirements:**
- Pending events count and list (from `events` table, status = `pending_review`)
- Integration status (from `integrations` table)
- Email statistics (from `emails` table)
- Recent activity (from `calendar_sync_log` table)

**API Calls:**
- Direct Supabase: `events`, `emails`, `integrations`, `calendar_sync_log`
- Backend API: `syncEmails()` for manual sync button

---

### 4. Review Queue

**Route:** `/app/review`
**Status:** ❌ Not Started

**Purpose:** List all items pending user review.

**Functionality:**

```
┌─────────────────────────────────────────────────────────────────┐
│  [← Back] Review Queue                                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Filter: [All ▼]  [Calendar Events ▼]  [Newest First ▼]        │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 📅 Birthday Party                                        │   │
│  │ ───────────────────────────────────────────────────────  │   │
│  │ Oct 5, 2026 • 2:00 PM - 5:00 PM                         │   │
│  │ Location: 123 Main St                                    │   │
│  │                                                          │   │
│  │ Source: Email from school@district.edu (Oct 1, 2026)    │   │
│  │ Confidence: 95%                                          │   │
│  │                                                          │   │
│  │ [Approve] [Edit] [Reject]                               │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 📅 Dentist Appointment                                   │   │
│  │ ───────────────────────────────────────────────────────  │   │
│  │ Oct 10, 2026 • 9:30 AM - 10:30 AM                       │   │
│  │ Location: 456 Health Ave                                 │   │
│  │                                                          │   │
│  │ Source: Email from clinic@dental.com (Sep 28, 2026)     │   │
│  │ Confidence: 88%                                          │   │
│  │                                                          │   │
│  │ [Approve] [Edit] [Reject]                               │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  Showing 3 of 3 items                                           │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Functionality:**
- List all events with status `pending_review`
- Quick actions: Approve, Edit (→ Event Detail), Reject
- Filter by type, source, date
- Sort by date, confidence, source
- Batch actions (approve/reject multiple)

**User Actions:**
- **Approve**: Sets status to `approved`, triggers calendar sync
- **Edit**: Opens Event Detail screen
- **Reject**: Sets status to `rejected`, moves to history

**Data Requirements:**
- Events with status `pending_review`
- Linked source email information
- Attachment references (for preview)

---

### 5. Event Detail (Review Interface)

**Route:** `/app/events/[id]`
**Status:** ❌ Not Started

**Purpose:** Side-by-side view for reviewing and editing extracted data (FR-C.1).

**This is the core human-in-the-loop screen.**

**Functionality:**

```
┌─────────────────────────────────────────────────────────────────────────┐
│  [← Back to Queue] Review Event                    [Reject] [Approve]  │
├─────────────────────────────────────────────────────────────────────────┤
│                                                                         │
│  ┌────────────────────────────┐  ┌────────────────────────────────┐   │
│  │ 📧 SOURCE                  │  │ 📅 EXTRACTED EVENT              │   │
│  │                            │  │                                  │   │
│  │ From: school@district.edu  │  │ Title:                          │   │
│  │ Date: Oct 1, 2026          │  │ [Birthday Party for Emma    ]   │   │
│  │ Subject: Party Invitation  │  │                                  │   │
│  │                            │  │ Date:                            │   │
│  │ ─────────────────────────  │  │ [Oct 5, 2026        ] [▼]       │   │
│  │                            │  │                                  │   │
│  │ Dear Parents,              │  │ Start Time:                      │   │
│  │                            │  │ [2:00 PM            ] [▼]       │   │
│  │ You're invited to Emma's   │  │                                  │   │
│  │ birthday party!            │  │ End Time:                        │   │
│  │                            │  │ [5:00 PM            ] [▼]       │   │
│  │ Date: October 5th          │  │                                  │   │
│  │ Time: 2:00 PM - 5:00 PM    │  │ Location:                        │   │
│  │ Location: 123 Main Street  │  │ [123 Main Street              ]  │   │
│  │                            │  │                                  │   │
│  │ Please RSVP by Oct 3.      │  │ Description:                     │   │
│  │                            │  │ [Birthday party invitation.   ]  │   │
│  │ ─────────────────────────  │  │ [Please RSVP by Oct 3.        ]  │   │
│  │                            │  │                                  │   │
│  │ 📎 Attachments:            │  │ Calendar:                        │   │
│  │ [invite.pdf] (click view)  │  │ [Personal Calendar      ▼]      │   │
│  │                            │  │                                  │   │
│  └────────────────────────────┘  └────────────────────────────────┘   │
│                                                                         │
│  ┌─────────────────────────────────────────────────────────────────┐   │
│  │ 📎 Attachment Preview                                            │   │
│  │ ─────────────────────────────────────────────────────────────── │   │
│  │                                                                  │   │
│  │  ┌──────────────────────────────────────────────────────────┐   │   │
│  │  │                                                          │   │   │
│  │  │                   [PDF/Image Preview]                    │   │   │
│  │  │                                                          │   │   │
│  │  │              (Shows invite.pdf content)                  │   │   │
│  │  │                                                          │   │   │
│  │  └──────────────────────────────────────────────────────────┘   │   │
│  │                                                                  │   │
│  └─────────────────────────────────────────────────────────────────┘   │
│                                                                         │
│  AI Confidence: 95% • Extracted on: Oct 2, 2026 at 3:45 PM             │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

**Layout:**
- **Left panel (40%)**: Source content (email body, attachments)
- **Right panel (60%)**: Editable extracted data
- **Bottom panel**: Attachment preview (PDF viewer, image viewer)

**Editable Fields:**
- Title
- Date (date picker)
- Start time (time picker)
- End time (time picker)
- Location
- Description
- Target calendar (dropdown)

**Read-Only Fields:**
- Source email metadata
- AI confidence score
- Extraction timestamp

**Actions:**
- **Approve**: Validate fields, set status to `approved`, sync to calendar
- **Reject**: Set status to `rejected`, optional reason
- **Save Draft**: Save edits without approving
- **Cancel**: Return to queue without changes

**Conflict Handling (for UPDATE events):**
When the event is marked as an UPDATE (e.g., time change email):
- Show "Before" vs "After" comparison
- Highlight changed fields
- Option to merge or replace

---

### 6. Integrations Screen

**Route:** `/app/integrations`
**Status:** ❌ Not Started

**Purpose:** Connect and manage third-party services (Gmail, Google Calendar).

**Functionality:**

```
┌─────────────────────────────────────────────────────────────────┐
│  [← Back] Integrations                                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 📧 Gmail                                                 │   │
│  │ ───────────────────────────────────────────────────────  │   │
│  │ Status: ✅ Connected                                     │   │
│  │ Account: selko.test@gmail.com                           │   │
│  │ Scopes: gmail.readonly                                   │   │
│  │ Last sync: 5 minutes ago                                 │   │
│  │                                                          │   │
│  │ [Sync Now]  [Disconnect]                                │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 📅 Google Calendar                                       │   │
│  │ ───────────────────────────────────────────────────────  │   │
│  │ Status: ✅ Connected                                     │   │
│  │ Account: selko.test@gmail.com                           │   │
│  │ Default calendar: Personal                               │   │
│  │                                                          │   │
│  │ Calendars:                                               │   │
│  │ ● Personal (default)                                     │   │
│  │ ○ Work                                                   │   │
│  │ ○ Family                                                 │   │
│  │                                                          │   │
│  │ [Change Default]  [Disconnect]                          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 📷 Google Photos                                         │   │
│  │ ───────────────────────────────────────────────────────  │   │
│  │ Status: ⚪ Not Connected                                 │   │
│  │                                                          │   │
│  │ Connect to automatically import photos for processing.   │   │
│  │                                                          │   │
│  │ [Connect Google Photos]                                  │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Functionality:**
- View connection status for each provider
- **Connect**: Initiates OAuth flow via backend API
- **Disconnect**: Revokes tokens, removes from `integrations` table
- **Sync Now**: Triggers immediate email sync
- **Change Default Calendar**: Select which calendar to sync events to

**OAuth Flow:**
1. User clicks "Connect Gmail"
2. Frontend calls `backend.getGmailAuthUrl()`
3. Backend returns OAuth URL
4. User redirected to Google consent screen
5. Google redirects back with auth code
6. Backend exchanges code for tokens, stores in database
7. Frontend refreshes integration status

**Data Requirements:**
- `integrations` table (provider, status, email, scopes, last_sync)
- `calendar_settings` table (default_calendar_id)

---

### 7. Activity History

**Route:** `/app/history`
**Status:** ❌ Not Started

**Purpose:** View past actions and enable undo/redo (FR-C.2).

**Functionality:**

```
┌─────────────────────────────────────────────────────────────────┐
│  [← Back] Activity History                                      │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Filter: [All Actions ▼]  [This Week ▼]                        │
│                                                                 │
│  Today                                                          │
│  ─────                                                          │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 3:45 PM • Created calendar event                         │   │
│  │ "Birthday Party for Emma" → Personal Calendar            │   │
│  │ Source: Email from school@district.edu                   │   │
│  │                                              [Undo]      │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 2:30 PM • Rejected event                                 │   │
│  │ "Weekly Newsletter" - marked as not an event             │   │
│  │ Source: Email from news@company.com                      │   │
│  │                                              [Restore]   │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  Yesterday                                                      │
│  ─────────                                                      │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 5:15 PM • Updated calendar event                         │   │
│  │ "Dentist Appointment" - time changed to 10:00 AM         │   │
│  │ Source: Email from clinic@dental.com                     │   │
│  │                                              [Undo]      │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ 11:00 AM • Synced 3 emails                               │   │
│  │ From: Gmail (selko.test@gmail.com)                       │   │
│  │                                                          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  [Load More...]                                                 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Functionality:**
- Chronological list of all actions
- Filter by action type (create, update, delete, sync)
- Filter by date range
- **Undo**: Triggers compensating transaction (FR-C.2)
  - Create undo → Deletes from Google Calendar
  - Update undo → Restores previous values
  - Reject undo → Restores to `pending_review`

**Data Requirements:**
- `calendar_sync_log` table (action, timestamp, snapshot)
- `event_source_history` table (for detailed change tracking)
- `events` table (current state)

---

## P1-Important Screens (Post-MVP)

### 8. Email List

**Route:** `/app/emails`
**Status:** ❌ Not Started

**Purpose:** Browse all fetched emails.

**Functionality:**
- List all emails from `emails` table
- Filter by: processed/unprocessed, has events, date range
- Search by subject, sender
- Click to open Email Detail

**Wireframe:**
```
┌─────────────────────────────────────────────────────────────────┐
│  [← Back] Emails                          [🔍 Search] [Sync]   │
├─────────────────────────────────────────────────────────────────┤
│  Filter: [All ▼]  [Has Events ▼]  [Newest ▼]                   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ ● school@district.edu                                    │   │
│  │   Party Invitation                              Oct 1    │   │
│  │   📅 1 event extracted                                   │   │
│  └─────────────────────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ ○ newsletter@company.com                                 │   │
│  │   Weekly Update #42                             Sep 30   │   │
│  │   ⚪ No events                                           │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

---

### 9. Email Detail

**Route:** `/app/emails/[id]`
**Status:** ❌ Not Started

**Purpose:** View full email content and manually trigger processing.

**Functionality:**
- Display email headers (from, to, date, subject)
- Display email body (HTML rendered or plain text)
- List attachments with download/preview
- Show linked events (if any)
- Manual "Process with AI" button
- "Ignore" button (marks as not containing events)

---

### 10. Web Upload

**Route:** `/app/upload`
**Status:** ❌ Not Started

**Purpose:** Manual file upload for processing (FR-A.3).

**Functionality:**
```
┌─────────────────────────────────────────────────────────────────┐
│  [← Back] Upload Files                                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                                                          │   │
│  │              ┌─────────────────────────────┐             │   │
│  │              │                             │             │   │
│  │              │    📁 Drag & Drop Files     │             │   │
│  │              │         or                  │             │   │
│  │              │    [Browse Files]           │             │   │
│  │              │                             │             │   │
│  │              └─────────────────────────────┘             │   │
│  │                                                          │   │
│  │  Supported: PDF, PNG, JPG, HEIC (max 10MB)              │   │
│  │                                                          │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  Queued Files:                                                  │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ ✅ invite.pdf (2.3 MB) - Uploaded                        │   │
│  │ ⏳ receipt.jpg (1.1 MB) - Processing...                  │   │
│  │ ❌ large_file.pdf (15 MB) - File too large              │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  [Process All]                                                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Functionality:**
- Drag-and-drop zone
- File browser fallback
- Progress indicators
- Automatic upload to Supabase Storage
- Trigger AI processing after upload
- Results appear in Review Queue

---

### 11. Automation Rules

**Route:** `/app/rules`
**Status:** ❌ Not Started

**Purpose:** Define rules to auto-approve events (FR-B.5).

**Functionality:**
```
┌─────────────────────────────────────────────────────────────────┐
│  [← Back] Automation Rules                         [Add Rule]  │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Rules are checked in order. First match wins.                  │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ ≡ Rule 1: Auto-approve school emails                     │   │
│  │   ─────────────────────────────────────────────────────  │   │
│  │   IF sender contains "school.edu"                        │   │
│  │   THEN auto-approve to "Family" calendar                 │   │
│  │                                                          │   │
│  │   Matched: 5 events this month                           │   │
│  │                                      [Edit] [Delete]     │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │ ≡ Rule 2: Ignore newsletters                             │   │
│  │   ─────────────────────────────────────────────────────  │   │
│  │   IF subject contains "newsletter" OR "unsubscribe"      │   │
│  │   THEN ignore (don't extract events)                     │   │
│  │                                                          │   │
│  │   Matched: 12 emails this month                          │   │
│  │                                      [Edit] [Delete]     │   │
│  └─────────────────────────────────────────────────────────┘   │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

**Rule Builder Fields:**
- **Conditions**: Sender email/domain, subject contains, has attachments
- **Actions**: Auto-approve, Auto-reject/ignore, Route to specific calendar
- **Priority**: Drag to reorder

---

### 12. Settings

**Route:** `/app/settings`
**Status:** ❌ Not Started

**Purpose:** User preferences and account settings.

**Sections:**
- **Account**: Email, password change
- **Calendar**: Default calendar, timezone
- **Notifications**: Email digest frequency (daily/weekly/off)
- **Data**: Export data, delete account

---

## P2-Future Screens (Phase 2+)

### 13. Photo Library (Google Photos Integration)

**Route:** `/app/photos`
**Purpose:** Browse and process photos from Google Photos.
**Status:** Future (after Email→Calendar is complete)

### 14. Task Management

**Route:** `/app/tasks`
**Purpose:** View and manage extracted tasks.
**Status:** Future (after Calendar integration is complete)

### 15. Mobile-Specific Screens

**Platform:** iOS/Android native apps
**Screens:** Camera capture, push notification handling, local processing
**Status:** Phase 3

---

## Navigation Structure

```
/
├── /login                    (Public)
├── /register                 (Public)
└── /app                      (Protected - requires auth)
    ├── /app                  (Dashboard)
    ├── /app/review           (Review Queue)
    ├── /app/events/[id]      (Event Detail)
    ├── /app/emails           (Email List)
    ├── /app/emails/[id]      (Email Detail)
    ├── /app/integrations     (Integrations)
    ├── /app/history          (Activity History)
    ├── /app/upload           (Web Upload)
    ├── /app/rules            (Automation Rules)
    └── /app/settings         (Settings)
```

---

## Component Architecture

Reusable components needed across screens:

| Component | Used In | Description |
|-----------|---------|-------------|
| `Navbar` | All `/app/*` | Logo, nav links, user menu |
| `EventCard` | Dashboard, Review Queue | Event preview with actions |
| `EmailCard` | Email List | Email preview |
| `AttachmentViewer` | Event Detail, Email Detail | PDF/image preview |
| `DateTimePicker` | Event Detail | Date and time selection |
| `Badge` | Dashboard, Review Queue | Status indicators |
| `Modal` | Various | Confirmation dialogs |
| `EmptyState` | All lists | "No items" placeholder |
| `LoadingSpinner` | All screens | Loading indicator |
| `ErrorBoundary` | All screens | Error handling UI |

---

## Implementation Order

Based on PRD priorities and dependencies:

### Phase 1: MVP (Weeks 1-4)

1. **Dashboard enhancements** - Show pending events, integration status
2. **Integrations screen** - Connect Gmail and Google Calendar
3. **Review Queue** - List pending events
4. **Event Detail** - Side-by-side review interface
5. **Activity History** - Basic undo support

### Phase 2: Post-MVP (Weeks 5-8)

6. **Email List/Detail** - Browse emails
7. **Web Upload** - Manual file processing
8. **Automation Rules** - Auto-approve configuration
9. **Settings** - User preferences

### Phase 3: Future

10. Google Photos integration
11. Task management
12. Mobile apps

---

## Success Criteria

MVP is complete when a user can:

1. ✅ Register and log in
2. Connect Gmail (view email count)
3. Connect Google Calendar
4. See pending events on Dashboard
5. Review an event (side-by-side source vs. extracted)
6. Edit extracted fields
7. Approve → Event syncs to Google Calendar
8. Reject → Event marked as rejected
9. View activity history
10. Undo an approved event (deletes from calendar)
