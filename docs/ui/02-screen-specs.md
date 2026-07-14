# Screen-by-Screen Specifications

Detailed responsive specs for each Selko web screen. For user journeys, see `docs/ui/01-user-journeys.md`. For shared patterns and components, see `docs/ui/03-patterns-and-components.md`.

Each spec follows a consistent template:
- **Route, primary/secondary actions**
- **Desktop layout** (1024px+ / `lg:` breakpoint)
- **Tablet layout** (768–1023px / `md:` breakpoint)
- **Mobile layout** (320–767px / default)
- **States**: Loading, Empty, Populated, Error
- **Data requirements** (service functions from `frontend/src/lib/services/`)
- **Key interactions**

---

## 1. Review Queue (Home Screen)

**Route:** `/app`

### Purpose

Home screen of the app. Two review lanes grouped by sender:

1. **New** — events to add to the calendar (`pending_review`)
2. **Changes** — proposed updates to events already on the calendar (`pending_change`), showing field-level before → after diffs from `event_sources.change_set`

When integrations are not connected or authorized, this screen is entirely replaced by an integration setup view.

After a calendar match, the LLM proposes a structured changeset; code gates equivalent/no-op diffs. Pure rediscoveries (RSVP replies with no real change) never appear here.

### Primary Actions
- Accept event (individual or all in sender group)
- Edit event (navigate to Event Detail)
- Reject event (individual or all in sender group)

### Desktop Layout (lg:)

Full-width list grouped by sender. Page container: `max-w-7xl mx-auto`.

```
┌─ Sender Group ──────────────────────────────────────────────────┐
│ School District                                                    │
│ school@district.edu                                        [⋯]   │
│                                                                   │
│  ┌─ Event Card ────────────────────────────────────────────────┐ │
│  │ Birthday Party                                               │ │
│  │ 🕐 Oct 5, 2:00 PM – 5:00 PM                                │ │
│  │ 📍 123 Main St                                               │ │
│  │                              [Accept] [Edit] [Reject]        │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                                                                   │
│  ┌─ Event Card ────────────────────────────────────────────────┐ │
│  │ RSVP Reminder                                                │ │
│  │ 🕐 Oct 3 · All Day                                          │ │
│  │                              [Accept] [Edit] [Reject]        │ │
│  └──────────────────────────────────────────────────────────────┘ │
│                                                                   │
│  ┌─ Event Card ────────────────────────────────────────────────┐ │
│  │ Field Trip                                                   │ │
│  │ 🕐 Oct 15, 8:00 AM                                          │ │
│  │ 📍 City Museum                                               │ │
│  │                              [Accept] [Edit] [Reject]        │ │
│  └──────────────────────────────────────────────────────────────┘ │
└──────────────────────────────────────────────────────────────────┘
```

The three-dot menu [⋯] on the sender header contains:
- "Approve all" — approves all events from this sender
- "Reject all" — rejects all events from this sender
- "Ignore sender" — (disabled, future feature)

Each event card shows:
- Title
- Date/time (or "All Day")
- Location (if any)
- Action buttons: Accept (green/success), Edit (outlined primary), Reject (outlined red/error)

Events are grouped by sender only (no email sub-grouping). All events from a sender appear directly under that sender's header.

### Tablet Layout (md:)

Same sender-grouped structure. All action buttons retain text labels.

### Mobile Layout (default)

Same sender-grouped structure as stacked cards:

- **Sender**: section header with sender name, email, and three-dot menu (right-aligned)
- **Events**: full-width cards stacked below each sender
- Action buttons: text labels with icons — Accept (green), Edit (outlined), Reject (outlined red)

### Integration Setup State

When integrations are not fully connected/authorized, the entire queue is replaced:

```
┌──────────────────────────────────────────────────────────────────┐
│                                                                    │
│  Welcome to Selko!                                                │
│                                                                    │
│  Connect your Google account to get started.                      │
│  Selko will read your emails and create calendar                  │
│  events automatically.                                             │
│                                                                    │
│  [Connect Google Account]                                         │
│                                                                    │
│  ── OR, if partially connected: ──                                │
│                                                                    │
│  Gmail: ✓ Authorized                                              │
│  Google Calendar: ✗ Not authorized        [Authorize]             │
│                                                                    │
│  ── OR, if token expired: ──                                      │
│                                                                    │
│  Gmail: ✗ Connection expired              [Reconnect]             │
│  Google Calendar: ✓ Authorized                                    │
│                                                                    │
└──────────────────────────────────────────────────────────────────┘
```

This same layout handles: first-time setup, partial OAuth scopes, token expiry, and revoked access.

### States

| State | Behavior |
|-------|----------|
| **Loading** | Gray box skeleton placeholders matching card layout |
| **Integration setup** | Setup screen replaces queue entirely (see above) |
| **Empty (all caught up)** | Centered: "All caught up!" message |
| **Populated** | Sender-grouped event list as described |
| **Error (load failure)** | `alert alert-error` with automatic retry |

### Data Requirements

```javascript
import { fetchIntegrations } from '$lib/services/integrations'
import { fetchPendingEvents, updateEventStatus } from '$lib/services/events'
import { fetchEventSources } from '$lib/services/event-sources'

// 1. Check integrations
const { data: integrations } = await fetchIntegrations()
const gmail = integrations?.find(i => i.provider === 'gmail')
const gcal = integrations?.find(i => i.provider === 'google_calendar')
const bothOk = gmail?.status === 'active' && gcal?.status === 'active'

// 2. If both OK, load pending events
if (bothOk) {
  const { data: events } = await fetchPendingEvents()
  // Group by sender
}

// Actions (no confirmation, immediate)
await updateEventStatus(eventId, 'approved')   // Approve — event animates out
await updateEventStatus(eventId, 'rejected')   // Reject — event animates out

// Group approve — loop through all events in the group
for (const event of groupEvents) {
  await updateEventStatus(event.id, 'approved')
}
```

### Key Interactions

- **Accept (individual)**: calls `updateEventStatus(id, 'approved')`, triggers calendar sync. Event animates out of the list. No toast, no modal.
- **Approve all (sender menu)**: approves all events from that sender. Entire group animates out.
- **Reject all (sender menu)**: rejects all events from that sender. Entire group animates out.
- **Reject**: calls `updateEventStatus(id, 'rejected')`. Event animates out. No confirmation modal.
- **Edit**: navigates to `/app/events/[id]`.
- **Animation**: approved/rejected events slide out (or simply disappear if smooth animation isn't achievable). Remaining events reflow upward.

---

## 2. Event Detail

**Route:** `/app/events/[id]`

### Purpose

Side-by-side review screen for a single event. The core human-in-the-loop interface (FR-C.1). Shows source email on one side and editable extracted event fields on the other. Reached by tapping "Edit" on an event in the Review Queue.

Navigation (sticky top navbar) stays visible — this is a drill-down within Review, not a modal.

### Primary Actions
- Approve event
- Reject event

### Secondary Actions
- Navigate back to Review Queue

### Desktop Layout (lg:)

Side-by-side: `grid grid-cols-5 gap-6`.

```
┌─ Page Header ───────────────────────────────────────────────────┐
│ [← Back to Queue]  Edit Event                [Reject] [Approve] │
└─────────────────────────────────────────────────────────────────┘

┌─ Left Panel (col-span-2) ────────┐  ┌─ Right Panel (col-span-3) ────────┐
│                                    │  │                                     │
│  SOURCE EMAIL                      │  │  EXTRACTED EVENT                    │
│                                    │  │                                     │
│  From: school@district.edu         │  │  Title                              │
│  Date: Oct 1, 2026                 │  │  [Birthday Party for Emma       ]  │
│  Subject: Party Invitation         │  │                                     │
│                                    │  │  ☐ All day                          │
│  ───────────────────────           │  │                                     │
│                                    │  │  Date                               │
│  Dear Parents,                     │  │  [2026-10-05                     ]  │
│                                    │  │                                     │
│  You're invited to Emma's          │  │  Start Time                         │
│  birthday party!                   │  │  [14:00                          ]  │
│                                    │  │                                     │
│  Date: October 5th                 │  │  End Time                           │
│  Time: 2:00 PM - 5:00 PM          │  │  [17:00                          ]  │
│  Location: 123 Main Street         │  │                                     │
│                                    │  │  Location                           │
│  Please RSVP by Oct 3.            │  │  [123 Main Street               ]  │
│                                    │  │                                     │
│  ───────────────────────           │  │  Description                        │
│                                    │  │  [Birthday party. RSVP by Oct 3.]  │
│  Attachments:                      │  │                                     │
│  📎 invite.pdf [Open ↗]           │  │                                     │
│  🖼 party-photo.jpg [inline]      │  │                                     │
│                                    │  │                                     │
└────────────────────────────────────┘  └─────────────────────────────────────┘
```

- Images from attachments display inline within the source email content.
- PDF attachments are links that open in a new browser tab.
- The "All day" checkbox hides time fields when checked (standard calendar app pattern).

### Tablet Layout (md:)

Stacked. Source email on top (collapsible, starts expanded). Form below. Action buttons in sticky header.

```
┌─ Header (sticky) ─────────────────────────────────┐
│ [← Back]  Edit Event               [Reject] [Approve] │
└─────────────────────────────────────────────────────┘

┌─ Source (collapsible, starts expanded) ────────────┐
│ From: school@district.edu · Oct 1                   │
│ Subject: Party Invitation              [▲ Collapse] │
│ ─────────────────────────────────────────────────── │
│ Dear Parents, ...                                    │
│ 📎 invite.pdf [Open ↗]                              │
└─────────────────────────────────────────────────────┘

┌─ Event Form ───────────────────────────────────────┐
│ Title: [Birthday Party for Emma                  ]  │
│ ☐ All day                                           │
│ Date: [2026-10-05]  Start: [14:00]  End: [17:00]   │
│ Location: [123 Main Street                       ]  │
│ Description: [Birthday party. RSVP by Oct 3.    ]  │
└─────────────────────────────────────────────────────┘
```

### Mobile Layout (default)

Form-first. Source email behind a "View Source" collapse at top, closed by default.

```
┌─ View Source Email (collapse, closed) ─────────────┐
│ From: school@district.edu · Party Invitation  [▼]   │
└─────────────────────────────────────────────────────┘

┌─ Event Form ───────────────────────────────────────┐
│ Title                                                │
│ [Birthday Party for Emma                          ]  │
│                                                      │
│ ☐ All day                                            │
│                                                      │
│ Date                                                 │
│ [2026-10-05                                       ]  │
│                                                      │
│ Start Time                                           │
│ [14:00                                            ]  │
│                                                      │
│ End Time                                             │
│ [17:00                                            ]  │
│                                                      │
│ Location                                             │
│ [123 Main Street                                  ]  │
│                                                      │
│ Description                                          │
│ [Birthday party. RSVP by Oct 3.                   ]  │
│                                                      │
│ Attachments:                                         │
│ 📎 invite.pdf                          [Open ↗]      │
└─────────────────────────────────────────────────────┘

┌─ Fixed Bottom Bar ─────────────────────────────────┐
│         [Reject]                  [Approve]          │
└─────────────────────────────────────────────────────┘
```

Key mobile decisions:
- Action buttons in a **fixed bottom bar** (`fixed bottom-0 left-0 right-0`) — always reachable
- Content has `pb-24` to account for the fixed bottom action bar
- Source email collapsed by default — form fields are the priority
- Bottom tabs (Review, History, Settings) remain visible below the action bar per HIG

### States

| State | Behavior |
|-------|----------|
| **Loading** | Gray box skeletons for source panel + form fields |
| **Error (event not found)** | "Event not found" with "Back to Queue" link |
| **Error (load failure)** | `alert alert-error` with automatic retry |
| **Populated** | Full layout as described |
| **Submitting** | Action buttons show `loading loading-spinner loading-sm`, disabled |

### Data Requirements

```javascript
import { getEvent, updateEvent, updateEventStatus } from '$lib/services/events'
import { fetchEventSources } from '$lib/services/event-sources'
import { getEmail } from '$lib/services/emails'
import { fetchAttachments, getAttachmentUrl } from '$lib/services/attachments'
import { syncEventToCalendar } from '$lib/api/backend'

// Load event
const { data: event } = await getEvent(eventId)

// Load source email info via event sources
const { data: sources } = await fetchEventSources(eventId)
const sourceEmailId = sources?.[0]?.email_id
const { data: sourceEmail } = await getEmail(sourceEmailId)

// Load attachments for the source email
const { data: attachments } = await fetchAttachments(sourceEmailId)

// Auto-save edits (on blur or debounced)
await updateEvent(eventId, { title, start_datetime, end_datetime, all_day, location, description })

// Approve — event disappears from queue
await updateEventStatus(eventId, 'approved')
await syncEventToCalendar(eventId)
// Navigate back to Review Queue

// Reject — event disappears from queue
await updateEventStatus(eventId, 'rejected')
// Navigate back to Review Queue
```

### Key Interactions

- **Edit fields**: edits auto-save on blur or with debouncing. No "Save" button. The event stays in the queue with the user's changes until approved/rejected.
- **Approve**: validates required fields (title, date), saves any pending edits, sets status to `approved`, triggers `syncEventToCalendar()`, navigates back to Review Queue. Event is gone from queue.
- **Reject**: sets status to `rejected`, navigates back to Review Queue. No confirmation modal. Event is gone from queue.
- **Back button**: navigates back to Review Queue. Edits are already saved.
- **All-day checkbox**: when checked, Start Time and End Time fields are hidden (not just disabled — hidden). Standard calendar app pattern.
- **Image attachments**: displayed inline in the source email content.
- **PDF attachments**: rendered as links that open in a new browser tab.

### Form Fields

| Field | Input Type | Validation | Notes |
|-------|-----------|------------|-------|
| Title | `input input-bordered` | Required | |
| All Day | `checkbox` | — | Hides time fields when checked |
| Date | `input type="date"` | Required | |
| Start Time | `input type="time"` | Required when not all-day | Hidden when all-day checked |
| End Time | `input type="time"` | Must be after start | Hidden when all-day checked |
| Location | `input input-bordered` | Optional | |
| Description | `textarea textarea-bordered` | Optional | |

---

## 3. Activity History

**Route:** `/app/history`

### Purpose

Timeline of all actions — user approvals of **New** events and applied **Changes** (with field-level diffs from `change_set`). Every entry has an Undo button that returns the item to the matching Review lane (`pending_review` or `pending_change`).

History is retained forever. Undo is available forever.

### Primary Actions
- Undo a previous action

### What Shows in History

| Action Type | Entry Description | Undo Behavior |
|-------------|-------------------|---------------|
| User approved event | "You approved Birthday Party" | Removes from Google Calendar, returns to queue (original AI extraction, not user edits) |
| User rejected event | "You rejected Weekly Newsletter" | Returns to queue (original AI extraction) |
| User edited event | "You edited Dentist Appointment — changed time to 10:00 AM" | Reverts to previous field values |
| Auto-applied update | "Dentist Appointment was automatically updated — time changed from 2:00 PM to 3:00 PM" | Treated as rejecting the update. Event reverts to pre-update state. Logged as "update rejected" |
| Auto-applied cancellation | "Team Meeting was automatically cancelled" | Restores the event to pre-cancellation state |
| Sync failure | "Birthday Party failed to sync to calendar" | Retry button (not undo) |

**Not shown:** Email sync activity ("synced 3 emails"). That's background system noise, not user-relevant activity.

### Desktop Layout (lg:)

Timeline list, grouped by date. Full-width within page container.

```
Today
────────────────────────────────────────────────────────────────

┌─ Activity Entry ───────────────────────────────────────────────┐
│ 3:45 PM · You approved event                                    │
│ "Birthday Party for Emma" → synced to Personal Calendar         │
│ Source: Email from school@district.edu                           │
│                                                         [Undo]  │
└─────────────────────────────────────────────────────────────────┘

┌─ Activity Entry ───────────────────────────────────────────────┐
│ 2:30 PM · You rejected event                                    │
│ "Weekly Newsletter" — marked as not an event                    │
│ Source: Email from news@company.com                              │
│                                                         [Undo]  │
└─────────────────────────────────────────────────────────────────┘

Yesterday
────────────────────────────────────────────────────────────────

┌─ Activity Entry ───────────────────────────────────────────────┐
│ 5:15 PM · Event automatically updated                           │
│ "Dentist Appointment" — time changed from 2:00 PM to 3:00 PM   │
│ Source: Email from clinic@dental.com                             │
│                                                         [Undo]  │
└─────────────────────────────────────────────────────────────────┘

┌─ Activity Entry ───────────────────────────────────────────────┐
│ 4:00 PM · Sync failed                                           │
│ "Team Standup" — could not sync to Google Calendar              │
│                                                        [Retry]  │
└─────────────────────────────────────────────────────────────────┘

                         [Load More]
```

### Tablet Layout (md:)

Same as desktop. Full-width entries with slightly reduced padding.

### Mobile Layout (default)

Same timeline structure, full-width cards. Each entry is a card. "Undo" button is right-aligned within the card.

Date group headers use `divider` component: `<div class="divider">Today</div>`.

### States

| State | Behavior |
|-------|----------|
| **Loading** | Gray box skeleton placeholders |
| **Empty** | "No activity yet. When you review events, your actions will appear here." |
| **Populated** | Timeline list grouped by date |
| **Error** | `alert alert-error` with automatic retry |

### Data Requirements

```javascript
import { fetchEvents, updateEventStatus } from '$lib/services/events'
import { fetchEventSources, undoSourceContribution } from '$lib/services/event-sources'

// Load events with all non-pending statuses (these are "actioned" events)
const { data: events } = await fetchEvents({
  statuses: ['approved', 'synced', 'sync_failed', 'rejected', 'cancelled'],
  limit: 20,
  offset: page * 20
})

// Undo approved/synced event → revert to pending_review (original AI extraction)
await updateEventStatus(eventId, 'pending_review')

// Undo auto-update → revert event to pre-update state
await undoSourceContribution(sourceId)
```

Note: A dedicated activity log table may be needed for richer history (especially for tracking field-level diffs on auto-updates). Current implementation can derive basic activity from event status changes and timestamps.

### Key Interactions

- **Undo (approved/synced event)**: immediately reverts status to `pending_review`, deletes from Google Calendar (pre-Selko state = no event), returns event to Review Queue with original AI-extracted values. No confirmation modal on the happy path.
- **Undo (rejected event)**: returns event to `pending_review`, appears in Review Queue again with original AI-extracted values.
- **Undo (applied change)**: restores Selko fields from `event_snapshot_before`, PATCHes Google Calendar back to that state (keeps the calendar event), sets `pending_change`.
- **Undo when GCal was edited after Selko synced**: blocked with `CALENDAR_DIVERGED` (409). UI offers **Force Undo**, which applies the same pre-Selko calendar revert and overwrites the user's GCal edits.
- **Retry (sync failure)**: re-triggers `syncEventToCalendar()`.
- **Load More**: fetches next page, appends to list.

---

## 4. Settings

**Route:** `/app/settings`

### Purpose

Integration management, account settings, calendar configuration.

### Sections

#### Connected Accounts (Integrations)

This is where users manage their Google account connections after initial setup.

```
Connected Accounts
───────────────────────────────────────────────────────────
Google Account: user@gmail.com                [Disconnect]
  ✅ Gmail (reading emails)
  ✅ Google Calendar
     Syncing events to: [Personal Calendar ▼]

── If a scope is missing: ──

Google Account: user@gmail.com                [Disconnect]
  ✅ Gmail (reading emails)
  ❌ Google Calendar (not authorized)         [Authorize]
```

Per-service OAuth scope status is shown. If Calendar isn't authorized, an "Authorize" button triggers a scoped OAuth request for just that permission.

Photo-library connections are intentionally omitted while ingestion is parked; historical photo-sourced events still use the review rendering paths.

Disconnecting a Google account preserves all data. If reconnected later, sync resumes from where it left off (idempotent upsert).

Future: "Add another account" button for multiple Google accounts.

#### Account

| Field | Type | Notes |
|-------|------|-------|
| Email | Read-only | Shows current email address |
| Change Password | Button | Triggers Supabase password reset flow |

#### Calendar Defaults

| Field | Type | Notes |
|-------|------|-------|
| Default Calendar | Dropdown | Only shown if multiple calendars. Auto-selected if only one. |
| Timezone | Dropdown | User-settable. Affects event time display. |

### Layout

- Desktop: single centered column, `max-w-2xl mx-auto`. Sections separated by headings.
- Mobile: full-width sections separated by `divider`.

### Data Requirements

```javascript
import { fetchIntegrations } from '$lib/services/integrations'
import { getCalendarSettings, updateCalendarSettings } from '$lib/services/calendar-settings'
import { getGmailAuthUrl, listCalendars } from '$lib/api/backend'

// Load integrations
const { data: integrations } = await fetchIntegrations()

// Load calendar settings
const { data: calSettings } = await getCalendarSettings()

// Load available calendars (for default calendar dropdown)
const { data: calendars } = await listCalendars()

// Change default calendar
await updateCalendarSettings({ target_calendar_id: selectedCalendarId })

// Connect/reconnect OAuth
const authUrl = getGmailAuthUrl(window.location.origin + '/app/settings')
window.location.href = authUrl
```

### Key Interactions

- **Disconnect**: shows `ConfirmModal` ("Disconnect Google account? Your existing data will be preserved."). Revokes OAuth tokens.
- **Authorize (missing scope)**: triggers OAuth flow for just the missing permission. On return, status updates.
- **Change default calendar**: dropdown saves via `updateCalendarSettings()`.
- **OAuth error**: shown as toast (same pattern as initial setup OAuth errors).

### States

| State | Behavior |
|-------|----------|
| **Loading** | Gray box skeleton placeholders per section |
| **Populated** | Sections as described |
| **Error** | `alert alert-error` with automatic retry |
